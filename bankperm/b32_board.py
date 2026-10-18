"""B-32 ReLU + QAT s1 at W=4 on Set12 05.png: Original, Frozen and Multi-start layouts.

    python bankperm/b32_board.py [--frozen ZIP] [--multi ZIP]     # writes bankperm/b32_board.json

GPT's bank-permutation work exported two relabellings of
denoise/export/dn_d10_c32_us_fx_qat, the Frozen and the Multi-start layouts
(research/q1_codesign/artifacts/*.zip, the defaults), and ran all three on
the W=4 board on Set12 05.png (sigma 25, test_noise seed 0). This script reads
each ZIP's export folder with zipfile into a temporary directory and rebuilds
every layer's windows of that image for each layout with the board driver's
host emulation (scripts/run_denoise.py). Per layer and in total it gives:

  count       the per-window count at W = 1, 2, 4 (denoise/predict_w4.window_cycles,
              sparse mode), fill and drain left out
  exact_w4    the W=4 board cycles it predicts: the count plus the fill and
              drain of denoise/w4_gaps.py, min(load, last) + 3 + ((COUT-1) % 16 + 1)
              on every layer after the first (load and last of the layout's own
              last window); the first layer gets the gap that w4_gaps.json
              records for this network's conv1 on the board (17), a measured
              constant, not derived (conv1 reads the image, so its windows are
              the same in all three layouts; checked here)
  mechanism   the mean over windows of the largest bank's nonzero taps, and the
              share of windows whose W=4 compute, ceil(COUT/16) * max(1, max bank),
              is at most the load ceil(K/4) + 1 ('floor-bound')
  bounds      two lower bounds on the W=4 count (see BOUNDS below)

Then it compares exact_w4 with the board numbers of bankperm/board_transcribed.json
(GPT's markdown; the raw report.json files are not in the repository) after
checking that every transcribed value is on the line it cites, and with the
earlier W=4 run committed in denoise/w4_measured.json. Board cycles include
IN_STALL (the core waiting for the DMA), so each comparison takes the reported
IN_STALL off first. Original layers are in sample for the fill-and-drain rule,
Frozen and Multi-start layers out of sample, conv1 is not a prediction (STATUS).
"""
import argparse
import contextlib
import hashlib
import io
import json
import math
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from common import QMAX_A, load_set, test_noise  # noqa: E402
from predict_w4 import P, T, window_cycles  # noqa: E402
from w4_gaps import load_and_last  # noqa: E402

MODEL = 'dn_d10_c32_us_fx_qat'
ORIGINAL = ROOT/'denoise'/'export'/MODEL
ART = ROOT/'research'/'q1_codesign'/'artifacts'
ZIPS = {'frozen': ART/'q1_bank_reordered_export_20261018.zip',
        'multistart': ART/'q1_multistart_verified_export_20261018.zip'}
LAYOUTS = ('original', 'frozen', 'multistart')
WIDTHS = (1, 2, 4)
IMAGE = '05.png'
BOUNDS = {
    'perfect_balance': ('per-window perfect balance: every window\'s nonzero taps spread as evenly as possible over '
                        'the 4 banks, i.e. max bank = ceil(nnz/4), window = max(ceil(K/4)+1, ceil(COUT/16)*max(1, '
                        'ceil(nnz/4)), COUT). The only capacity limit is a bank\'s ceil(K/4) taps (72 on the hidden '
                        'layers), never binding since ceil(nnz/4) <= ceil(K/4). Each window is balanced on its own, '
                        'so no static channel-to-bank layout can count less (its max bank is >= ceil(nnz/4) on '
                        'every window); a layout cannot in general reach it'),
    'floor': ('load/COUT floor: window = max(ceil(K/4)+1, COUT), the count if no window were bound by its compute; '
              'no layout or balancing of any kind can count less on this port'),
}
STATUS = {
    'not a prediction': ('conv1: its fill and drain is the measured constant of w4_gaps.json (this network\'s conv1 '
                         'on the board), and its windows are the image\'s, the same in every layout'),
    'in sample': ('Original conv2-conv10: the fill-and-drain constants (c = 3 + the channels of the last 16-lane '
                  'group) were read off board gaps that include this network\'s earlier W=4 run of the Original '
                  '(denoise/w4_gaps.py), so agreement is consistency, not prediction'),
    'out of sample': ('Frozen and Multi-start conv2-conv10: the rule, with the same constants (c = 19 on hidden '
                      'layers, COUT + 3 on the last), was committed in 6dc0e60 (2026-10-17 13:15 UTC), before the '
                      'permuted exports (c2ad6ad, 45b4f16) and their board run; the min(load, last) term is computed '
                      'from the layout\'s own last window'),
}


