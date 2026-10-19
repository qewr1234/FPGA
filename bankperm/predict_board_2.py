"""Exact W=4 board cycles of the PROTOCOL_2 board runs, written before they run.

    python bankperm/predict_board_2.py [--jobs 2]     # writes bankperm/board_prediction_2.json
    python bankperm/export_layout.py --layout skew --model dn_d10_c32_us_fx_qat --out DIR
    python bankperm/predict_board_2.py --jobs 2 --skew-export DIR   # also checks the driver's skew path

bankperm/PROTOCOL_2.md ('Board runs', committed in 951c8f1) fixes the next board
runs: the existing W=4 bitstream (core ID 0x4d410303; run_denoise.py --w4 --mode 1
--fclk 50), B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat), layouts Original (L0),
Frozen, Multi-start and Skew (L2), images Set12 05.png, 06.png, 07.png, 08.png
(sigma 25, test_noise seed 0). Before the runs, every run's exact per-layer
cycles are committed here; a layer is predicted if its CYCLES - IN_STALL equals
the prediction exactly.

Per layer the windows are those of the board driver's host emulation
(scripts/run_denoise.py denoise, --emulate): the Original export in the tree, the
Frozen and Multi-start exports read from their ZIPs with zipfile into a
temporary directory (bankperm/b32_board.py unzip_export), and the Skew the
Original's windows of conv2..conv9 with their taps in bankperm/skew_count.py's
skew_order (channel p of position s in slot s*32 + (p + s) % 32, so in bank
(s + p) % 4; conv1 reads the image and conv10 is the last layer, both unchanged,
as in PROTOCOL_2 L2). The prediction of a layer is

    count      sum over its windows of denoise/predict_w4.window_cycles at W=4,
               sparse mode: max(ceil(K/4) + 1, ceil(COUT/16) * max(1, max bank nnz), COUT)
    fill/drain conv2..conv10: min(load, last) + 3 + ((COUT-1) % 16 + 1)
               (denoise/w4_gaps.py), load = ceil(K/4) + 1 and last = the compute of
               the run's own last window (the layout's, skewed for the Skew);
               conv1: the measured constant of denoise/w4_gaps.json (this network's
               conv1 board_w4 gap - in_stall = 17), not derived; conv1's windows are
               the image's and identical in every layout (checked)
    predicted  count + fill/drain, per board run (one per layer here: every layer
               of these images has at most --tile = 65536 windows, run_denoise.py's
               default; with a smaller --tile each run pays its own fill/drain)

Validated before anything is written: on 05.png the Original, Frozen and
Multi-start totals must equal 13,289,030 / 12,355,814 / 12,278,419 (and every
layer bankperm/b32_board.json), and the Skew's count skew_count.json's W=4
skewed total 12,139,748; otherwise the script stops and writes nothing. It also
checks the counts of 06-08 against b32_testsets.json and skew_count.json, the
denoised images against each other and int_eval.json, and that the skewed taps
with the skewed weight columns give every accumulator of the Original (whole
layers, integer oracle). With --skew-export it also emulates that layout export
through run_denoise.py's own tap_order path and requires every layer's record
and config.bin digest to be the Skew's. The 05.png Original, Frozen and Multi-start runs were
measured before (bankperm/board_transcribed.json); 06-08 and the Skew have never
run on the board; the raw report of the 05.png Original W=4 run
(denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json) is compared layer by layer too.
"""
import argparse
import concurrent.futures
import contextlib
import datetime
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_denoise  # noqa: E402
from b32_board import MODEL, ORIGINAL, ZIPS, rel, unzip_export  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from predict_w4 import P, T, window_cycles  # noqa: E402
from run_cifar import oracle  # noqa: E402
from skew_count import skew_order  # noqa: E402
from w4_gaps import load_and_last  # noqa: E402

PROTOCOL = HERE/'PROTOCOL_2.md'
RAW_W4 = ROOT/'denoise'/'board_runs'/'dn_d10_c32_us_fx_qat_05_w4.json'   # the raw report of the earlier W=4 run
PROTOCOL_COMMIT = '951c8f1'
SET = 'Set12'
IMAGES = ('05.png', '06.png', '07.png', '08.png')
LAYOUTS = ('original', 'frozen', 'multistart', 'skew')
W = 4
TILE = 65536
VALIDATE = {'image': '05.png',
            'exact_total': {'original': 13289030, 'frozen': 12355814, 'multistart': 12278419},
            'skew_count_w4': 12139748}


