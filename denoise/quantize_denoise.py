"""Quantize a trained denoiser to what the core computes, and measure THAT.

    python denoise/quantize_denoise.py --ckpt denoise/dn_d7_c32.pt

The rules are the ones cifar/quantize_cifar.py uses for the board, unchanged:

  * activations unsigned 0..127 (the 7-bit input port), one scale per map;
  * weights signed INT8 with one scale per output channel;
  * bias INT32 in the accumulator's unit a_scale * w_scale[c];
  * BatchNorm folded into the convolution; tap order (ky, kx, cin);
  * the core does conv + bias + ReLU in integers; the host requantizes between
    layers with clip(round(acc * requant[c]), 0, 127).

A model is a graph of nodes (train_denoise: node, unet_spec); each node is one
core pass over a window of its input maps concatenated, and the host applies
the node's post-op (maxout, pixel shuffle) to the requantized codes. Things
particular to the denoiser:

  * The image is the map 'image', already 7-bit (common.quantize_input), so
    its scale is exactly 1/127 -- not calibrated.
  * A node that reads several maps (the last layer with the image appended,
    a U-Net's decoder) sees several scales. One accumulator cannot add taps of
    two scales, so each other map's ratio to the first map's scale is folded
    into the weights of its taps before they are quantized: the core still
    multiplies integers, and the host still feeds each map's own codes.
  * A shuffle2 node's output channels are quantized in groups of four, so each
    channel of the shuffled map keeps one scale.
  * Residual chain models (train_denoise.py --residual) predict the noise z
    with a linear last layer, exported as two output channels (w, b) and
    (-w, -b); the host subtracts ReLU(z) and ReLU(-z) (common.to_image).

The PSNR printed for the integer model is what the board will produce, pixel for
pixel: the last node's accumulator becomes an 8-bit image on the host.

Writes denoise/export/<name>/: <node>_config.bin, manifest.json, int_eval.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from common import (HERE, QMAX_A, add_noise, load_set, pad_mult, psnr, shuffle2, shuffle2c, test_noise,
                    to_image, unshuffle2)
from train_denoise import (QMAX_W, QMIN_W, Denoiser, FoldedQ, GraphDenoiser, board_cycles_per_pixel,
                           float_layers, graph_shapes, map_channels, node_padding, post_op)


def tap_order(w):
    """(cout, cin, kh, kw) -> (cout, K), K laid out as (ky, kx, cin)."""
    return w.permute(0, 2, 3, 1).reshape(w.shape[0], -1)


def from_tap_order(wk, cin, kh=3, kw=3):
    """Inverse of tap_order, for running the integer model as a convolution."""
    cout = wk.shape[0]
    return wk.reshape(cout, kh, kw, cin).permute(0, 3, 1, 2)


def out_size(n, h, w):
    """Output height and width of node n on an h x w input."""
    pad, d, s = node_padding(n), n['dilation'], n['stride']
    return (h + 2*pad - d*(n['kh']-1) - 1)//s + 1, (w + 2*pad - d*(n['kw']-1) - 1)//s + 1


def im2col(q, n):
    """(C, H, W) integer map -> (N, K) windows of node n in (ky, kx, cin) order,
    zero padded, tap (ky, kx) dilation*ky, dilation*kx away, one window per
    stride.

    This is the layout the board driver streams. Used here only to prove that
    the convolution form of the integer model is the same computation.
    """
    c, h, w = q.shape
    pad, d, s = node_padding(n), n['dilation'], n['stride']
    oh, ow = out_size(n, h, w)
    p = np.zeros((c, h+2*pad, w+2*pad), q.dtype)
    p[:, pad:pad+h, pad:pad+w] = q
    cols = np.stack([p[:, d*ky:d*ky+s*oh:s, d*kx:d*kx+s*ow:s]
                     for ky in range(n['kh']) for kx in range(n['kw'])], 0)
    return cols.transpose(2, 3, 0, 1).reshape(oh*ow, n['kh']*n['kw']*c)


def post_int(q, post):
    """The host side of a node on integer codes: (COUT, h, w) -> the map stored."""
    if post == 'maxout':
        # Requantization is monotonic per channel, so taking the max after it
        # is the max of the two real values, requantized.
        c = q.shape[0]//2
        return np.maximum(q[:c], q[c:])
    if post == 'shuffle2':
        return shuffle2c(q)
    return q


class IntModel:
    """The integer pipeline the board runs, node by node."""
    def __init__(self, layers, spec):
        self.layers, self.spec = layers, spec

    def layer(self, i, q):
        """One core pass: (C,H,W) 0..127 in -> INT32 accumulators after ReLU (COUT,oh,ow)."""
        L, n = self.layers[i], self.spec['nodes'][i]
        w = torch.from_numpy(L['wq']).double()                 # (cout, K)
        x = torch.from_numpy(q.astype(np.float64))[None]
        # Integers below 2**53 are exact in float64, so this IS integer arithmetic.
        acc = F.conv2d(x, from_tap_order(w, q.shape[0], n['kh'], n['kw']),
                       torch.from_numpy(L['bq']).double(), stride=n['stride'],
                       padding=node_padding(n), dilation=n['dilation'])[0]
        acc = torch.clamp(acc, min=0).numpy()
        assert np.all(acc == np.rint(acc)) and acc.max() < 2**31
        return acc.astype(np.int64)

    def run(self, q_in):
        """7-bit noisy image (H,W) -> denoised 8-bit image (H,W), and each node's input."""
        H, W = q_in.shape
        spec = self.spec
        img = pad_mult(q_in, spec['pad_to'])
        base = (unshuffle2(img) if spec['unshuffle'] else img[None]).astype(np.int64)
        maps, inputs = {'image': base}, []
        for i, (L, n) in enumerate(zip(self.layers, spec['nodes'])):
            q = np.concatenate([maps[k] for k in n['inputs']], 0)
            inputs.append(q)
            acc = self.layer(i, q)
            if i < len(self.layers)-1:
                q = np.clip(np.rint(acc*L['requant'][:, None, None]), 0, QMAX_A).astype(np.int64)
                maps[n['name']] = post_int(q, n['post'])
            elif spec['unshuffle']:
                out = shuffle2(to_image(acc, base, L['to_pixel'], False), H, W)
            else:
                out = to_image(acc, q_in, L['to_pixel'], spec['residual'])
        return out, inputs


