"""Core cycles with a skewed tap layout, against the conventional one (a count, not a measurement).

    python bankperm/skew_count.py                    # writes bankperm/skew_count.json
    python bankperm/skew_count.py --jobs 2

The host builds every window (scripts/run_cifar.im2col, order (ky, kx, channel))
and sends the layer's weights with it, so the same permutation of the K tap
positions, applied to the windows and to the weight columns, leaves every
accumulator unchanged (X' W'^T = X P P^T W^T = X W^T; with 7-bit activations and
INT8 weights a partial sum stays below K * 127 * 128 < 2^31 in any order, so the
INT32 result does not depend on the order). Conventionally tap t = s*C + p (s the
3x3 position, p the channel) is in bank t % 4, which for C % 4 == 0 is p % 4: all
nine taps of a channel share a bank. The skewed layout puts channel p of
position s in slot s*C + (p + s) % C, so its bank is (p + s) % 4 and each
channel's nine taps fall 3/2/2/2 over the banks. For C % 4 == 1 (the 45-channel
network) the conventional layout already has bank (s + p) % 4, so the skewed
layout is the conventional one there. As in bankperm/PROTOCOL.md, only the
inputs of conv2 to conv(L-1) are changed (the last layer has COUT <= 16 and can
never pay, bankperm/bounds.py).

Counted per window as in denoise/count_test_sets.py (sparse mode; fill and
drain left out): window = max(feed + 1, ceil(COUT/16) * max(1, m), COUT), feed =
ceil(K/w) for w = 1, 2, 4 values per cycle, C_in for on-chip line buffers.

What is counted (Set12 + BSD68, sigma 25, test_noise seed 0, host emulation):
  - B-32 ReLU + QAT s1 (the board network of the permutation study) on all 80
    images, so that its skew can be set beside the Frozen and Multi-start
    layouts of b32_testsets.json;
  - the four other networks of the IWEICT paper's comparisons (A, B, B-32 maxout
    s1, 10 x 45) on Set12 05.png, the board image, for the ratios that paper
    reports.
Nothing here was run on the board.
"""
import argparse
import concurrent.futures
import contextlib
import io
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, test_noise  # noqa: E402
from predict_w4 import P, T  # noqa: E402

STRUCTS = ('w1', 'w2', 'w4', 'line_buffer')
BOARD_NET = ('B-32 ReLU + QAT s1', 'dn_d10_c32_us_fx_qat')
OTHERS = {'A': 'dn_d7_c32_es', 'B + QAT': 'dn_d10_c64_us_es_qat',
          'B-32 maxout + QAT s1': 'dn_d10_c32_us_mo_fx_qat', '10 x 45 ReLU + QAT': 'dn_d10_c45_us_fx_qat'}


def skew_order(k, c):
    """new[slot] = old tap index: channel p of position s goes to slot s*c + (p + s) % c."""
    new = np.empty(k, dtype=np.int64)
    for s in range(k // c):
        for p in range(c):
            new[s*c + (p + s) % c] = s*c + p
    return new


def feed(struct, L):
    return L['K'] // (L['kh']*L['kw']) if struct == 'line_buffer' else math.ceil(L['K']/int(struct[1:]))


def counts(L, x):
    k, cout = L['K'], L['COUT']
    m = np.stack([(x[:, b::T] != 0).sum(1) for b in range(T)], 1).max(1)
    issue = math.ceil(cout/P)*np.maximum(m, 1)
    return {s: int(np.maximum(np.maximum(feed(s, L) + 1, issue), cout).sum()) for s in STRUCTS}


def run(label, model, set_name, only):
    man, layers = run_denoise.load_layers(ROOT/'denoise'/'export'/model)
    n = len(layers)
    out = {}
    real = run_denoise.run_layer
    for name, clean, noisy in test_noise(load_set(set_name), man['sigma'], seed=0):
        if only and name not in only:
            continue
        tot = {'conventional': dict.fromkeys(STRUCTS, 0), 'skewed': dict.fromkeys(STRUCTS, 0)}
        changed = []

        def capture(L, x, args, tag):
            i = len(changed)
            c = L['K'] // (L['kh']*L['kw'])
            skew = 0 < i < n-1 and len(L['inputs']) == 1 and c % 4 == 0
            changed.append(skew)
            xs = x[:, skew_order(L['K'], c)] if skew else x
            for key, xx in (('conventional', x), ('skewed', xs)):
                for s, v in counts(L, xx).items():
                    tot[key][s] += v
            return real(L, x, args, tag)

        run_denoise.run_layer = capture
        try:
            q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
            with contextlib.redirect_stdout(io.StringIO()):
                run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'skew')
        finally:
            run_denoise.run_layer = real
        out[name] = dict(pixels=int(clean.size), layers_skewed=int(sum(changed)), **tot)
    return label, model, set_name, out