def config_digest(L, order=None):
    """SHA-256 of the layer's config.bin, or of the one with its weight columns in `order`."""
    if order is None:
        return hashlib.sha256(Path(L['cfg']).read_bytes()).hexdigest()
    blob = np.concatenate([L['wq'][:, order].astype('<i4').ravel(), L['bq'].astype('<i4')])
    return hashlib.sha256(blob.tobytes()).hexdigest()


def rebuilt_config_matches(L):
    """The config format the skewed digest assumes: INT32 weights (COUT x K), then the bias."""
    blob = np.concatenate([L['wq'].astype('<i4').ravel(), L['bq'].astype('<i4')])
    return blob.tobytes() == Path(L['cfg']).read_bytes()


def runs_of(n, tile):
    return [(s, min(n, s + tile)) for s in range(0, n, tile)]


def layer_record(i, L, x, conv1_gap, tile):
    """The exact W=4 prediction of one layer whose core sees windows x (N, K)."""
    k, cout = L['K'], L['COUT']
    if k % W:
        raise SystemExit(f'{L["name"]}: K={k} is not a multiple of 4; the W=4 padding is not modelled here')
    per = window_cycles(x, k, cout, W)
    rec = dict(name=L['name'], K=k, COUT=cout, windows=int(x.shape[0]), nonzeros=int((x != 0).sum()),
               count_w4=int(per.sum()))
    runs = []
    for s, e in runs_of(x.shape[0], tile):
        load, last = load_and_last(x[e-1], k, cout, W)
        r = dict(windows=[s, e], last_window=dict(load=load, compute=last))
        r['fill_drain_w4'] = conv1_gap if i == 0 else min(load, last) + 3 + (cout - 1) % P + 1
        runs.append(r)
    rec['board_runs'] = len(runs)
    rec['last_window'] = runs[-1]['last_window']
    if len(runs) > 1:
        rec['runs'] = runs
    rec['fill_drain_w4'] = sum(r['fill_drain_w4'] for r in runs)
    rec['predicted'] = rec['count_w4'] + rec['fill_drain_w4']
    rec['status'] = ('conv1: count + the measured constant (not derived)' if i == 0
                     else 'count + the w4_gaps.py fill-and-drain rule')
    return rec


def emulate(export, image, conv1_gap, tile, with_skew):
    """Emulate one export on one image -> {layout: [layer records]}, conv1 windows, output, checks."""
    man, layers = run_denoise.load_layers(export)
    n = len(layers)
    name, clean, noisy = next(t for t in test_noise(load_set(SET), man['sigma'], seed=0) if t[0] == image)
    q_in = np.rint(noisy*QMAX_A).astype(np.uint8)          # as int_eval and run_denoise.py
    rows = {'layout': []}
    if with_skew:
        rows['skew'] = []
    keep = {}
    skew_info = []
    real = run_denoise.run_layer

    def capture(L, x, args, tag):
        i = len(rows['layout'])
        acc, info = real(L, x, args, tag)
        rec = layer_record(i, L, x, conv1_gap, tile)
        rec['config_sha256'] = config_digest(L)
        rows['layout'].append(rec)
        if i == 0:
            keep['conv1'] = x.copy()
        if with_skew:
            c = L['K'] // (L['kh']*L['kw'])
            skew = 0 < i < n-1 and len(L['inputs']) == 1 and c % 4 == 0
            if skew:
                o = skew_order(L['K'], c)
                xs = x[:, o]
                rs = layer_record(i, L, xs, conv1_gap, tile)
                rs['skewed'] = True
                rs['config_sha256'] = config_digest(L, o)
                skew_info.append(dict(name=L['name'], C=c,
                                      accumulators_identical=bool(np.array_equal(
                                          oracle(xs, L['wq'][:, o], L['bq']), acc)),
                                      config_format_rebuilt=rebuilt_config_matches(L),
                                      nonzeros_equal=rs['nonzeros'] == rec['nonzeros'],
                                      order_is_permutation=bool(np.array_equal(np.sort(o), np.arange(L['K'])))))
            else:
                rs = dict(rec, skewed=False)
            rows['skew'].append(rs)
        return acc, info

    run_denoise.run_layer = capture
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out, _ = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'pred2')
    finally:
        run_denoise.run_layer = real
    p = float(psnr(clean, out.astype(np.float32)/255))
    int_eval = json.loads((export/'int_eval.json').read_text())[SET]['per_image'][image]
    return dict(rows=rows, conv1=keep['conv1'], out=out, psnr=p, int_eval=int_eval, skew_info=skew_info,
                pixels=int(clean.size))