def rel(p):
    """p relative to the repository, or its bare name if it is outside."""
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


def unzip_export(zpath, dest):
    """The MODEL/ folder of a GPT export ZIP, extracted flat under dest; nothing else is written."""
    out = Path(dest)/MODEL
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            parts = m.filename.split('/')
            if m.is_dir() or len(parts) != 2 or parts[0] != MODEL or parts[1] in ('', '.', '..') or '\\' in parts[1]:
                continue
            (out/parts[1]).write_bytes(z.read(m))
    return out


def layouts(zips, tmp):
    """{layout: (source, export dir)}: the Original in the tree and the ZIPs extracted under tmp."""
    out = {'original': (ORIGINAL, ORIGINAL)}
    for name, z in zips.items():
        out[name] = (Path(z), unzip_export(z, Path(tmp)/name))
    return out


def emulate(man, layers, q_in, per_layer):
    """Denoise q_in with the board driver's host emulation; per_layer(L, x) sees every layer's windows."""
    real = run_denoise.run_layer

    def capture(L, x, args, tag):
        per_layer(L, x)
        return real(L, x, args, tag)

    run_denoise.run_layer = capture
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out, _ = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'b32')
    finally:
        run_denoise.run_layer = real
    return out


def noisy_input(set_name, image, sigma):
    """The 7-bit noisy image the board runs were given (test_noise seed 0, as int_eval)."""
    name, clean, noisy = next(t for t in test_noise(load_set(set_name), sigma, seed=0) if t[0] == image)
    return np.rint(noisy*QMAX_A).astype(np.uint8)


def counts(x, k, cout):
    """{w1, w2, w4}: the summed per-window count of one layer's windows."""
    return {f'w{w}': int(window_cycles(x, k, cout, w).sum()) for w in WIDTHS}


def max_bank(x):
    """Per window, the most nonzero taps in one bank (tap t in bank t % T)."""
    return np.stack([(x[:, b::T] != 0).sum(1) for b in range(T)], 1).max(1)