def check_exact(model):
    """Accumulators of every layer of 05.png with the skewed order on both sides equal the conventional ones."""
    sys.path.insert(0, str(ROOT/'scripts'))
    from run_cifar import oracle
    man, layers = run_denoise.load_layers(ROOT/'denoise'/'export'/model)
    real = run_denoise.run_layer
    bad = []

    def capture(L, x, args, tag):
        c = L['K'] // (L['kh']*L['kw'])
        o = skew_order(L['K'], c)
        idx = np.linspace(0, x.shape[0]-1, 4096).astype(int)
        if not np.array_equal(oracle(x[idx], L['wq'], L['bq']), oracle(x[idx][:, o], L['wq'][:, o], L['bq'])):
            bad.append(L['name'])
        return real(L, x, args, tag)

    run_denoise.run_layer = capture
    try:
        name, clean, noisy = next(t for t in test_noise(load_set('Set12'), man['sigma'], seed=0) if t[0] == '05.png')
        with contextlib.redirect_stdout(io.StringIO()):
            run_denoise.denoise(np.rint(noisy*QMAX_A).astype(np.uint8), man, layers,
                                SimpleNamespace(emulate=True, out=None), 'skew')
    finally:
        run_denoise.run_layer = real
    return bad


def saving(a, b):
    return 100*(a - b)/a


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--out', type=Path, default=HERE/'skew_count.json')
    args = ap.parse_args()
    jobs = [(*BOARD_NET, s, None) for s in ('Set12', 'BSD68')]
    jobs += [(label, model, 'Set12', {'05.png'}) for label, model in OTHERS.items()]
    res = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(run, *j) for j in jobs]):
            label, model, set_name, per = fut.result()
            res.setdefault(label, dict(model=model, images={}))['images'].update(
                {f'{set_name} {k}': v for k, v in per.items()})
            print(f'{label:<24}{set_name:<6}{len(per):3d} images', flush=True)
    exact = check_exact(BOARD_NET[1])
    b32 = res[BOARD_NET[0]]['images']
    sav = {s: [saving(v['conventional'][s], v['skewed'][s]) for k, v in b32.items() if k != 'Set12 01.png']
           for s in STRUCTS}
    summary = {s: dict(min=min(v), median=float(np.median(v)), max=max(v),
                       pooled=saving(sum(b32[k]['conventional'][s] for k in b32 if k != 'Set12 01.png'),
                                     sum(b32[k]['skewed'][s] for k in b32 if k != 'Set12 01.png')))
               for s, v in sav.items()}
    b05 = {label: r['images']['Set12 05.png'] for label, r in res.items()}
    ratio = lambda a, b, lay, s: b05[a][lay][s]/b05[b][lay][s]  # noqa: E731 (same image: totals are per pixel x pixels)
    pairs = {'B/A': ('B + QAT', 'A'), 'maxout/ReLU': ('B-32 maxout + QAT s1', BOARD_NET[0]),
             '45-channel/maxout': ('10 x 45 ReLU + QAT', 'B-32 maxout + QAT s1')}
    ratios = {n: {s: dict(conventional=ratio(a, b, 'conventional', s), skewed=ratio(a, b, 'skewed', s))
                  for s in STRUCTS} for n, (a, b) in pairs.items()}
    for n, r in ratios.items():
        for s, v in r.items():
            v['same_side_of_1'] = (v['conventional'] > 1) == (v['skewed'] > 1)
            v['change_percent'] = 100*(v['skewed'] - v['conventional'])/v['conventional']
    out = dict(what='count, not a board measurement: conventional tap layout (bank t % 4) against the skewed '
                    'layout (bank (p + s) % 4); inputs of conv2..conv(L-1) only; fill and drain left out',
               noise='sigma 25, test_noise seed 0', exactness=dict(
                   argument='same permutation of window taps and weight columns; |partial sum| <= K*127*128 < 2^31',
                   checked=f'{BOARD_NET[1]} 05.png, 4096 windows per layer, integer oracle',
                   layers_differing=exact),
               board_network=dict(label=BOARD_NET[0], model=BOARD_NET[1],
                                  saving_percent_79_images_other_than_01=summary),
               ratios_05png=ratios, networks=res)
    args.out.write_text(json.dumps(out, indent=1)+'\n')
    for s, v in summary.items():
        print(f'{BOARD_NET[0]} {s:<12} skew saving over 79 images: {v["min"]:.2f}..{v["max"]:.2f}% '
              f'(median {v["median"]:.2f}, pooled {v["pooled"]:.2f})')
    for n, r in ratios.items():
        print(f'{n:<18}' + '  '.join(f'{s} {v["conventional"]:.3f}->{v["skewed"]:.3f}' for s, v in r.items()))
    print('exactness check, layers differing:', exact or 'none')
    print('wrote', args.out)


if __name__ == '__main__':
    main()
