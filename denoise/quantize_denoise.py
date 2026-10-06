"""Quantize a trained denoiser to what the core computes, and measure THAT.

    python denoise/quantize_denoise.py --ckpt denoise/dn_d7_c32.pt

The rules are the ones cifar/quantize_cifar.py uses for the board, unchanged:

  * activations unsigned 0..127 (the 7-bit input port), one scale per layer;
  * weights signed INT8 with one scale per output channel;
  * bias INT32 in the accumulator's unit a_scale * w_scale[c];
  * BatchNorm folded into the convolution; tap order (ky, kx, cin);
  * the core does conv + bias + ReLU in integers; the host requantizes between
    layers with clip(round(acc * requant[c]), 0, 127).

Two things are particular to the denoiser:

  * Layer 1's input is the noisy image, already 7-bit (common.quantize_input),
    so its scale is exactly 1/127 -- not calibrated.
  * With --skip models the last layer also takes the noisy image as one more
    input channel, at scale 1/127, while the features beside it have their own
    scale. One accumulator cannot add taps of two scales, so the ratio is folded
    into the weights of the image taps before they are quantized: the core still
    multiplies integers, and the host still feeds the image's own 7-bit values.
  * Residual models (train_denoise.py --residual) predict the noise z with a
    linear last layer. It is exported as two output channels, (w, b) and
    (-w, -b), so the core returns ReLU(z) and ReLU(-z); the host subtracts them
    (common.to_image). Both channels have the same largest weight, so they get
    the same INT8 scale and the difference is the integer z exactly -- the split
    adds no error of its own.

The PSNR printed for the integer model is what the board will produce, pixel for
pixel: the last layer's accumulator becomes an 8-bit image on the host.

Writes denoise/export/<name>/: conv<N>_config.bin, manifest.json, int_eval.json.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from common import (HERE, QMAX_A, load_set, pad_even, psnr, shuffle2, test_noise, to_image,
                    unshuffle2)
from train_denoise import Denoiser, board_cycles_per_pixel

QMIN_W, QMAX_W = -128, 127


def fold_bn(conv, bn):
    w = conv.weight.detach().double()
    s = bn.weight.detach().double()/torch.sqrt(bn.running_var.detach().double() + bn.eps)
    return w*s.reshape(-1, 1, 1, 1), bn.bias.detach().double() - bn.running_mean.detach().double()*s


def float_layers(net):
    """[(weight (cout,cin,3,3), bias (cout,))] of the plain conv+ReLU network."""
    L = [(net.first.weight.detach().double(), net.first.bias.detach().double())]
    L += [fold_bn(c, b) for c, b in zip(net.mid, net.bn)]
    w, b = net.last.weight.detach().double(), net.last.bias.detach().double()
    if getattr(net, 'residual', False):
        w, b = torch.cat([w, -w]), torch.cat([b, -b])       # the sign pair
    L.append((w, b))
    return L


def tap_order(w):
    """(cout, cin, ky, kx) -> (cout, K), K laid out as (ky, kx, cin)."""
    return w.permute(0, 2, 3, 1).reshape(w.shape[0], -1)


def from_tap_order(wk, cin):
    """Inverse of tap_order, for running the integer model as a convolution."""
    cout = wk.shape[0]
    return wk.reshape(cout, 3, 3, cin).permute(0, 3, 1, 2)


def im2col(q):
    """(C, H, W) integer map -> (H*W, 9C) windows in (ky, kx, cin) order, zero padded.

    This is the layout the board driver streams. Used here only to prove that
    the convolution form of the integer model is the same computation.
    """
    c, h, w = q.shape
    p = np.zeros((c, h+2, w+2), q.dtype)
    p[:, 1:h+1, 1:w+1] = q
    cols = np.stack([p[:, ky:ky+h, kx:kx+w] for ky in range(3) for kx in range(3)], 0)
    return cols.transpose(2, 3, 0, 1).reshape(h*w, 9*c)


class IntModel:
    """The integer pipeline the board runs, layer by layer."""
    def __init__(self, layers, skip, residual=False, unshuffle=False):
        self.layers, self.skip, self.residual, self.unshuffle = layers, skip, residual, unshuffle

    def layer(self, i, q):
        """One core pass: (C,H,W) 0..127 in -> INT32 accumulators after ReLU (COUT,H,W)."""
        L = self.layers[i]
        w = torch.from_numpy(L['wq']).double()                 # (cout, K)
        x = torch.from_numpy(q.astype(np.float64))[None]
        # Integers below 2**53 are exact in float64, so this IS integer arithmetic.
        acc = F.conv2d(x, from_tap_order(w, q.shape[0]), torch.from_numpy(L['bq']).double(),
                       padding=1)[0]
        acc = torch.clamp(acc, min=0).numpy()
        assert np.all(acc == np.rint(acc)) and acc.max() < 2**31
        return acc.astype(np.int64)

    def run(self, q_in):
        """7-bit noisy image (H,W) -> denoised 8-bit image (H,W), and the per-layer maps."""
        H, W = q_in.shape
        # An unshuffled model sees the four 2x2 phases of the (even-padded) image.
        base = unshuffle2(pad_even(q_in)) if self.unshuffle else q_in[None]
        base = base.astype(np.int64)
        q = base
        maps = []
        for i, L in enumerate(self.layers):
            if i == len(self.layers)-1 and self.skip:
                q = np.concatenate([q, base], 0)
            maps.append(q)
            acc = self.layer(i, q)
            if i < len(self.layers)-1:
                q = np.clip(np.rint(acc*L['requant'][:, None, None]), 0, QMAX_A).astype(np.int64)
            else:
                if self.unshuffle:
                    out = shuffle2(to_image(acc, base, L['to_pixel'], False), H, W)
                else:
                    out = to_image(acc, q_in, L['to_pixel'], self.residual)
        return out, maps


def quantize(FL, a_scale, skip, n_img=1):
    """Integer layers for the given input scales. Nothing is written.

    n_img is how many image channels the skip appends to the last layer's input
    (1, or 4 for an unshuffled model) -- always the last n_img input channels."""
    nl = len(FL)
    layers = []
    for i, (w, b) in enumerate(FL):
        wk = tap_order(w).numpy().copy()                       # (cout, K) float
        cout, K = wk.shape
        if i == nl-1 and skip:
            # Taps of input channel C (the image) carry scale 1/127, the rest
            # a_scale[i]: fold the ratio into those weights (see the docstring).
            cin = w.shape[1]
            img = np.arange(K) % cin >= cin - n_img
            wk[:, img] *= (1.0/QMAX_A)/a_scale[i]
        ws = np.abs(wk).max(axis=1)/QMAX_W
        ws[ws == 0] = 1.0
        wq = np.clip(np.rint(wk/ws[:, None]), QMIN_W, QMAX_W).astype(np.int64)
        bq = np.rint(b.numpy()/(a_scale[i]*ws)).astype(np.int64)
        worst = np.abs(bq) + QMAX_A*np.abs(wq).sum(axis=1)
        assert worst.max() <= 2**31-1, f'conv{i+1} accumulator could overflow INT32'
        L = dict(name=f'conv{i+1}', K=int(K), COUT=int(cout), wq=wq, bq=bq,
                 a_scale_in=a_scale[i], w_scale=ws, worst=int(worst.max()))
        if i < nl-1:
            L['requant'] = a_scale[i]*ws/a_scale[i+1]
        elif cout == 1 or (cout == 2 and np.allclose(ws[0], ws[1])):
            L['to_pixel'] = float(a_scale[i]*ws[0])            # accumulator -> [0,1] pixel
        else:
            L['to_pixel'] = [float(a_scale[i]*v) for v in ws]  # one per sub-image
        layers.append(L)
    return layers


def int_psnr(model, images):
    """Mean PSNR of the integer model on (name, clean, noisy) images."""
    vals = []
    for _, clean, noisy in images:
        out, _ = model.run(np.rint(noisy*QMAX_A).astype(np.int64))
        vals.append(psnr(clean, out.astype(np.float32)/255))
    return float(np.mean(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', type=Path, required=True)
    ap.add_argument('--calib', type=int, default=40, help='training images used for the ranges')
    ap.add_argument('--percentile', default='auto',
                    help='activation range percentile for every layer (100 = max, as for CIFAR), '
                         'or auto: the best on 40 validation images, first one value for all '
                         'layers, then refined layer by layer (see --global-only)')
    ap.add_argument('--global-only', action='store_true',
                    help='auto: stop after choosing one percentile for all layers')
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu', weights_only=False)
    residual = ck.get('residual', False)
    unshuffle = ck.get('unshuffle', False)
    net = Denoiser(ck['depth'], ck['channels'], ck['skip'], residual, unshuffle)
    n_img = 4 if unshuffle else 1
    net.load_state_dict(ck['state']); net.eval()
    name = args.ckpt.stem
    out_dir = args.out or HERE/'export'/name
    out_dir.mkdir(parents=True, exist_ok=True)
    sigma = ck['sigma']
    print(f'{name}: depth {ck["depth"]}, {ck["channels"]} channels, skip={ck["skip"]}, '
          f'residual={residual}, '
          f'sigma {sigma}, float Set12 {ck["set12_psnr"]:.2f} dB at training end')

    FL = float_layers(net)
    nl = len(FL)

    # ---- activation ranges, on the folded float network, from TRAINING images ----
    rng = np.random.default_rng(7)
    from common import add_noise
    calib = [add_noise(c, sigma, rng) for _, c in load_set('Train400')[::max(1, 400//args.calib)]]
    # A random sample of each layer's input values (all of them would not fit in
    # memory), plus the exact maximum, which is what percentile 100 uses.
    samples = [[] for _ in range(nl)]
    peak = [0.0]*nl
    with torch.no_grad():
        for x in calib:
            x0 = (torch.from_numpy(unshuffle2(pad_even(x))).double()[None] if unshuffle
                  else torch.from_numpy(x).double()[None, None])
            h = x0
            for i, (w, b) in enumerate(FL):
                v = h[0, :ck['channels']].reshape(-1).numpy()   # features only, not the image
                peak[i] = max(peak[i], float(v.max()))
                samples[i].append(rng.choice(v, size=min(20000, v.size), replace=False))
                if i == nl-1 and ck['skip']:
                    h = torch.cat([h, x0], 1)
                h = F.relu(F.conv2d(h, w, b, padding=1))
    pooled = [np.concatenate(v) for v in samples]

    def scales(pcts):
        """Input scales for one percentile per layer (layer 1's input is the 7-bit image)."""
        a = [1.0/QMAX_A]
        for i in range(1, nl):
            p = pcts[i]
            a.append((peak[i] if p >= 100 else float(np.percentile(pooled[i], p)))/QMAX_A)
        return a

    # ---- choose the range percentile on VALIDATION images, never on the tests ----
    # Train400[5::10] -- 40 training images disjoint from the calibration ones.
    # They were seen in training, which flatters every candidate equally; what
    # is compared here is how much each range loses to quantization.
    #
    # One value for every layer is not enough when layers differ: on the
    # unshuffled 64-channel model the PSNR fell from 28.5 to 16 dB between
    # percentile 99.95 and 99.995, a step the old five-value grid jumped over.
    # So the grid is finer, and after the best common value each layer in turn
    # takes the grid value that is best with the others held (one sweep of
    # coordinate ascent), still scored on the validation images only.
    GRID = (100.0, 99.999, 99.995, 99.99, 99.98, 99.97, 99.95, 99.9, 99.5)
    search = []
    if args.percentile == 'auto':
        vrng = np.random.default_rng(11)
        val = [(n, c, add_noise(c, sigma, vrng)) for n, c in load_set('Train400')[5::10]]

        def score(pcts):
            return int_psnr(IntModel(quantize(FL, scales(pcts), ck['skip'], n_img),
                                     ck['skip'], residual, unshuffle), val)
        tried = {}
        for g in GRID:
            tried[g] = score([g]*nl)
            print(f'  range percentile {g:<7} validation PSNR {tried[g]:.3f} dB')
        g = max(tried, key=tried.get)
        pcts, best = [g]*nl, tried[g]
        print(f'  -> percentile {g} for every layer')
        if not args.global_only:
            for i in range(1, nl):
                for cand in GRID:
                    if cand == pcts[i]:
                        continue
                    trial = pcts[:i] + [cand] + pcts[i+1:]
                    v = score(trial)
                    if v > best:
                        pcts, best = trial, v
                search.append(dict(layer=f'conv{i+1}', percentile=pcts[i], validation_psnr=best))
                print(f'  conv{i+1} input: percentile {pcts[i]:<7} validation PSNR {best:.3f} dB')
    else:
        pcts, tried = [float(args.percentile)]*nl, {}
    a_scale = scales(pcts)
    layers = quantize(FL, a_scale, ck['skip'], n_img)
    for L in layers:
        blob = np.concatenate([L['wq'].reshape(-1).astype('<i4'), L['bq'].astype('<i4')])
        (out_dir/f'{L["name"]}_config.bin').write_bytes(blob.tobytes())
        print(f'  {L["name"]}: K={L["K"]:>4} COUT={L["COUT"]:>3}  input scale {L["a_scale_in"]:.6f}  '
              f'worst accumulator {L["worst"]:>11,}')

    model = IntModel(layers, ck['skip'], residual, unshuffle)
    if residual:
        L = layers[-1]
        assert L['COUT'] == 2 and np.array_equal(L['wq'][0], -L['wq'][1]) \
            and L['bq'][0] == -L['bq'][1], 'the sign pair did not quantize symmetrically'

    # ---- the convolution form must equal what the board streams (im2col) ----
    q_in = np.rint(calib[0][:24, :20]*QMAX_A).astype(np.int64)
    _, maps = model.run(q_in)
    for i, L in enumerate(layers):
        cols = im2col(maps[i])
        ref = np.maximum(0, cols @ L['wq'].T + L['bq'])          # (H*W, cout)
        got = model.layer(i, maps[i]).reshape(L['COUT'], -1).T
        assert np.array_equal(ref, got), f'conv{i+1}: conv form differs from im2col form'
    print('integer conv form == im2col form on every layer (the layout the board streams)')

    # ---- PSNR: float model vs the integer model, same noisy images ----
    res = {}
    for set_name in ('Set12', 'BSD68'):
        tests = test_noise(load_set(set_name), sigma, seed=0)
        fl, it, per = [], [], {}
        with torch.no_grad():
            for n, clean, noisy in tests:
                f_out = net(torch.from_numpy(noisy)[None, None])[0, 0].numpy()
                q = np.rint(noisy*QMAX_A).astype(np.int64)
                i_out, _ = model.run(q)
                fl.append(psnr(clean, f_out))
                it.append(psnr(clean, i_out.astype(np.float32)/255))
                per[n] = it[-1]
        res[set_name] = dict(float=float(np.mean(fl)), integer=float(np.mean(it)), per_image=per)
        print(f'{set_name:<6} float {np.mean(fl):6.2f} dB   integer (board) {np.mean(it):6.2f} dB   '
              f'({np.mean(it)-np.mean(fl):+.2f})')

    shapes = [(L['name'], L['K'], L['COUT']) for L in layers]
    cpp = board_cycles_per_pixel(shapes, windows_per_pixel=0.25 if unshuffle else 1.0)
    (out_dir/'manifest.json').write_text(json.dumps(dict(
        note='activations unsigned 0..127; weights INT8 per output channel; tap order (ky, kx, cin); '
             'last layer output -> pixel = clip(round(acc*to_pixel*255), 0, 255)',
        model=name, depth=ck['depth'], channels=ck['channels'], skip=ck['skip'], sigma=sigma,
        percentile_by_layer=pcts[1:],      # layer 1's input is the image, fixed at 1/127
        validation_psnr_by_percentile={str(k): v for k, v in tried.items()},
        per_layer_search=search,
        layers=[dict(name=L['name'], K=L['K'], COUT=L['COUT'], a_scale_in=L['a_scale_in'],
                     w_scale=[float(v) for v in L['w_scale']],
                     **({'requant': [float(v) for v in L['requant']]} if 'requant' in L
                        else {'to_pixel': L['to_pixel']}),
                     config=f'{L["name"]}_config.bin', worst_accumulator=L['worst'])
                for L in layers],
        input_channel_appended_to_last_layer=ck['skip'],
        residual_output=residual,
        unshuffle=unshuffle,
        board_cycles_per_pixel=cpp), indent=2), encoding='utf-8')
    (out_dir/'int_eval.json').write_text(json.dumps(res, indent=2), encoding='utf-8')
    print(f'board cost {cpp:.0f} cycles/pixel (model, dense): 256x256 {cpp*65536/50e6:.2f} s, '
          f'512x512 {cpp*262144/50e6:.2f} s at 50 MHz')
    print(f'wrote {out_dir}')


if __name__ == '__main__':
    main()
