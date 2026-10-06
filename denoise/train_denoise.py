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

--dilation 1,2,3,4,3,2,1 makes layer i a 3x3 convolution with dilation d_i
(IRCNN, Zhang et al. 2017): the nine taps are d_i pixels apart. K, and so the
board's cycles, do not change -- the host builds the windows (im2col) and the
core sees K values either way -- but the receptive field grows from
1 + 2*depth to 1 + 2*sum(d_i).

--maxout makes every hidden layer compute TWO candidate maps per channel and
keep the larger, max(ReLU(a), ReLU(b)) = ReLU(max(a, b)) (maxout, Goodfellow et
al. 2013, as Max-Feature-Map pairs channel i with channel i+C). The core then
outputs 2C channels while the next layer still reads C, so K does not grow. On
this core a window costs max(K, ceil(COUT/16)*ceil(K/4)) cycles, and for
K = 288 that is 288 for COUT = 32 and for COUT = 64 alike: where the feed
bounds the layer, the second map costs nothing. The max is taken on the host,
in the requantization it already does between layers.

Writes denoise/<name>.pt and denoise/<name>_train.json (curve, Set12 PSNR).

Two ways to decide how long to train:

  --schedule cosine (default): a fixed --epochs, the rate annealed over them.
      How the existing models were trained.
  --schedule plateau: --epochs is only a ceiling. Every --val-every-th training
      image is held out (never sampled for patches) as a VALIDATION set; when its
      PSNR has not improved for --patience epochs the rate is halved, and when it
      has not improved for --stop-patience epochs, or the rate is below --min-lr,
      training stops. The checkpoint written is the best one on validation.
      Set12 is still printed every epoch, but it is a TEST set: nothing is
      decided by it.
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
    def __init__(self, depth=7, channels=32, skip=True, residual=False, unshuffle=False,
                 dilation=None, maxout=False):
        super().__init__()
        self.maxout = bool(maxout)
        m = 2 if self.maxout else 1          # maps computed per channel kept
        self.dilation = [int(d) for d in (dilation or [1]*depth)]
        assert len(self.dilation) == depth and min(self.dilation) >= 1, \
            f'need {depth} dilations >= 1, got {self.dilation}'
        dl = self.dilation
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
        self.first = nn.Conv2d(self.img_ch, m*c, 3, padding=dl[0], dilation=dl[0], bias=True)
        self.mid = nn.ModuleList(nn.Conv2d(c, m*c, 3, padding=dl[i+1], dilation=dl[i+1], bias=False)
                                 for i in range(depth-2))
        self.bn = nn.ModuleList(nn.BatchNorm2d(m*c) for _ in range(depth-2))
        self.last = nn.Conv2d(c + (self.img_ch if skip else 0), self.img_ch, 3,
                              padding=dl[-1], dilation=dl[-1], bias=True)

    def forward(self, x):
        if self.unshuffle:
            hh, ww = x.shape[-2:]
            x = F.pad(x, (0, ww % 2, 0, hh % 2), mode='replicate')   # = common.pad_even
            x = F.pixel_unshuffle(x, 2)
        h = self.pick(F.relu(self.first(x)))
        for conv, bn in zip(self.mid, self.bn):
            h = self.pick(F.relu(bn(conv(h))))
        if self.skip:
            h = torch.cat([h, x], 1)
        if self.residual:
            return x - self.last(h)         # ReLU(z) - ReLU(-z) = z, done on the host
        y = F.relu(self.last(h))            # the core's ReLU, on the image itself
        if self.unshuffle:
            y = F.pixel_shuffle(y, 2)[..., :hh, :ww]
        return y

    def pick(self, h):
        """maxout: channel i of the next layer's input is the larger of maps i and i+C."""
        if not self.maxout:
            return h
        c = self.channels
        return torch.maximum(h[:, :c], h[:, c:])

    def layer_shapes(self):
        """(name, K, COUT) per layer, K = 9 * input channels, tap order (ky,kx,cin).
        COUT is what the core computes: 2C on a maxout layer, of which C go on."""
        c, g = self.channels, self.img_ch
        m = 2 if self.maxout else 1
        s = [('conv1', 9*g, m*c)] + [(f'conv{i+2}', 9*c, m*c) for i in range(self.depth-2)]
        # The residual layer's two output channels are the sign pair.
        s.append((f'conv{self.depth}', 9*(c + (g if self.skip else 0)),
                  2 if self.residual else g))
        return s

    def windows_per_pixel(self):
        return 0.25 if self.unshuffle else 1.0

    def receptive_field(self):
        """Width in input pixels that one output pixel depends on."""
        return (1 + 2*sum(self.dilation))*(2 if self.unshuffle else 1)


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
    dev = next(net.parameters()).device
    vals = []
    with torch.no_grad():
        for _, clean, noisy in tests:
            out = net(torch.from_numpy(noisy)[None, None].to(dev))[0, 0].cpu().numpy()
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
    ap.add_argument('--maxout', action='store_true',
                    help='hidden layers compute 2C maps and keep the larger of each pair')
    ap.add_argument('--dilation', default=None,
                    help='comma separated dilation per layer, e.g. 1,2,3,4,3,2,1 (default all 1)')
    ap.add_argument('--patch', type=int, default=40, help='training patch size (even)')
    ap.add_argument('--sigma', type=float, default=25)
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--patches', type=int, default=32768, help='random patches per epoch')
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--threads', type=int, default=0, help='torch threads (0 = default)')
    ap.add_argument('--device', default='auto', help="auto (cuda when there is one), cuda or cpu")
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--name', default=None, help='output name (default from the shape)')
    ap.add_argument('--schedule', choices=['cosine', 'plateau'], default='cosine')
    ap.add_argument('--val-every', type=int, default=20,
                    help='plateau: hold out every N-th training image for validation')
    ap.add_argument('--patience', type=int, default=6, help='plateau: epochs before halving the rate')
    ap.add_argument('--stop-patience', type=int, default=15, help='plateau: epochs before stopping')
    ap.add_argument('--min-lr', type=float, default=2e-5, help='plateau: stop below this rate')
    ap.add_argument('--resume', action='store_true',
                    help='continue <name>: exactly from <name>_last.pt when it exists, otherwise '
                         'from the best checkpoint <name>.pt with a fresh optimizer at --lr')
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    dev = ('cuda' if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device
    dil = [int(v) for v in args.dilation.split(',')] if args.dilation else None
    net = Denoiser(args.depth, args.channels, not args.no_skip, args.residual,
                   args.unshuffle, dil, args.maxout).to(dev)
    print(f'device: {dev}')
    shapes = net.layer_shapes()
    for n, k, c in shapes:
        assert k <= K_MAX and c <= COUT_MAX, f'{n}: K={k} COUT={c} exceeds the board build'
    name = args.name or (f'dn_d{args.depth}_c{args.channels}' + ('_us' if net.unshuffle else '') +
                         ('_dil' if max(net.dilation) > 1 else '') + ('_mo' if net.maxout else '') +
                         ('_res' if net.residual else ('' if net.skip else '_noskip')))
    cpp = board_cycles_per_pixel(shapes, windows_per_pixel=net.windows_per_pixel())
    print(f'{name}: {sum(p.numel() for p in net.parameters()):,} parameters, '
          f'layers {[(k, c) for _, k, c in shapes]}, dilation {net.dilation}, '
          f'receptive field {net.receptive_field()}x{net.receptive_field()}')
    print(f'board cost {cpp:.0f} cycles/pixel -> 256x256 at 50 MHz: {cpp*65536/50e6:.2f} s')

    train_imgs = load_set('Train400')
    val = None
    if args.schedule == 'plateau':
        held = set(range(0, len(train_imgs), args.val_every))
        val = test_noise([im for i, im in enumerate(train_imgs) if i in held], args.sigma, seed=1)
        train_imgs = [im for i, im in enumerate(train_imgs) if i not in held]
        print(f'validation: {len(val)} training images held out, {len(train_imgs)} left to train on')
    patches = Patches(train_imgs, patch=args.patch)
    tests = test_noise(load_set('Set12'), args.sigma, seed=0)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    if args.schedule == 'cosine':
        # DnCNN steps the rate down late in training; cosine does the same smoothly.
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs, eta_min=args.lr/20)
    else:
        sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode='max', factor=0.5,
                                                           patience=args.patience)
    best_val, best_ep, stale = -1.0, 0, 0
    curve, start_ep, resumed = [], 1, None

    # Everything needed to continue exactly where training stopped, written every
    # epoch: the container this runs in can restart, and the best checkpoint
    # alone loses the optimizer, the schedule and the random state.
    last = HERE/f'{name}_last.pt'
    if args.resume:
        if last.exists():
            st = torch.load(last, map_location='cpu', weights_only=False)
            net.load_state_dict(st['state']); opt.load_state_dict(st['opt'])
            sched.load_state_dict(st['sched'])
            rng.bit_generator.state = st['np_rng']; torch.set_rng_state(st['torch_rng'])
            best_val, best_ep, stale, curve = st['best_val'], st['best_ep'], st['stale'], st['curve']
            start_ep = st['epoch'] + 1
            resumed = dict(kind='exact', from_epoch=st['epoch'])
        else:
            ck = torch.load(HERE/f'{name}.pt', map_location='cpu', weights_only=False)
            net.load_state_dict(ck['state'])
            for g in opt.param_groups:
                g['lr'] = args.lr
            best_val, best_ep = ck.get('val_psnr', -1.0), ck['epoch']
            start_ep = ck['epoch'] + 1
            # A different stream from the first run's, so its patches are not replayed.
            rng = np.random.default_rng([args.seed, start_ep])
            resumed = dict(kind='from_best', from_epoch=ck['epoch'],
                           note='optimizer, schedule and random state were not saved by the '
                                'interrupted run; continued from its best checkpoint with a '
                                'fresh Adam at --lr')
        print(f'resuming {name} at epoch {start_ep} ({resumed["kind"]}), best validation '
              f'{best_val:.3f} dB at epoch {best_ep}, lr {opt.param_groups[0]["lr"]:.1e}')

    def write_json():
        (HERE/f'{name}_train.json').write_text(json.dumps(dict(
            name=name, args=vars(args), layers=shapes, board_cycles_per_pixel=cpp,
            best_val_epoch=best_ep if val is not None else None, resumed=resumed,
            curve=curve), indent=2), encoding='utf-8')

    t0 = time.time()
    for ep in range(start_ep, args.epochs+1):
        clean = patches.sample(args.patches, rng)
        noisy = noisy_batch(clean, args.sigma, rng)
        order = rng.permutation(args.patches)
        tot = 0.0
        for i in range(0, args.patches, args.batch):
            idx = order[i:i+args.batch]
            x = torch.from_numpy(noisy[idx]).to(dev); y = torch.from_numpy(clean[idx]).to(dev)
            loss = F.mse_loss(net(x), y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item()*len(idx)
        t12 = evaluate(net, tests)
        rec = dict(epoch=ep, loss=tot/args.patches, set12_psnr=t12, lr=opt.param_groups[0]['lr'],
                   seconds=round(time.time()-t0, 1))
        ckpt = dict(state=net.state_dict(), depth=args.depth, channels=args.channels,
                    skip=net.skip, residual=net.residual, unshuffle=net.unshuffle,
                    dilation=net.dilation, maxout=net.maxout, sigma=args.sigma, epoch=ep,
                    set12_psnr=t12)
        if val is None:
            sched.step()
            torch.save(ckpt, HERE/f'{name}.pt')
            msg = ''
        else:
            v = evaluate(net, val)
            rec['val_psnr'] = v
            ckpt['val_psnr'] = v
            sched.step(v)
            if v > best_val:
                best_val, best_ep, stale = v, ep, 0
                torch.save(ckpt, HERE/f'{name}.pt')      # the best on validation
            else:
                stale += 1
            msg = f'val {v:.3f} dB (best {best_val:.3f} @ {best_ep})  lr {rec["lr"]:.1e}  '
        curve.append(rec)
        torch.save(dict(state=net.state_dict(), opt=opt.state_dict(), sched=sched.state_dict(),
                        np_rng=rng.bit_generator.state, torch_rng=torch.get_rng_state(),
                        epoch=ep, best_val=best_val, best_ep=best_ep, stale=stale, curve=curve),
                   last)
        write_json()
        print(f'epoch {ep:>3}/{args.epochs}  loss {tot/args.patches:.6f}  {msg}'
              f'Set12 {t12:.2f} dB (test, not used)  {time.time()-t0:7.0f}s', flush=True)
        if val is not None and (stale >= args.stop_patience or
                                opt.param_groups[0]['lr'] < args.min_lr):
            print(f'early stop at epoch {ep}: best validation {best_val:.3f} dB at epoch {best_ep}')
            break
    write_json()
    print(f'wrote {HERE/(name + ".pt")}')


if __name__ == '__main__':
    main()