def strip(rec):
    """A layer record without what differs by construction (the weights' digest, the skew flag)."""
    return {k: v for k, v in rec.items() if k not in ('config_sha256', 'skewed')}


def total(rows):
    return dict(count_w4=sum(r['count_w4'] for r in rows), fill_drain_w4=sum(r['fill_drain_w4'] for r in rows),
                predicted=sum(r['predicted'] for r in rows),
                conv2_9=dict(count_w4=sum(r['count_w4'] for r in rows[1:9]),
                             predicted=sum(r['predicted'] for r in rows[1:9])))


def run_image(image, exports, conv1_gap, tile):
    """All four layouts of one image (the Skew from the Original's emulation)."""
    t0 = time.time()
    res, outs, conv1, chk = {}, {}, {}, {}
    for name in ('original', 'frozen', 'multistart'):
        e = emulate(exports[name], image, conv1_gap, tile, with_skew=name == 'original')
        res[name] = e['rows']['layout']
        if name == 'original':
            res['skew'] = e['rows']['skew']
            chk['skew_layers'] = e['skew_info']
            chk['pixels'] = e['pixels']
        outs[name], conv1[name] = e['out'], e['conv1']
        chk.setdefault('psnr_vs_int_eval', {})[name] = dict(
            psnr=e['psnr'], int_eval=e['int_eval'], agrees_1e5=abs(e['psnr'] - e['int_eval']) <= 1e-5)
    chk['conv1_windows_identical'] = {n: bool(np.array_equal(conv1[n], conv1['original']))
                                      for n in ('frozen', 'multistart')}
    chk['denoised_identical'] = {n: bool(np.array_equal(outs[n], outs['original'])) for n in ('frozen', 'multistart')}
    chk['nonzeros_per_layer_equal'] = {n: [a['nonzeros'] for a in res[n]] == [a['nonzeros'] for a in res['original']]
                                       for n in LAYOUTS[1:]}
    chk['conv1_prediction_identical'] = {n: strip(res[n][0]) == strip(res['original'][0]) for n in LAYOUTS[1:]}
    chk['skewed_layers'] = [r['name'] for r in res['skew'] if r['skewed']]
    if exports.get('skew_export') is not None:
        # The driver's own skew path: a layout export (tap_order in its manifest) through run_denoise.denoise.
        e = emulate(exports['skew_export'], image, conv1_gap, tile, with_skew=False)
        got = e['rows']['layout']
        chk['skew_export'] = dict(
            predictions_identical=[strip(a) for a in got] == [strip(b) for b in res['skew']],
            config_sha256_identical=[a['config_sha256'] for a in got] == [b['config_sha256'] for b in res['skew']],
            denoised_identical=bool(np.array_equal(e['out'], outs['original'])),
            psnr_agrees_1e5=abs(e['psnr'] - e['int_eval']) <= 1e-5,
            differing_layers=[a['name'] for a, b in zip(got, res['skew'])
                              if strip(a) != strip(b) or a['config_sha256'] != b['config_sha256']])
    return image, res, chk, round(time.time() - t0, 1)


def pct(a, b):
    return round(100*(a - b)/a, 6)


