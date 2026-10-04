"""Train a small DnCNN-style denoiser that the accelerator can run as it is.

    python denoise/train_denoise.py                         # depth 7, 32 channels
    python denoise/train_denoise.py --depth 5 --channels 16 --epochs 2   # quick try

The structure is DnCNN's (Zhang et al. 2017): conv+ReLU, then conv+BN+ReLU
repeated, then a last conv, all 3x3 with zero padding. Three things are changed
to fit the hardware, and each is a property of the core, not a choice:

  * The last layer outputs the CLEAN IMAGE, not the noise. DnCNN predicts the
    noise and subtracts it, but noise is signed and the core applies ReLU to
    every output it produces. A clean pixel is never negative, so ReLU costs
    the clean-image output nothing.
    --residual instead gets DnCNN's noise prediction past the ReLU: the last
    layer becomes a sign pair, (w, b) and (-w, -b), and the host subtracts the
    two ReLU outputs (see Denoiser).
  * --skip feeds the noisy image into the last layer as one more input channel
    (concatenation). That gives the network the easy path DnCNN's residual gives
    it -- "copy the input, then correct it" -- without a subtraction the core
    cannot do. It costs 9 taps on one layer.
  * The input is clipped and quantized to 7 bits during training exactly as it
    will be on the board (common.add_noise), so the network never sees an input
    it will not get.

Training follows DnCNN's data generator: 40x40 patches from the Train400 images
at scales 1, 0.9, 0.8, 0.7, with the 8 flips/rotations, sigma 25, MSE, Adam.
DnCNN draws ~240k patches per epoch; this draws --patches fresh random ones per
epoch (default 32k) so an epoch fits a CPU.

Writes denoise/<name>.pt and denoise/<name>_train.json (curve, Set12 PSNR).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

from common import HERE, QMAX_A, load_set, psnr, test_noise

sys.path.insert(0, str(HERE.parent/'scripts'))
from cifar_budget import dense_per_group, per_window  # noqa: E402

K_MAX, COUT_MAX = 1152, 128      # what the board build provides


class Denoiser(nn.Module):
    """residual=False: the last layer outputs the clean image through the core's
    ReLU (optionally with the noisy image as an extra input, skip).

    residual=True: DnCNN's residual learning -- the last layer outputs the noise
    z, linear, and the clean image is x - z. The core cannot output a signed z,
    because it applies ReLU to everything. So the last layer is built as TWO
    output channels with weights (w, b) and (-w, -b): the core returns ReLU(z)
    and ReLU(-z), and the host takes their difference, which is z exactly --
    in float, and in integers too, because both channels share one weight scale.
    The float model below is therefore the plain linear-output DnCNN; nothing
    about the split needs training."""
    def __init__(self, depth=7, channels=32, skip=True, residual=False, unshuffle=False):
        super().__init__()
        if residual:
            skip = False                    # the residual already carries the input
        assert not (residual and unshuffle), 'residual with unshuffle is not implemented'
        self.depth, self.channels, self.skip, self.residual = depth, channels, skip, residual
        self.unshuffle = unshuffle
        # unshuffle (FFDNet, Zhang et al. 2018): the image is split into its four
        # 2x2 phases and the network runs on those half-size sub-images, then
        # the four outputs are put back together. A quarter of the windows, each
        # 3x3 tap covering twice the distance.
        self.img_ch = 4 if unshuffle else 1
        c = channels
        self.first = nn.Conv2d(self.img_ch, c, 3, padding=1, bias=True)
        self.mid = nn.ModuleList(nn.Conv2d(c, c, 3, padding=1, bias=False) for _ in range(depth-2))
        self.bn = nn.ModuleList(nn.BatchNorm2d(c) for _ in range(depth-2))
        self.last = nn.Conv2d(c + (self.img_ch if skip else 0), self.img_ch, 3, padding=1, bias=True)

    def forward(self, x):
        if self.unshuffle:
            hh, ww = x.shape[-2:]
            x = F.pad(x, (0, ww % 2, 0, hh % 2), mode='replicate')   # = common.pad_even
            x = F.pixel_unshuffle(x, 2)
        h = F.relu(self.first(x))
        for conv, bn in zip(self.mid, self.bn):
            h = F.relu(bn(conv(h)))
        if self.skip:
            h = torch.cat([h, x], 1)
        if self.residual:
            return x - self.last(h)         # ReLU(z) - ReLU(-z) = z, done on the host
        y = F.relu(self.last(h))            # the core's ReLU, on the image itself
        if self.unshuffle:
            y = F.pixel_shuffle(y, 2)[..., :hh, :ww]
        return y

    def layer_shapes(self):
        """(name, K, COUT) per layer, K = 9 * input channels, tap order (ky,kx,cin)."""
        c, g = self.channels, self.img_ch
        s = [('conv1', 9*g, c)] + [(f'conv{i+2}', 9*c, c) for i in range(self.depth-2)]
        # The residual layer's two output channels are the sign pair.
        s.append((f'conv{self.depth}', 9*(c + (g if self.skip else 0)),
                  2 if self.residual else g))
        return s

    def windows_per_pixel(self):
        return 0.25 if self.unshuffle else 1.0


def board_cycles_per_pixel(shapes, p=16, t=4, windows_per_pixel=1.0):
    """Cycles one output pixel costs the board core (P=16, T=4), dense mode.

    scripts/cifar_budget.py's per-window model, which reproduces every measured
    configuration within 1.3 cycles; on the CIFAR run it read about one cycle
    per window low (289 measured for 288), more on very short windows (32 for
    K=27). Dense mode is the upper bound: sparse mode only shortens the issue
    term, and where the feed floor K dominates it changes nothing.
    """
    return windows_per_pixel*sum(per_window(k, cout, p, t, dense_per_group(k, t))
                                 for _, k, cout in shapes)


class Patches:
    """DnCNN's patch source: square crops of the training images at 4 scales.

    40x40 for DnCNN; FFDNet uses 50x50 for grayscale, and an unshuffled model
    needs the larger patch, its receptive field being about 42 pixels wide."""
    def __init__(self, images, patch=40, scales=(1.0, 0.9, 0.8, 0.7)):
        self.patch = patch
        self.pyr = []
        for _, im in images:
            h, w = im.shape
            for s in scales:
                hs, ws = int(h*s), int(w*s)
                pil = Image.fromarray(np.uint8(np.rint(im*255))).resize((ws, hs), Image.BICUBIC)
                self.pyr.append(np.asarray(pil, np.float32)/255.0)

    def sample(self, n, rng):
        out = np.empty((n, 1, self.patch, self.patch), np.float32)
        p = self.patch
        for i in range(n):
            im = self.pyr[rng.integers(len(self.pyr))]
            y = rng.integers(im.shape[0]-p+1); x = rng.integers(im.shape[1]-p+1)
            a = im[y:y+p, x:x+p]
            m = rng.integers(8)                          # 8 flips/rotations
            a = np.rot90(a, m % 4)
            if m >= 4:
                a = np.flipud(a)
            out[i, 0] = a
        return out


def noisy_batch(clean, sigma, rng):
    n = clean + rng.standard_normal(clean.shape).astype(np.float32)*(sigma/255.0)
    return np.rint(np.clip(n, 0, 1)*QMAX_A).astype(np.float32)/QMAX_A


def evaluate(net, tests):
    net.eval()
    vals = []
    with torch.no_grad():
        for _, clean, noisy in tests:
            out = net(torch.from_numpy(noisy)[None, None])[0, 0].numpy()
            vals.append(psnr(clean, out))
    net.train()
    return float(np.mean(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--depth', type=int, default=7)
    ap.add_argument('--channels', type=int, default=32)
    ap.add_argument('--no-skip', action='store_true', help='no noisy-image input to the last layer')
    ap.add_argument('--residual', action='store_true',
                    help='predict the noise (DnCNN residual learning) through a sign-split last layer')
    ap.add_argument('--unshuffle', action='store_true',
                    help='FFDNet-style: run on the four 2x2 phases at half resolution')
    ap.add_argument('--patch', type=int, default=40, help='training patch size (even)')
    ap.add_argument('--sigma', type=float, default=25)
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--patches', type=int, default=32768, help='random patches per epoch')
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--threads', type=int, default=0, help='torch threads (0 = default)')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--name', default=None, help='output name (default from the shape)')
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    net = Denoiser(args.depth, args.channels, not args.no_skip, args.residual, args.unshuffle)
    shapes = net.layer_shapes()
    for n, k, c in shapes:
        assert k <= K_MAX and c <= COUT_MAX, f'{n}: K={k} COUT={c} exceeds the board build'
    name = args.name or (f'dn_d{args.depth}_c{args.channels}' + ('_us' if net.unshuffle else '') +
                         ('_res' if net.residual else ('' if net.skip else '_noskip')))
    cpp = board_cycles_per_pixel(shapes, windows_per_pixel=net.windows_per_pixel())
    print(f'{name}: {sum(p.numel() for p in net.parameters()):,} parameters, '
          f'layers {[(k, c) for _, k, c in shapes]}')
    print(f'board cost {cpp:.0f} cycles/pixel -> 256x256 at 50 MHz: {cpp*65536/50e6:.2f} s')

    patches = Patches(load_set('Train400'), patch=args.patch)
    tests = test_noise(load_set('Set12'), args.sigma, seed=0)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    # DnCNN steps the rate down late in training; cosine does the same smoothly.
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs, eta_min=args.lr/20)

    curve = []
    t0 = time.time()
    for ep in range(1, args.epochs+1):
        clean = patches.sample(args.patches, rng)
        noisy = noisy_batch(clean, args.sigma, rng)
        order = rng.permutation(args.patches)
        tot = 0.0
        for i in range(0, args.patches, args.batch):
            idx = order[i:i+args.batch]
            x = torch.from_numpy(noisy[idx]); y = torch.from_numpy(clean[idx])
            loss = F.mse_loss(net(x), y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item()*len(idx)
        sched.step()
        val = evaluate(net, tests)
        curve.append(dict(epoch=ep, loss=tot/args.patches, set12_psnr=val,
                          seconds=round(time.time()-t0, 1)))
        print(f'epoch {ep:>3}/{args.epochs}  loss {tot/args.patches:.6f}  Set12 {val:.2f} dB  '
              f'{time.time()-t0:7.0f}s', flush=True)
        torch.save(dict(state=net.state_dict(), depth=args.depth, channels=args.channels,
                        skip=net.skip, residual=net.residual, unshuffle=net.unshuffle,
                        sigma=args.sigma, epoch=ep, set12_psnr=val),
                   HERE/f'{name}.pt')
    (HERE/f'{name}_train.json').write_text(json.dumps(dict(
        name=name, args=vars(args), layers=shapes, board_cycles_per_pixel=cpp,
        curve=curve), indent=2), encoding='utf-8')
    print(f'wrote {HERE/(name + ".pt")}')


if __name__ == '__main__':
    main()
