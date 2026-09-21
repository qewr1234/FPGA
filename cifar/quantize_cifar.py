"""Quantize the trained CIFAR-10 network and write what the board needs.

What comes out is one config blob per convolution -- the weights and biases in
the core's tap order -- plus a manifest holding the scales the host needs to
requantize between layers, and the classifier it runs itself.

The quantization has to match the hardware exactly, so:

  * Activations are unsigned 0..127, because the core's input port is 7 bits.
    One scale per layer, taken from the largest activation seen on the
    calibration images.
  * Weights are signed INT8, scaled PER OUTPUT CHANNEL. The core never sees a
    scale -- it multiplies integers -- and the bias is already per channel and
    INT32, so a per-channel weight scale costs the hardware nothing and is
    worth a point or so of accuracy over one scale per layer.
  * Bias is quantized in units of a_scale * w_scale[c], which is the unit the
    accumulator is already in.
  * BatchNorm is folded into the convolution first, so what ships is plain
    conv + bias + ReLU.

Tap order is (ky, kx, cin): tap index = (ky*3 + kx)*cin + c. That is the order
the existing config.bin uses, established by matching against it rather than
assumed, and export_featuremap.py builds its windows the same way.

    python cifar/quantize_cifar.py            # quantize, verify, export
    python cifar/quantize_cifar.py --limit 2000

Writes cifar/export/ : conv<N>_config.bin per layer, and manifest.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

HERE = Path(__file__).resolve().parent
QMAX_A, QMIN_W, QMAX_W = 127, -128, 127


def fold_bn(conv, bn):
    """BatchNorm into the convolution, giving weight and bias for plain conv."""
    w = conv.weight.detach().clone()
    g = bn.weight.detach(); b = bn.bias.detach()
    m = bn.running_mean.detach(); v = bn.running_var.detach()
    s = g/torch.sqrt(v + bn.eps)
    return w*s.reshape(-1, 1, 1, 1), b - m*s


def tap_order(w):
    """(cout, cin, ky, kx) -> (cout, K) with K laid out as (ky, kx, cin)."""
    return w.permute(0, 2, 3, 1).reshape(w.shape[0], -1).contiguous()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', type=Path, default=HERE/'cifar_cnn.pt')
    ap.add_argument('--out', type=Path, default=HERE/'export')
    ap.add_argument('--calib', type=int, default=512, help='images used for the ranges')
    ap.add_argument('--limit', type=int, default=0, help='test images for the accuracy check')
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(HERE))
    from train_cifar import Net, CONVS

    ck = torch.load(args.ckpt, map_location='cpu', weights_only=False)
    net = Net(); net.load_state_dict(ck['state']); net.eval()
    print(f'loaded {args.ckpt}  (float test accuracy {ck["acc"]*100:.2f}%)')

    te = transforms.ToTensor()
    ds = datasets.CIFAR10(HERE/'data', train=False, download=True, transform=te)
    if args.limit:
        ds = Subset(ds, range(min(args.limit, len(ds))))
    dl = DataLoader(ds, 256, shuffle=False)
    calib = torch.stack([ds[i][0] for i in range(min(args.calib, len(ds)))])

    # --- 1. fold BN ---
    folded = [fold_bn(c, b) for c, b in zip(net.conv, net.bn)]

    # --- 2. activation ranges, on the folded float network ---
    # The input to layer 0 is the image in [0,1]; after that it is the ReLU
    # output of the previous layer, rescaled and pooled the way the host will.
    acts, x = [], calib
    with torch.no_grad():
        for i, (w, b) in enumerate(folded):
            acts.append(float(x.max()))
            x = F.relu(F.conv2d(x, w, b, padding=1))
            if i % 2 == 1:
                x = F.max_pool2d(x, 2)
    a_scale = [a/QMAX_A for a in acts]
    out_scale = float(x.max())/QMAX_A      # scale of the last layer's output
    print('\nactivation ranges from the calibration images:')
    for i, a in enumerate(acts):
        print(f'  conv{i+1} input max {a:8.4f}  ->  scale {a_scale[i]:.6f}')

    # --- 3. quantize ---
    args.out.mkdir(parents=True, exist_ok=True)
    layers = []
    for i, (w, b) in enumerate(folded):
        wf = tap_order(w).numpy().astype(np.float64)          # (cout, K)
        cout, K = wf.shape
        ws = np.abs(wf).max(axis=1)/QMAX_W                    # per output channel
        ws[ws == 0] = 1.0                                     # a dead channel
        wq = np.clip(np.rint(wf/ws[:, None]), QMIN_W, QMAX_W).astype(np.int32)
        bq = np.rint(b.numpy().astype(np.float64)/(a_scale[i]*ws)).astype(np.int64)

        worst = np.abs(bq) + QMAX_A*np.abs(wq).sum(axis=1)
        assert worst.max() <= 2**31-1, \
            f'conv{i+1} accumulator could overflow INT32: {worst.max():,}'
        assert np.abs(bq).max() <= 2**31-1, f'conv{i+1} bias does not fit INT32'

        # config.bin: cout*K weight words (low byte), then cout bias words --
        # the order window_mac_axis walks when it is in configuration mode.
        blob = np.concatenate([wq.reshape(-1).astype('<i4'),
                               bq.astype('<i4')])
        path = args.out/f'conv{i+1}_config.bin'
        path.write_bytes(blob.tobytes())

        nxt = a_scale[i+1] if i+1 < len(folded) else out_scale
        layers.append(dict(
            name=f'conv{i+1}', K=int(K), COUT=int(cout),
            a_scale_in=a_scale[i], a_scale_out=nxt,
            w_scale=[float(v) for v in ws],
            # host requant: clip(round(acc * requant[c]), 0, 127)
            requant=[float(a_scale[i]*v/nxt) for v in ws],
            pool_after=(i % 2 == 1),
            config=path.name, config_words=int(blob.size),
            worst_accumulator=int(worst.max())))
        print(f'  conv{i+1}: K={K:>5} COUT={cout:>4}  worst accumulator '
              f'{worst.max():>12,}  -> {path.name}')

    # --- 4. the classifier the host runs ---
    fc_w = net.fc.weight.detach().numpy().astype(float)
    fc_b = net.fc.bias.detach().numpy().astype(float)

    (args.out/'manifest.json').write_text(json.dumps(dict(
        note='activations unsigned 0..127; weights INT8 per output channel; '
             'tap order (ky, kx, cin)',
        float_accuracy=ck['acc'], convs=CONVS, layers=layers,
        K_MAX=max(l['K'] for l in layers), COUT_MAX=max(l['COUT'] for l in layers),
        fc_weight=fc_w.tolist(), fc_bias=fc_b.tolist(),
        fc_input_scale=out_scale), indent=2), encoding='utf-8')

    # --- 5. does the integer network still classify? ---
    print('\nrunning the integer model (exactly what the board computes)...')
    ok = n = 0
    for xb, yb in dl:
        q = np.clip(np.rint(xb.numpy()/a_scale[0]), 0, QMAX_A).astype(np.int64)
        for i, L in enumerate(layers):
            wq = np.frombuffer((args.out/L['config']).read_bytes(), dtype='<i4')
            cout, K = L['COUT'], L['K']
            w = wq[:cout*K].reshape(cout, K).astype(np.int64)
            bq = wq[cout*K:].astype(np.int64)
            B, _, H, W = q.shape
            # (ky, kx, cin) windows, padding 1 -- the same order as the weights
            pad = np.zeros((B, q.shape[1], H+2, W+2), np.int64)
            pad[:, :, 1:H+1, 1:W+1] = q
            cols = np.stack([pad[:, :, ky:ky+H, kx:kx+W]
                             for ky in range(3) for kx in range(3)], axis=1)
            cols = cols.transpose(0, 3, 4, 1, 2).reshape(B*H*W, K)
            acc = np.maximum(0, cols @ w.T + bq)              # conv + bias + ReLU
            r = np.asarray(L['requant'])
            q = np.clip(np.rint(acc*r), 0, QMAX_A).astype(np.int64)
            q = q.reshape(B, H, W, cout).transpose(0, 3, 1, 2)
            if L['pool_after']:
                q = q.reshape(B, cout, H//2, 2, W//2, 2).max(axis=(3, 5))
            H, W = q.shape[2], q.shape[3]
        feat = q.mean(axis=(2, 3))*out_scale                   # GAP, back to float
        pred = (feat @ fc_w.T + fc_b).argmax(1)
        ok += (pred == yb.numpy()).sum(); n += len(yb)
    print(f'\nfloat   accuracy: {ck["acc"]*100:6.2f}%')
    print(f'integer accuracy: {ok/n*100:6.2f}%   ({n} images)')
    print(f'                  {(ok/n - ck["acc"])*100:+.2f} points from quantization')
    print(f'\nwritten to {args.out}')


if __name__ == '__main__':
    main()