def protocol_record():
    text = PROTOCOL.read_bytes()
    rec = dict(file=rel(PROTOCOL), commit=PROTOCOL_COMMIT, sha256=hashlib.sha256(text).hexdigest(),
               section='Board runs (prospective)',
               test='a layer is predicted if CYCLES - IN_STALL equals its prediction exactly; every miss is listed')
    try:
        blob = subprocess.run(['git', '-C', str(ROOT), 'show', f'{PROTOCOL_COMMIT}:bankperm/PROTOCOL_2.md'],
                              capture_output=True, check=True).stdout
        rec['identical_to_commit'] = blob == text
    except (OSError, subprocess.CalledProcessError) as e:
        rec['identical_to_commit'] = None
        rec['git_error'] = str(e)
    return rec


def measured_before(board, pred05):
    """The 05.png board numbers of board_transcribed.json against this file's predictions."""
    def cmp(cycles, in_stall, predicted):
        return dict(cycles=cycles, in_stall=in_stall, predicted=predicted,
                    cycles_minus_in_stall_minus_predicted=cycles - in_stall - predicted)
    lay = {n: [r['predicted'] for r in pred05[n]] for n in LAYOUTS}
    tot = {n: total(pred05[n]) for n in LAYOUTS}
    out = dict(source='bankperm/board_transcribed.json', status=board['status'],
               core_id=board['core_id']['value'], fclk_mhz=board['fclk_mhz']['value'],
               note=('measured before PROTOCOL_2 (2026-10-18, GPT\'s runs): Original canary and 3 repeats, Frozen and '
                     'Multi-start 3 repeats each, all on Set12 05.png; per-layer numbers exist for the Original '
                     '(canary, repeat 1) and the Multi-start (repeat 1), not for the Frozen. 06.png, 07.png, 08.png '
                     'and the Skew have never run on the board.'))
    can = board['original_canary']
    out['original_canary_layers'] = [dict(name=b['name'], **cmp(b['cycles'], b['in_stall'], lay['original'][i]))
                                     for i, b in enumerate(can['layers'])]
    out['original_canary_total'] = cmp(can['total']['cycles'], can['total']['in_stall'], tot['original']['predicted'])
    tri = board['triplet_rep1_layers']['layers']
    for n in ('original', 'multistart'):
        out[f'{n}_rep1_layers'] = [dict(name=b['name'], **cmp(b[n], 0, lay[n][i])) for i, b in enumerate(tri)]
    out['repeats'] = [dict(rep=r['rep'], **{n: dict(total=cmp(r[n], r['in_stall'][n], tot[n]['predicted']),
                                                    conv2_9=cmp(r['conv2_9'][n], 0, tot[n]['conv2_9']['predicted']))
                                            for n in ('original', 'frozen', 'multistart')})
                      for r in board['triplet_repeats']]
    diffs = ([x['cycles_minus_in_stall_minus_predicted'] for k in ('original_canary_layers', 'original_rep1_layers',
                                                                   'multistart_rep1_layers') for x in out[k]]
             + [out['original_canary_total']['cycles_minus_in_stall_minus_predicted']]
             + [r[n][k]['cycles_minus_in_stall_minus_predicted'] for r in out['repeats']
                for n in ('original', 'frozen', 'multistart') for k in ('total', 'conv2_9')])
    out['summary'] = dict(comparisons=len(diffs), exact=sum(d == 0 for d in diffs),
                          largest_abs_difference=max(abs(d) for d in diffs))
    # The one raw (not transcribed) board report of these runs in the repository: the
    # 05.png Original on the W=4 bitstream (RUN_W4_DENOISE.cmd, scripts/run_denoise.py).
    raw = json.loads(RAW_W4.read_text(encoding='utf-8'))
    assert raw['model'] == MODEL and raw['emulated'] is False and raw['activations_per_cycle'] == 4, RAW_W4
    rim = raw['images'][0]
    assert rim['image'] == VALIDATE['image'] and [b['name'] for b in rim['layers']] == [r['name'] for r in pred05['original']]
    rows = [dict(name=b['name'], runs=b['runs'], out_stall=b['out_stall'], **cmp(b['cycles'], b['in_stall'], lay['original'][i]))
            for i, b in enumerate(rim['layers'])]
    rtot = cmp(rim['cycles'], sum(b['in_stall'] for b in rim['layers']), tot['original']['predicted'])
    rd = [x['cycles_minus_in_stall_minus_predicted'] for x in rows] + [rtot['cycles_minus_in_stall_minus_predicted']]
    out['raw_report_original'] = dict(
        source=rel(RAW_W4), sha256=hashlib.sha256(RAW_W4.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        note=('the raw report.json of the earlier W=4 board run of the 05.png Original (not transcribed); kept apart '
              'from "summary", which counts the board_transcribed.json comparisons only'),
        mode_seq=raw['mode_seq'], core_id=sorted({c for b in rim['layers'] for c in b['core_id']}),
        fclk_mhz=sorted({f for b in rim['layers'] for f in b['fclk_mhz']}), layers=rows, total=rtot,
        summary=dict(comparisons=len(rd), exact=sum(d == 0 for d in rd), largest_abs_difference=max(abs(d) for d in rd)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--frozen', type=Path, default=ZIPS['frozen'], help='Frozen export ZIP')
    ap.add_argument('--multi', type=Path, default=ZIPS['multistart'], help='Multi-start export ZIP')
    ap.add_argument('--skew-export', type=Path,
                    help='optional: a skew layout export (bankperm/export_layout.py --layout skew) to check that the '
                         'driver\'s own skew path sends exactly the predicted windows and weights')
    ap.add_argument('--tile', type=int, default=TILE, help='windows per board run, as run_denoise.py --tile')
    ap.add_argument('--jobs', type=int, default=1, help='processes for 06-08 (at most 2 here)')
    ap.add_argument('--out', type=Path, default=HERE/'board_prediction_2.json')
    args = ap.parse_args()
    t0 = time.time()

    gaps = json.loads((ROOT/'denoise'/'w4_gaps.json').read_text())
    net_label, net = next((k, v) for k, v in gaps['networks'].items() if v['model'] == MODEL)
    g1 = net['layers'][0]['board_w4']
    assert net['layers'][0]['name'] == 'conv1'
    conv1_gap = g1['gap'] - g1['in_stall']

    with tempfile.TemporaryDirectory() as tmp:
        exports = {'original': ORIGINAL, 'frozen': unzip_export(args.frozen, Path(tmp)/'frozen'),
                   'multistart': unzip_export(args.multi, Path(tmp)/'multistart'),
                   'skew_export': args.skew_export.resolve() if args.skew_export else None}
        sources = dict(
            original=dict(path=rel(ORIGINAL)),
            frozen=dict(path=rel(args.frozen), zip_sha256=hashlib.sha256(args.frozen.read_bytes()).hexdigest()),
            multistart=dict(path=rel(args.multi), zip_sha256=hashlib.sha256(args.multi.read_bytes()).hexdigest()),
            skew=dict(path=rel(ORIGINAL), how=('the Original export\'s windows, conv2..conv9 with their taps in '
                                               'bankperm/skew_count.py skew_order(288, 32): slot s*32 + (p + s) % 32 '
                                               'holds channel p of 3x3 position s (bank (s + p) % 4); conv1 and conv10 '
                                               'unchanged; the weight columns permuted the same way (their config.bin '
                                               'digest is given per layer)'),
                      order_288_32=[int(v) for v in skew_order(288, 32)],
                      order_meaning='order[slot] = the Original tap index sent in that slot (x_skew = x[:, order])'))
        if args.skew_export:
            sm = json.loads((args.skew_export/'manifest.json').read_text())
            lm = args.skew_export/'layout_manifest.json'
            want = [int(v) for v in skew_order(288, 32)]
            sources['skew']['driver_export_checked'] = dict(
                path=rel(args.skew_export), model=sm.get('model'),
                layout_manifest_sha256=hashlib.sha256(lm.read_bytes()).hexdigest() if lm.exists() else None,
                tap_order_layers=[L['name'] for L in sm['layers'] if 'tap_order' in L],
                tap_order_is_skew_order={L['name']: L['tap_order'] == want for L in sm['layers'] if 'tap_order' in L},
                how=('emulated with scripts/run_denoise.py denoise (its tap_order path) on every image; each layer\'s '
                     'record and config.bin digest must equal the Skew\'s (checks.<image>.skew_export)'))
            if sm.get('model') != MODEL:
                raise SystemExit(f'--skew-export is a {sm.get("model")} export, not {MODEL}')
        else:
            sources['skew']['driver_export_checked'] = None
        for n in ('frozen', 'multistart'):
            sources[n]['permuted_outputs'] = sorted(json.loads(
                (exports[n]/'permutation_manifest.json').read_text())['orders'], key=lambda c: int(c[4:]))

        # Validate on 05.png first; stop before anything is written if it fails.
        image, r05, c05, sec = run_image(VALIDATE['image'], exports, conv1_gap, args.tile)
        print(f'{image} emulated in {sec} s', flush=True)
        b32 = json.loads((HERE/'b32_board.json').read_text())
        sk = json.loads((HERE/'skew_count.json').read_text())
        sk_img = sk['networks']['B-32 ReLU + QAT s1']['images']
        assert sk['networks']['B-32 ReLU + QAT s1']['model'] == MODEL and b32['model'] == MODEL
        val = {}
        for n, want in VALIDATE['exact_total'].items():
            got = total(r05[n])['predicted']
            per = [r['predicted'] for r in r05[n]]
            want_layers = [r['exact_w4'] for r in b32['layouts'][n]['layers']]
            val[f'{n}_total'] = dict(predicted=got, required=want, equal=got == want)
            val[f'{n}_layers_vs_b32_board'] = dict(equal=per == want_layers,
                                                   differing=[r['name'] for r, a in zip(r05[n], want_layers)
                                                              if r['predicted'] != a])
        sc = total(r05['skew'])['count_w4']
        val['skew_count_w4'] = dict(count=sc, required=VALIDATE['skew_count_w4'],
                                    skew_count_json=sk_img['Set12 05.png']['skewed']['w4'],
                                    equal=sc == VALIDATE['skew_count_w4'] == sk_img['Set12 05.png']['skewed']['w4'])
        oc = total(r05['original'])['count_w4']
        val['original_count_w4_vs_skew_count_json'] = dict(
            count=oc, skew_count_json=sk_img['Set12 05.png']['conventional']['w4'],
            equal=oc == sk_img['Set12 05.png']['conventional']['w4'])
        ok = all(v['equal'] for v in val.values())
        for k, v in val.items():
            print(f'  validate {k:<36} {"OK" if v["equal"] else "FAILED"}  {v}')
        if not ok:
            raise SystemExit('validation on 05.png failed: nothing written')

        per_image = {image: (r05, c05, sec)}
        rest = [i for i in IMAGES if i != VALIDATE['image']]
        jobs = max(1, min(args.jobs, 2))
        if jobs == 1:
            for i in rest:
                image, r, c, sec = run_image(i, exports, conv1_gap, args.tile)
                per_image[image] = (r, c, sec)
                print(f'{image} emulated in {sec} s', flush=True)
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
                futs = [pool.submit(run_image, i, exports, conv1_gap, args.tile) for i in rest]
                for f in concurrent.futures.as_completed(futs):
                    image, r, c, sec = f.result()
                    per_image[image] = (r, c, sec)
                    print(f'{image} emulated in {sec} s', flush=True)

    # Cross-checks of the counts on 06-08 (b32_testsets.json, skew_count.json)
    ts = {(r['set'], r['image']): r for r in json.loads((HERE/'b32_testsets.json').read_text())['images']}
    cross = {}
    for i in IMAGES:
        r = per_image[i][0]
        t = ts[(SET, i)]
        s = sk_img[f'{SET} {i}']
        cross[i] = dict(
            b32_testsets_w4={n: dict(count=total(r[n])['count_w4'], json=t['w4'][n],
                                     equal=total(r[n])['count_w4'] == t['w4'][n]) for n in LAYOUTS[:3]},
            b32_testsets_w4_conv2_9={n: dict(count=total(r[n])['conv2_9']['count_w4'], json=t['w4_conv2_9'][n],
                                             equal=total(r[n])['conv2_9']['count_w4'] == t['w4_conv2_9'][n])
                                     for n in LAYOUTS[:3]},
            skew_count_json=dict(original=dict(count=total(r['original'])['count_w4'], json=s['conventional']['w4'],
                                               equal=total(r['original'])['count_w4'] == s['conventional']['w4']),
                                 skew=dict(count=total(r['skew'])['count_w4'], json=s['skewed']['w4'],
                                           equal=total(r['skew'])['count_w4'] == s['skewed']['w4'])))

    checks = {i: per_image[i][1] for i in IMAGES}
    flat = []
    for i in IMAGES:
        c = checks[i]
        flat += [v['agrees_1e5'] for v in c['psnr_vs_int_eval'].values()]
        flat += list(c['conv1_windows_identical'].values()) + list(c['denoised_identical'].values())
        flat += list(c['nonzeros_per_layer_equal'].values())
        flat += list(c['conv1_prediction_identical'].values())
        if 'skew_export' in c:
            flat += [v for k, v in c['skew_export'].items() if k != 'differing_layers']
        flat += [c['skewed_layers'] == [f'conv{j}' for j in range(2, 10)]]
        flat += [all(v for k, v in s.items() if k not in ('name', 'C')) for s in c['skew_layers']]
        flat += [v['equal'] for d in cross[i].values() for v in d.values()]
    dx = sources['skew']['driver_export_checked']
    if dx:
        flat += [dx['tap_order_layers'] == [f'conv{j}' for j in range(2, 10)]] + list(dx['tap_order_is_skew_order'].values())
    all_checks = all(flat)

    runs = {n: {} for n in LAYOUTS}
    for n in LAYOUTS:
        for i in IMAGES:
            rows = per_image[i][0][n]
            runs[n][i] = dict(layers=rows, total=total(rows),
                              measured_before=n != 'skew' and i == VALIDATE['image'])
    predictions = {n: {i: dict(layers={r['name']: r['predicted'] for r in runs[n][i]['layers']},
                               total=runs[n][i]['total']['predicted']) for i in IMAGES} for n in LAYOUTS}
    savings = {i: {n: dict(predicted_cycles=runs['original'][i]['total']['predicted'] - runs[n][i]['total']['predicted'],
                           predicted_pct=pct(runs['original'][i]['total']['predicted'], runs[n][i]['total']['predicted']),
                           count_cycles=runs['original'][i]['total']['count_w4'] - runs[n][i]['total']['count_w4'],
                           count_pct=pct(runs['original'][i]['total']['count_w4'], runs[n][i]['total']['count_w4']),
                           fill_drain_difference=(runs['original'][i]['total']['fill_drain_w4']
                                                  - runs[n][i]['total']['fill_drain_w4']))
                   for n in LAYOUTS[1:]} for i in IMAGES}
    pooled = {n: dict(original=sum(runs['original'][i]['total']['predicted'] for i in IMAGES[1:]),
                      layout=sum(runs[n][i]['total']['predicted'] for i in IMAGES[1:])) for n in LAYOUTS}
    for n in LAYOUTS[1:]:
        pooled[n]['saving_pct'] = pct(pooled[n]['original'], pooled[n]['layout'])
    del pooled['original']

    board = json.loads((HERE/'board_transcribed.json').read_text(encoding='utf-8'))
    before = measured_before(board, per_image[VALIDATE['image']][0])

    never = [f'{n} {i}' for n in LAYOUTS for i in IMAGES if not (n != 'skew' and i == VALIDATE['image'])]
    res = dict(
        what=('exact W=4 board cycles predicted for the PROTOCOL_2 board runs, written before any of them; '
              'per layer CYCLES - IN_STALL must equal "predicted" exactly'),
        written_utc=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        script='bankperm/predict_board_2.py',
        protocol=protocol_record(),
        model=MODEL, network='B-32 ReLU + QAT s1', set=SET, images=list(IMAGES),
        noise='sigma 25 (the manifest\'s), test_noise seed 0, the board driver\'s host emulation',
        board=dict(bitstream='the existing W=4 bitstream (build zed_v4_p16_t4_w4_*)', core_id='0x4d410303',
                   driver_flags='scripts/run_denoise.py --w4 --mode 1 --fclk 50', tile=args.tile,
                   board_runs_per_layer=sorted({r['board_runs'] for n in LAYOUTS for i in IMAGES
                                                for r in runs[n][i]['layers']}),
                   padding=('none: every K (36, 288, 324) is a multiple of 4, so no zero taps and, every window '
                            'being whole beats, no zero windows are added')),
        core=f'P = {P} lanes, T = {T} banks, tap t of a window in bank t % 4, sparse mode (mode 1)',
        rule=dict(
            count='count_w4 = sum over windows of max(ceil(K/4) + 1, ceil(COUT/16) * max(1, max_b nnz_b), COUT) '
                  '(denoise/predict_w4.py window_cycles, W = 4, sparse)',
            fill_drain=('conv2..conv10, per board run: min(load, last) + 3 + ((COUT-1) % 16 + 1), load = ceil(K/4) + 1, '
                        'last = ceil(COUT/16) * max(1, max bank nnz) of the run\'s last window in the layout as sent '
                        '(denoise/w4_gaps.py); conv1: the measured constant '
                        f'{conv1_gap} per run'),
            conv1_constant=dict(value=conv1_gap, source=f'denoise/w4_gaps.json networks["{net_label}"] conv1 board_w4',
                                gap=g1['gap'], in_stall=g1['in_stall'],
                                note=('measured on the board on 05.png (the Original), not derived; conv1 reads the '
                                      'image, so its windows are the same in every layout (checked); used unchanged '
                                      'for 06-08')),
            predicted='count_w4 + fill_drain_w4',
            exactness_of_layouts=('every layout is the same function: Frozen and Multi-start relabel channels '
                                  '(denoised images identical, checked); the Skew permutes a window\'s taps and the '
                                  'weight columns together, |partial sum| <= K*127*128 < 2^31 in any order, and every '
                                  'accumulator of conv2..conv9 is the Original\'s (whole layers, integer oracle, checked)')),
        layouts=sources,
        validation=dict(image=f'{SET} {VALIDATE["image"]}', required=VALIDATE, results=val, passed=ok),
        cross_checks_counts=cross,
        checks=checks,
        all_checks_passed=all_checks,
        predictions=predictions,
        savings_vs_original=savings,
        pooled_06_08=pooled,
        measured_before=before,
        never_run_on_the_board=never,
        assumptions=[
            'one board run per layer: every layer here has at most 65536 windows (16,384 on 05-07, 65,536 on 08.png, '
            'the 2x2-unshuffled image), so run_denoise.py --tile 65536 (default) runs each layer once; '
            're-run with --tile N if another tile is used',
            'the Skew run sends conv2..conv9 windows with their taps in skew_order(288, 32) and the same columns of '
            'the weights (config.bin digests in runs.skew); conv1 and conv10 exactly as the Original. A host path '
            'that sends other windows is not what is predicted',
            'conv1\'s fill and drain is the 05.png Original\'s measured 17 on every image and layout (conv1 is not a '
            'prediction; its last window\'s load and compute are listed per image)',
            'CYCLES - IN_STALL is compared; this bitstream\'s IN_STALL does not count starvation at window '
            'boundaries (PROTOCOL_2), so a miss is a miss even with IN_STALL = 0',
        ],
        runs=runs,
        seconds=round(time.time() - t0, 1))
    args.out.write_text(json.dumps(res, indent=1) + '\n')

    print(f'\n{"":<12}' + ''.join(f'{i:>20}' for i in IMAGES))
    for n in LAYOUTS:
        print(f'{n:<12}' + ''.join(f'{predictions[n][i]["total"]:>20,}' for i in IMAGES))
    for n in LAYOUTS[1:]:
        print(f'{n[:6] + " saves":<12}' + ''.join(f'{savings[i][n]["predicted_cycles"]:>12,} ({savings[i][n]["predicted_pct"]:.2f}%)'
                                                for i in IMAGES))
    print('measured before (05.png):', before['summary'], '; raw W=4 report:', before['raw_report_original']['summary'])
    print('all checks passed:', all_checks)
    print(f'wrote {rel(args.out)} in {time.time()-t0:.0f} s')
    if not all_checks:
        raise SystemExit('a check failed: see "checks" and "cross_checks_counts" in the JSON')


if __name__ == '__main__':
    main()