def quantize(FL, spec, a_out):
    """Integer layers for the given output scales (one per node but the last).
    Nothing is written."""
    nodes, ch = spec['nodes'], map_channels(spec)
    scale = {'image': 1.0/QMAX_A}
    for i, n in enumerate(nodes[:-1]):
        scale[n['name']] = a_out[i]
    layers = []
    for i, ((w, b), n) in enumerate(zip(FL, nodes)):
        wk = tap_order(w).numpy().copy()                       # (cout, K) float
        cout, K = wk.shape
        cin = w.shape[1]
        a_main = scale[n['inputs'][0]]
        # Taps of every map but the first carry that map's scale ratio (docstring).
        cidx = np.arange(K) % cin                              # input channel of each tap
        start = 0
        for k, m in enumerate(n['inputs']):
            if k:
                wk[:, (cidx >= start) & (cidx < start+ch[m])] *= scale[m]/a_main
            start += ch[m]
        ws = np.abs(wk).max(axis=1)/QMAX_W
        if n['post'] == 'shuffle2':
            ws = np.repeat(ws.reshape(-1, 4).max(axis=1), 4)   # one scale per shuffled channel
        ws[ws == 0] = 1.0
        wq = np.clip(np.rint(wk/ws[:, None]), QMIN_W, QMAX_W).astype(np.int64)
        bq = np.rint(b.numpy()/(a_main*ws)).astype(np.int64)
        worst = np.abs(bq) + QMAX_A*np.abs(wq).sum(axis=1)
        assert worst.max() <= 2**31-1, f'{n["name"]} accumulator could overflow INT32'
        L = dict(name=n['name'], K=int(K), COUT=int(cout), wq=wq, bq=bq,
                 a_scale_in=float(a_main), w_scale=ws, worst=int(worst.max()))
        if i < len(nodes)-1:
            L['requant'] = a_main*ws/a_out[i]
            L['a_scale_out'] = float(a_out[i])
        elif cout == 1 or (cout == 2 and np.allclose(ws[0], ws[1])):
            L['to_pixel'] = float(a_main*ws[0])            # accumulator -> [0,1] pixel
        else:
            L['to_pixel'] = [float(a_main*v) for v in ws]  # one per sub-image
        layers.append(L)
    return layers