def layer_record(i, L, x, conv1_gap):
    k, cout = L['K'], L['COUT']
    groups, load = math.ceil(cout/P), math.ceil(k/4) + 1
    mb = max_bank(x)
    nnz = (x != 0).sum(1)
    rec = dict(name=L['name'], K=k, COUT=cout, windows=int(x.shape[0]), nonzeros=int(nnz.sum()),
               count=counts(x, k, cout))
    if i == 0:
        rec['fill_drain_w4'] = conv1_gap
    else:
        ld, last = load_and_last(x[-1], k, cout, 4)
        rec['last_window'] = dict(load=ld, compute=last)
        rec['fill_drain_w4'] = min(ld, last) + 3 + (cout - 1) % P + 1
    rec['exact_w4'] = rec['count']['w4'] + rec['fill_drain_w4']
    rec['mean_max_bank'] = round(float(mb.mean()), 6)
    rec['floor_bound_share'] = round(float((groups*np.maximum(mb, 1) <= load).mean()), 6)
    rec['at_floor_share'] = round(float((groups*np.maximum(mb, 1) <= max(load, cout)).mean()), 6)
    rec['perfect_balance_w4'] = int(np.maximum(np.maximum(load, groups*np.maximum(-(-nnz//T), 1)), cout).sum())
    rec['floor_w4'] = int(x.shape[0])*max(load, cout)
    return rec


def pct(a, b):
    """Saving of b against a, in percent."""
    return round(100*(a - b)/a, 6)


def check_transcription(node, found, cache):
    """Every [file, line, quote] in node is on that line; every integer >= 1000 of an entry is in one of its quotes."""
    if isinstance(node, list):
        for v in node:
            check_transcription(v, found, cache)
        return
    if not isinstance(node, dict):
        return
    quotes = []
    for f, line, quote in node.get('src', []):
        if f not in cache:
            cache[f] = (ROOT/f).read_text(encoding='utf-8').splitlines()
        ok = quote in cache[f][line-1]
        found['sources'] += 1
        if not ok:
            found['missing'].append(f'{f}:{line} {quote!r}')
        quotes.append(quote)
    for key, v in node.items():
        if key == 'src':
            continue
        if isinstance(v, int) and not isinstance(v, bool) and v >= 1000 and node.get('src'):
            found['values'] += 1
            if not any(f'{v:,}' in q or str(v) in q for q in quotes):
                found['missing'].append(f'{key}={v} not in the quotes of its entry')
        check_transcription(v, found, cache)


def compare(board, predicted, status, in_stall=0):
    return dict(board=board, in_stall=in_stall, predicted=predicted,
                board_minus_in_stall_minus_predicted=board - in_stall - predicted, status=status)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--frozen', type=Path, default=ZIPS['frozen'], help='Frozen export ZIP')
    ap.add_argument('--multi', type=Path, default=ZIPS['multistart'], help='Multi-start export ZIP')
    ap.add_argument('--board', type=Path, default=HERE/'board_transcribed.json')
    ap.add_argument('--out', type=Path, default=HERE/'b32_board.json')
    args = ap.parse_args()
    t0 = time.time()

    gaps = json.loads((ROOT/'denoise'/'w4_gaps.json').read_text())
    net = next(v for v in gaps['networks'].values() if v['model'] == MODEL)
    g1 = net['layers'][0]['board_w4']
    conv1_gap = g1['gap'] - g1['in_stall']

    res = dict(model=MODEL, image=f'Set12 {IMAGE}', noise='sigma 25 (the manifest\'s), test_noise seed 0',
               core=f'P = {P} lanes, T = {T} banks, tap t in bank t % 4, sparse mode',
               count_rule='window = max(ceil(K/W)+1, ceil(COUT/16)*max(1, max_b nnz_b), COUT) (denoise/predict_w4.py)',
               fill_drain_rule=('exact_w4 = count_w4 + min(load, last) + 3 + ((COUT-1) % 16 + 1) on conv2-conv10 '
                                '(denoise/w4_gaps.py); conv1 + the measured constant '
                                f'{conv1_gap} (denoise/w4_gaps.json, this network\'s conv1 board_w4 gap - in_stall)'),
               bounds=BOUNDS, status=STATUS, sources={}, layouts={})
    with tempfile.TemporaryDirectory() as tmp:
        lay = layouts({'frozen': args.frozen, 'multistart': args.multi}, tmp)
        windows, outputs = {}, {}
        for name in LAYOUTS:
            src, export = lay[name]
            man, layers = run_denoise.load_layers(export)
            info = dict(path=rel(src))
            if src.suffix == '.zip':
                info['zip_sha256'] = hashlib.sha256(src.read_bytes()).hexdigest()
                info['permuted_outputs'] = sorted(json.loads((export/'permutation_manifest.json').read_text())['orders'],
                                                  key=lambda c: int(c[4:]))
            res['sources'][name] = info
            q_in = noisy_input('Set12', IMAGE, man['sigma'])
            got = []
            outputs[name] = emulate(man, layers, q_in, lambda L, x: got.append((L, x)))
            windows[name] = got
            rows = [layer_record(i, L, x, conv1_gap) for i, (L, x) in enumerate(got)]
            res['layouts'][name] = dict(layers=rows)
            print(f'{name:<11} emulated', flush=True)

        conv1 = windows['original'][0][1]
        res['checks'] = dict(
            conv1_windows_identical={n: bool(np.array_equal(windows[n][0][1], conv1)) for n in LAYOUTS[1:]},
            denoised_identical={n: bool(np.array_equal(outputs[n], outputs['original'])) for n in LAYOUTS[1:]},
            nonzeros_per_layer_equal={n: all(a['nonzeros'] == b['nonzeros'] for a, b in zip(
                res['layouts'][n]['layers'], res['layouts']['original']['layers'])) for n in LAYOUTS[1:]})
    del windows

    # Totals, savings, mechanism, bounds
    for name in LAYOUTS:
        rows = res['layouts'][name]['layers']
        tot = dict(count={f'w{w}': sum(r['count'][f'w{w}'] for r in rows) for w in WIDTHS},
                   fill_drain_w4=sum(r['fill_drain_w4'] for r in rows), exact_w4=sum(r['exact_w4'] for r in rows),
                   perfect_balance_w4=sum(r['perfect_balance_w4'] for r in rows),
                   floor_w4=sum(r['floor_w4'] for r in rows))
        tot['conv2_9'] = dict(count_w4=sum(r['count']['w4'] for r in rows[1:9]),
                              exact_w4=sum(r['exact_w4'] for r in rows[1:9]))
        res['layouts'][name]['total'] = tot
    o = res['layouts']['original']
    ob = o['total']
    res['savings_pct'] = {}
    for name in LAYOUTS[1:]:
        t = res['layouts'][name]['total']
        res['savings_pct'][name] = dict(
            count={f'w{w}': pct(ob['count'][f'w{w}'], t['count'][f'w{w}']) for w in WIDTHS},
            exact_w4=pct(ob['exact_w4'], t['exact_w4']),
            conv2_9_count_w4=pct(ob['conv2_9']['count_w4'], t['conv2_9']['count_w4']),
            per_layer_count_w4={a['name']: pct(a['count']['w4'], b['count']['w4'])
                                for a, b in zip(o['layers'], res['layouts'][name]['layers'])})
    res['mechanism'] = dict(
        what=('per layer: mean_max_bank = mean over windows of the largest bank\'s nonzero taps; floor_bound_share = '
              'share of windows whose W=4 compute ceil(COUT/16)*max(1, max bank) <= the load ceil(K/4)+1; '
              'at_floor_share = the same against max(load, COUT), the window\'s floor (differs only on conv1, whose '
              'floor is COUT = 32 > load = 10)'),
        layers={r['name']: {n: {k: res['layouts'][n]['layers'][i][k]
                                for k in ('mean_max_bank', 'floor_bound_share', 'at_floor_share')}
                            for n in LAYOUTS}
                for i, r in enumerate(o['layers'])})
    head = dict(what=('W=4 count of the bounds against the Original\'s count (fill and drain left out); the '
                      'bounds depend only on each window\'s nonzero count, the same in every layout (checked)'),
                original_count_w4=ob['count']['w4'])
    for b in ('perfect_balance', 'floor'):
        vals = {n: res['layouts'][n]['total'][f'{b}_w4'] for n in LAYOUTS}
        head[b] = dict(count_w4=vals['original'], same_in_every_layout=len(set(vals.values())) == 1,
                       saving_pct=pct(ob['count']['w4'], vals['original']),
                       per_layer={r['name']: r[f'{b}_w4'] for r in o['layers']})
    gain = ob['count']['w4'] - head['perfect_balance']['count_w4']
    head['share_of_perfect_balance_saving'] = {
        n: round((ob['count']['w4'] - res['layouts'][n]['total']['count']['w4'])/gain, 6) for n in LAYOUTS[1:]}
    res['headroom_w4'] = head

    # Board
    board = json.loads(args.board.read_text(encoding='utf-8'))
    found = dict(sources=0, values=0, missing=[])
    check_transcription(board, found, {})
    res['transcription_check'] = dict(file=rel(args.board), status=board['status'], sources_checked=found['sources'],
                                      integers_checked=found['values'], all_found=not found['missing'],
                                      missing=found['missing'])
    pred = {n: [r['exact_w4'] for r in res['layouts'][n]['layers']] for n in LAYOUTS}

    def st(i, n):
        return 'not a prediction' if i == 0 else 'in sample' if n == 'original' else 'out of sample'

    cmp = {}
    can = board['original_canary']
    cmp['original_canary_layers'] = [dict(name=b['name'], **compare(b['cycles'], pred['original'][i], st(i, 'original'),
                                                                   b['in_stall']))
                                     for i, b in enumerate(can['layers'])]
    cmp['original_canary_total'] = compare(can['total']['cycles'], ob['exact_w4'], 'in sample', can['total']['in_stall'])
    tri = board['triplet_rep1_layers']['layers']
    for n in ('original', 'multistart'):
        cmp[f'{n}_rep1_layers'] = [dict(name=b['name'], **compare(b[n], pred[n][i], st(i, n))) for i, b in enumerate(tri)]
    reps = []
    for r in board['triplet_repeats']:
        row = dict(rep=r['rep'])
        for n in LAYOUTS:
            t = res['layouts'][n]['total']
            s = r['in_stall'][n]
            row[n] = dict(total=compare(r[n], t['exact_w4'], 'in sample' if n == 'original' else 'out of sample', s),
                          conv2_9=compare(r['conv2_9'][n], t['conv2_9']['exact_w4'],
                                          'in sample' if n == 'original' else 'out of sample'))
        # Frozen's conv1 + conv10 from the two totals (the stall of repeat 3 is on conv10)
        c110 = r['frozen'] - r['conv2_9']['frozen']
        row['frozen']['conv1_plus_conv10_derived'] = compare(c110, pred['frozen'][0] + pred['frozen'][9],
                                                             'conv1 not a prediction; conv10 out of sample',
                                                             r['in_stall']['frozen'])
        reps.append(row)
    cmp['repeats'] = reps
    meas = json.loads((ROOT/'denoise'/'w4_measured.json').read_text())
    m = next(v for v in meas['networks'].values() if v['model'] == MODEL)
    cmp['earlier_committed_run'] = dict(
        source='denoise/w4_measured.json',
        total=compare(m['measured_total'], ob['exact_w4'], 'in sample', m['in_stall']),
        layers=[dict(name=L['name'], **compare(L['measured'], pred['original'][i], st(i, 'original'), L['in_stall']))
                for i, L in enumerate(m['layers'])],
        matches_transcribed=(m['measured_total'] == board['earlier_committed_run']['total'] == can['total']['earlier']
                             and m['in_stall'] == board['earlier_committed_run']['in_stall']
                             and [L['measured'] for L in m['layers']] == [b['earlier'] for b in can['layers']]))
    r1 = board['triplet_repeats'][0]
    cmp['savings_rep1'] = {
        n: dict(board=r1['original'] - r1[n], predicted_exact=ob['exact_w4'] - res['layouts'][n]['total']['exact_w4'],
                count_only=ob['count']['w4'] - res['layouts'][n]['total']['count']['w4'],
                fill_drain_difference=ob['fill_drain_w4'] - res['layouts'][n]['total']['fill_drain_w4'],
                board_pct=pct(r1['original'], r1[n]))
        for n in LAYOUTS[1:]}

    def diffs(rows):
        return [x['board_minus_in_stall_minus_predicted'] for x in rows]
    every = (diffs(cmp['original_canary_layers']) + diffs(cmp['original_rep1_layers'])
             + diffs(cmp['multistart_rep1_layers']) + diffs(cmp['earlier_committed_run']['layers'])
             + [cmp['original_canary_total']['board_minus_in_stall_minus_predicted'],
                cmp['earlier_committed_run']['total']['board_minus_in_stall_minus_predicted']]
             + [row[n][k]['board_minus_in_stall_minus_predicted'] for row in reps for n in LAYOUTS
                for k in row[n]])
    out_of_sample = (diffs(cmp['multistart_rep1_layers'][1:])
                     + [row[n][k]['board_minus_in_stall_minus_predicted'] for row in reps
                        for n in ('frozen', 'multistart') for k in ('total', 'conv2_9')])
    cmp['summary'] = dict(comparisons=len(every), exact=sum(d == 0 for d in every),
                          out_of_sample_comparisons=len(out_of_sample),
                          out_of_sample_exact=sum(d == 0 for d in out_of_sample),
                          largest_abs_difference=max(abs(d) for d in every))
    res['board_vs_prediction'] = cmp

    args.out.write_text(json.dumps(res, indent=1) + '\n')
    for n in LAYOUTS:
        t = res['layouts'][n]['total']
        print(f'{n:<11} count W1 {t["count"]["w1"]:>11,} W2 {t["count"]["w2"]:>11,} W4 {t["count"]["w4"]:>11,}'
              f'   exact W4 {t["exact_w4"]:>11,} (fill/drain {t["fill_drain_w4"]})')
    for n in LAYOUTS[1:]:
        s = res['savings_pct'][n]
        print(f'{n:<11} saving W1 {s["count"]["w1"]:.4f}%  W2 {s["count"]["w2"]:.4f}%  W4 {s["count"]["w4"]:.4f}%  '
              f'exact W4 {s["exact_w4"]:.4f}%  share of perfect-balance saving '
              f'{head["share_of_perfect_balance_saving"][n]:.4f}')
    print(f'bounds: perfect balance {head["perfect_balance"]["count_w4"]:,} ({head["perfect_balance"]["saving_pct"]:.4f}%)'
          f'  floor {head["floor"]["count_w4"]:,} ({head["floor"]["saving_pct"]:.4f}%)')
    print('checks', res['checks'])
    print('transcription:', found['sources'], 'sources,', found['values'], 'integers, missing', found['missing'])
    print('board vs exact prediction:', cmp['summary'])
    print(f'wrote {rel(args.out)} in {time.time()-t0:.0f} s')


if __name__ == '__main__':
    main()
