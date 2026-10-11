"""Quantization-aware fine-tuning: train the integer model the board runs.

    python denoise/qat_denoise.py --ckpt denoise/dn_d10_c64_us_es.pt --epochs 15

Takes a trained checkpoint, folds BatchNorm, and continues training a float
copy that computes exactly what the board computes (train_denoise.FoldedQ):
INT8 weights per output channel, 7-bit activations with one scale per layer,
rounding passed through with the straight-through estimator. The activation
scales are parameters, so they move with the weights; they start from the
percentile search of an existing export when there is one, else from the
99.99th percentile of a calibration pass.

Validation PSNR is measured with the quantization on, so the checkpoint kept
is the best INTEGER model, and quantize_denoise.py reads it ('folded': True)
without any range search: what it exports is what was trained.

Writes denoise/<name>.pt (best on validation), <name>_last.pt (resumable) and
<name>_train.json. Default name: <ckpt stem>_qat.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from common import HERE, QMAX_A, load_set, test_noise
from train_denoise import (Denoiser, FoldedQ, Patches, board_cycles_per_pixel, evaluate,
                           float_layers, noisy_batch)


def calibrate(model, images, pct=99.99, seed=7):
    """Input scale per layer from the float folded model: percentile of the
    features entering each layer on the given noisy images (the image's own
    scale is 1/127)."""
    nl = len(model.W)
    model.quant, model.record = False, [[] for _ in range(nl)]
    with torch.no_grad():
        for x in images:
            model(torch.from_numpy(x)[None, None])
    rng = np.random.default_rng(seed)
    a = [1.0/QMAX_A]
    for i in range(1, nl):
        v = torch.cat([f.reshape(-1) for f in model.record[i]]).numpy()
        v = rng.choice(v, size=min(400000, v.size), replace=False)
        a.append(float(np.percentile(v, pct))/QMAX_A)
    model.quant, model.record = True, None
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ckpt', type=Path, required=True)
    ap.add_argument('--epochs', type=int, default=15)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--patch', type=int, default=0, help='0: 50 if unshuffled else 40')
    ap.add_argument('--patches', type=int, default=20480)
    ap.add_argument('--batch', type=int, default=128)
    ap.add_argument('--sigma', type=float, default=0, help='0: the checkpoint\'s')
    ap.add_argument('--val-every', type=int, default=20)
    ap.add_argument('--scales', type=Path, default=None,
                    help='manifest.json whose a_scale_in start the scales (default: the '
                         'checkpoint\'s export when it exists, else a calibration pass)')
    ap.add_argument('--threads', type=int, default=0)
    ap.add_argument('--seed', type=int, default=3)
    ap.add_argument('--name', default=None)
    ap.add_argument('--resume', action='store_true')
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    ck = torch.load(args.ckpt, map_location='cpu', weights_only=False)
    assert not ck.get('residual', False), 'residual models are not supported'
    unshuffle = ck.get('unshuffle', False)
    dil = ck.get('dilation') or [1]*ck['depth']
    maxout = ck.get('maxout', False)
    sigma = args.sigma or ck['sigma']
    name = args.name or f'{args.ckpt.stem}_qat'
    patch = args.patch or (50 if unshuffle else 40)

    if ck.get('folded'):
        layers, a_scale = ck['layers'], list(ck['a_scale'])
        src = 'the folded checkpoint'
    else:
        net = Denoiser(ck['depth'], ck['channels'], ck['skip'], False, unshuffle, dil, maxout)
        net.load_state_dict(ck['state']); net.eval()
        layers = [(w.float(), b.float()) for w, b in float_layers(net)]
        man = args.scales or HERE/'export'/args.ckpt.stem/'manifest.json'
        if man.exists():
            m = json.loads(man.read_text())
            a_scale = [L['a_scale_in'] for L in m['layers']]
            src = str(man)
        else:
            a_scale = None
    model = FoldedQ(layers, a_scale or [1.0/QMAX_A]*len(layers), ck['channels'], ck['skip'],
                    unshuffle, dil, maxout)

    train_imgs = load_set('Train400')
    held = set(range(0, len(train_imgs), args.val_every))
    val = test_noise([im for i, im in enumerate(train_imgs) if i in held], sigma, seed=1)
    train_imgs = [im for i, im in enumerate(train_imgs) if i not in held]
    tests = test_noise(load_set('Set12'), sigma, seed=0)
    if a_scale is None:
        from common import add_noise
        crng = np.random.default_rng(7)
        calib = [add_noise(c, sigma, crng) for _, c in train_imgs[::10]]
        a_scale = calibrate(model, calib)
        with torch.no_grad():
            for p, v in zip(model.a, a_scale[1:]):
                p.fill_(v)
        src = 'a 99.99th-percentile calibration pass'
    shapes = Denoiser(ck['depth'], ck['channels'], ck['skip'], False, unshuffle, dil,
                      maxout).layer_shapes()
    cpp = board_cycles_per_pixel(shapes, windows_per_pixel=0.25 if unshuffle else 1.0)
    print(f'{name}: from {args.ckpt}, scales from {src}')
    print(f'  depth {ck["depth"]}, {ck["channels"]} channels, maxout={maxout}, dilation {dil}, '
          f'sigma {sigma}, board cost {cpp:.0f} cycles/pixel')

    model.quant = False
    f_val, f_set12 = evaluate(model, val), evaluate(model, tests)
    model.quant = True
    q_val, q_set12 = evaluate(model, val), evaluate(model, tests)
    print(f'  before: float val {f_val:.3f} / Set12 {f_set12:.2f}   '
          f'integer val {q_val:.3f} / Set12 {q_set12:.2f}  (loss {q_val-f_val:+.3f} / {q_set12-f_set12:+.2f})')

    patches = Patches(train_imgs, patch=patch)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs, eta_min=args.lr/10)
    best_val, best_ep, curve, start_ep = q_val, 0, [], 1
    last = HERE/f'{name}_last.pt'

    def folded_ckpt(ep, set12, v):
        return dict(folded=True, layers=model.layers(), a_scale=model.scales(),
                    depth=ck['depth'], channels=ck['channels'], skip=ck['skip'], residual=False,
                    unshuffle=unshuffle, dilation=dil, maxout=maxout, sigma=sigma, epoch=ep,
                    set12_psnr=set12, val_psnr=v,
                    qat=dict(source=str(args.ckpt), epochs=args.epochs, lr=args.lr, patch=patch))

    if args.resume and last.exists():
        st = torch.load(last, map_location='cpu', weights_only=False)
        model.load_state_dict(st['state']); opt.load_state_dict(st['opt'])
        sched.load_state_dict(st['sched'])
        rng.bit_generator.state = st['np_rng']; torch.set_rng_state(st['torch_rng'])
        best_val, best_ep, curve, start_ep = st['best_val'], st['best_ep'], st['curve'], st['epoch']+1
        print(f'  resuming at epoch {start_ep}, best integer validation {best_val:.3f} dB at {best_ep}')
    elif best_ep == 0:
        torch.save(folded_ckpt(0, q_set12, q_val), HERE/f'{name}.pt')   # never worse than the start

    def write_json():
        (HERE/f'{name}_train.json').write_text(json.dumps(dict(
            name=name, args={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
            source=str(args.ckpt), layers=shapes, board_cycles_per_pixel=cpp,
            before=dict(float_val=f_val, float_set12=f_set12, int_val=q_val, int_set12=q_set12),
            best_val_epoch=best_ep, curve=curve), indent=2), encoding='utf-8')

    t0 = time.time()
    for ep in range(start_ep, args.epochs+1):
        clean = patches.sample(args.patches, rng)
        noisy = noisy_batch(clean, sigma, rng)
        order = rng.permutation(args.patches)
        tot = 0.0
        model.train()
        for i in range(0, args.patches, args.batch):
            idx = order[i:i+args.batch]
            x = torch.from_numpy(noisy[idx]); y = torch.from_numpy(clean[idx])
            loss = F.mse_loss(model(x), y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item()*len(idx)
        sched.step()
        v, t12 = evaluate(model, val), evaluate(model, tests)
        if v > best_val:
            best_val, best_ep = v, ep
            torch.save(folded_ckpt(ep, t12, v), HERE/f'{name}.pt')
        curve.append(dict(epoch=ep, loss=tot/args.patches, val_psnr=v, set12_psnr=t12,
                          lr=opt.param_groups[0]['lr'], seconds=round(time.time()-t0, 1)))
        torch.save(dict(state=model.state_dict(), opt=opt.state_dict(), sched=sched.state_dict(),
                        np_rng=rng.bit_generator.state, torch_rng=torch.get_rng_state(),
                        epoch=ep, best_val=best_val, best_ep=best_ep, curve=curve), last)
        write_json()
        print(f'epoch {ep:>3}/{args.epochs}  loss {tot/args.patches:.6f}  integer val {v:.3f} dB '
              f'(best {best_val:.3f} @ {best_ep})  Set12 {t12:.2f} dB (test, not used)  '
              f'{time.time()-t0:6.0f}s', flush=True)
    write_json()
    print(f'wrote {HERE/(name + ".pt")}: integer validation {q_val:.3f} -> {best_val:.3f} dB '
          f'(float was {f_val:.3f})')


if __name__ == '__main__':
    main()