def float_run(FL, spec, x, record=None):
    """The folded float graph on one noisy image (H, W) in float64; record, a
    list per node, receives each node's output map (what the next node reads)."""
    img = pad_mult(x, spec['pad_to'])
    x0 = torch.from_numpy(unshuffle2(img) if spec['unshuffle'] else img[None]).double()[None]
    maps, nodes = {'image': x0}, spec['nodes']
    for i, ((w, b), n) in enumerate(zip(FL, nodes)):
        h = torch.cat([maps[k] for k in n['inputs']], 1)
        h = F.relu(F.conv2d(h, w, b, stride=n['stride'], padding=node_padding(n), dilation=n['dilation']))
        if i < len(nodes)-1:
            h = post_op(h, n['post'])
            maps[n['name']] = h
            if record is not None:
                record[i].append(h[0])
    return h


def int_psnr(model, images):
    """Mean PSNR of the integer model on (name, clean, noisy) images."""
    vals = []
    for _, clean, noisy in images:
        out, _ = model.run(np.rint(noisy*QMAX_A).astype(np.int64))
        vals.append(psnr(clean, out.astype(np.float32)/255))
    return float(np.mean(vals))


def load_model(ck):
    """The float model of a checkpoint (trained, or folded by qat_denoise.py) and its graph."""
    unshuffle = ck.get('unshuffle', False)
    dil = ck.get('dilation') or [1]*ck['depth']        # older checkpoints: plain 3x3
    if ck.get('folded'):
        spec = ck['graph'] if 'graph' in ck else Denoiser(
            ck['depth'], ck['channels'], ck['skip'], False, unshuffle, dil, ck.get('maxout', False)).graph()
        a_out = ck['a_out'] if 'a_out' in ck else ck['a_scale'][1:]
        net = FoldedQ(spec, ck['layers'], a_out)
        net.quant = False
    elif ck.get('arch') == 'unet':
        spec = ck['graph']
        net = GraphDenoiser(spec)
        net.load_state_dict(ck['state'])
    else:
        net = Denoiser(ck['depth'], ck['channels'], ck['skip'], ck.get('residual', False), unshuffle, dil,
                       ck.get('maxout', False))
        net.load_state_dict(ck['state'])
        spec = net.graph()
    net.eval()
    return net, spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', type=Path, required=True)
    ap.add_argument('--calib', type=int, default=40, help='training images used for the ranges')
    ap.add_argument('--percentile', default='auto',
                    help='activation range percentile for every map (100 = max, as for CIFAR), '
                         'or auto: the best on 40 validation images, first one value for all '
                         'maps, then refined map by map (see --global-only)')
    ap.add_argument('--global-only', action='store_true',
                    help='auto: stop after choosing one percentile for all maps')
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location='cpu', weights_only=False)
    folded = ck.get('folded', False)       # qat_denoise.py: BN folded, scales learned
    net, spec = load_model(ck)
    nodes = spec['nodes']
    nl = len(nodes)
    residual, unshuffle = spec['residual'], spec['unshuffle']
    skip = 'image' in nodes[-1]['inputs']
    maxout = any(n['post'] == 'maxout' for n in nodes)
    name = args.ckpt.stem
    out_dir = args.out or HERE/'export'/name
    out_dir.mkdir(parents=True, exist_ok=True)
    sigma = ck['sigma']
    what = (f'unet {spec["unet"]}' if 'unet' in spec else
            f'depth {ck["depth"]}, {ck["channels"]} channels, skip={skip}, residual={residual}, '
            f'dilation {ck.get("dilation")}, maxout={maxout}')
    print(f'{name}: {what}, sigma {sigma}, float Set12 {ck["set12_psnr"]:.2f} dB at training end')

    FL = float_layers(net)

    rng = np.random.default_rng(7)
    calib = [add_noise(c, sigma, rng) for _, c in load_set('Train400')[::max(1, 400//args.calib)]]
    if folded:
        # The scales were trained with the weights (qat_denoise.py); no search.
        a_out, pcts, tried, search = [float(v) for v in net.scales()], ['qat']*(nl-1), {}, []
    else:
        # ---- activation ranges, on the folded float network, from TRAINING images ----
        # A random sample of each map's values (all of them would not fit in
        # memory), plus the exact maximum, which is what percentile 100 uses.
        samples = [[] for _ in range(nl)]
        peak = [0.0]*nl
        with torch.no_grad():
            for x in calib:
                rec = [[] for _ in range(nl)]
                float_run(FL, spec, x, rec)
                # The chain quantizer also drew a (never used) sample of the
                # image map first; the draw is kept so that the random subsample
                # of every map, and so every committed export, stays the same.
                v = pad_mult(x, spec['pad_to']).reshape(-1)
                rng.choice(v, size=min(20000, v.size), replace=False)
                for i in range(nl-1):
                    v = rec[i][0].reshape(-1).numpy()
                    peak[i] = max(peak[i], float(v.max()))
                    samples[i].append(rng.choice(v, size=min(20000, v.size), replace=False))
        pooled = [np.concatenate(v) if v else None for v in samples]

        def scales(pcts):
            """Output scale per node but the last, one percentile each."""
            return [(peak[i] if pcts[i] >= 100 else float(np.percentile(pooled[i], pcts[i])))/QMAX_A
                    for i in range(nl-1)]

        # ---- choose the range percentile on VALIDATION images, never on the tests ----
        # Train400[5::10] -- 40 training images disjoint from the calibration ones.
        # They were seen in training, which flatters every candidate equally; what
        # is compared here is how much each range loses to quantization.
        #
        # One value for every map is not enough when layers differ: on the
        # unshuffled 64-channel model the PSNR fell from 28.5 to 16 dB between
        # percentile 99.95 and 99.995, a step the old five-value grid jumped over.
        # So the grid is finer, and after the best common value each map in turn
        # takes the grid value that is best with the others held (one sweep of
        # coordinate ascent), still scored on the validation images only.
        # 99 and 98 were added when a maxout model chose 99.5, the lowest value then
        # offered, on three layers.
        GRID = (100.0, 99.999, 99.995, 99.99, 99.98, 99.97, 99.95, 99.9, 99.5, 99.0, 98.0)
        search = []
        if args.percentile == 'auto':
            vrng = np.random.default_rng(11)
            val = [(n, c, add_noise(c, sigma, vrng)) for n, c in load_set('Train400')[5::10]]

            def score(pcts):
                return int_psnr(IntModel(quantize(FL, spec, scales(pcts)), spec), val)
            tried = {}
            for g in GRID:
                tried[g] = score([g]*(nl-1))
                print(f'  range percentile {g:<7} validation PSNR {tried[g]:.3f} dB')
            g = max(tried, key=tried.get)
            pcts, best = [g]*(nl-1), tried[g]
            print(f'  -> percentile {g} for every map')
            if not args.global_only:
                for i in range(nl-1):
                    for cand in GRID:
                        if cand == pcts[i]:
                            continue
                        trial = pcts[:i] + [cand] + pcts[i+1:]
                        v = score(trial)
                        if v > best:
                            pcts, best = trial, v
                    search.append(dict(map=nodes[i]['name'], percentile=pcts[i], validation_psnr=best))
                    print(f'  {nodes[i]["name"]} out: percentile {pcts[i]:<7} validation PSNR {best:.3f} dB')
        else:
            pcts, tried = [float(args.percentile)]*(nl-1), {}
        a_out = scales(pcts)
    layers = quantize(FL, spec, a_out)
    for L in layers:
        blob = np.concatenate([L['wq'].reshape(-1).astype('<i4'), L['bq'].astype('<i4')])
        (out_dir/f'{L["name"]}_config.bin').write_bytes(blob.tobytes())
        print(f'  {L["name"]:>5}: K={L["K"]:>4} COUT={L["COUT"]:>3}  input scale {L["a_scale_in"]:.6f}  '
              f'worst accumulator {L["worst"]:>11,}')

    model = IntModel(layers, spec)
    if residual:
        L = layers[-1]
        assert L['COUT'] == 2 and np.array_equal(L['wq'][0], -L['wq'][1]) \
            and L['bq'][0] == -L['bq'][1], 'the sign pair did not quantize symmetrically'

    # ---- the convolution form must equal what the board streams (im2col) ----
    q_in = np.rint(calib[0][:24, :20]*QMAX_A).astype(np.int64)
    _, inputs = model.run(q_in)
    for i, L in enumerate(layers):
        cols = im2col(inputs[i], nodes[i])
        ref = np.maximum(0, cols @ L['wq'].T + L['bq'])          # (N, cout)
        got = model.layer(i, inputs[i]).reshape(L['COUT'], -1).T
        assert np.array_equal(ref, got), f'{L["name"]}: conv form differs from im2col form'
    print('integer conv form == im2col form on every node (the layout the board streams)')

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

    cpp = board_cycles_per_pixel(graph_shapes(spec))
    (out_dir/'manifest.json').write_text(json.dumps(dict(
        note='activations unsigned 0..127; weights INT8 per output channel; tap order (ky, kx, cin); '
             'a node reads the concatenation of its input maps and the host applies its post-op to '
             'the requantized codes; last node output -> pixel = clip(round(acc*to_pixel*255), 0, 255)',
        model=name, graph=True, img_ch=spec['img_ch'], pad_to=spec['pad_to'],
        depth=nl, channels=ck['channels'], skip=skip, sigma=sigma,
        percentile_by_layer=pcts,          # one per map, in node order
        validation_psnr_by_percentile={str(k): v for k, v in tried.items()},
        per_layer_search=search,
        qat=folded,
        layers=[dict(name=L['name'], inputs=n['inputs'], kh=n['kh'], kw=n['kw'], stride=n['stride'],
                     dilation=n['dilation'], post=n['post'], wpp=n['wpp'], K=L['K'], COUT=L['COUT'],
                     a_scale_in=L['a_scale_in'],
                     w_scale=[float(v) for v in L['w_scale']],
                     **({'requant': [float(v) for v in L['requant']], 'a_scale_out': L['a_scale_out']}
                        if 'requant' in L else {'to_pixel': L['to_pixel']}),
                     config=f'{L["name"]}_config.bin', worst_accumulator=L['worst'])
                for n, L in zip(nodes, layers)],
        input_channel_appended_to_last_layer=skip,
        residual_output=residual,
        unshuffle=unshuffle,
        maxout=maxout,
        unet=spec.get('unet'),
        board_cycles_per_pixel=cpp), indent=2), encoding='utf-8')
    (out_dir/'int_eval.json').write_text(json.dumps(res, indent=2), encoding='utf-8')
    print(f'board cost {cpp:.0f} cycles/pixel (model, dense): 256x256 {cpp*65536/50e6:.2f} s, '
          f'512x512 {cpp*262144/50e6:.2f} s at 50 MHz')
    print(f'wrote {out_dir}')


if __name__ == '__main__':
    main()
