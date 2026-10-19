"""Exact W=4 board cycles of the L3 board runs (PROTOCOL_2_ADDENDUM.md), written before they run.

    python bankperm/export_layout.py --layout skew --orders bankperm/perms_2.json \
                                     --model dn_d10_c32_us_fx_qat --out DIR      # the L3 export
    python bankperm/predict_board_3.py --l3-export DIR [--jobs 2]   # writes bankperm/board_prediction_3.json
    python bankperm/predict_board_3.py [--jobs 2]                   # the same, building the export in a temp dir

bankperm/PROTOCOL_2_ADDENDUM.md (committed in d6521ec) adds four board runs to
PROTOCOL_2: L3 (skew + relabeling) of B-32 ReLU + QAT s1 (dn_d10_c32_us_fx_qat),
exactly as in bankperm/perms_2.json, exported with bankperm/export_layout.py
--orders (the relabeling folded into the producers with bankperm/fold.fold, then
the skew order on the inputs of conv2..conv9), on the same W=4 bitstream
(run_denoise.py --w4 --mode 1 --fclk 50), Set12 05.png, 06.png, 07.png, 08.png
(sigma 25, test_noise seed 0). It is a separate prediction: nothing of PROTOCOL_2's
(bankperm/board_prediction_2.json, RUN_W4_LAYOUTS.cmd) is read for the prediction
itself, only for the comparison with the Original and the Skew.

Per layer the windows are those of the board driver's host emulation of the L3
export (scripts/run_denoise.py denoise, --emulate; its tap_order path puts the
window columns of conv2..conv9 in the export's order), i.e. what the run streams.
The prediction of a layer is the PROTOCOL_2 rule (bankperm/predict_board_2.py
layer_record, imported, so the rule is the same code):

    count      sum over its windows of denoise/predict_w4.window_cycles at W=4,
               sparse mode: max(ceil(K/4) + 1, ceil(COUT/16) * max(1, max bank nnz), COUT)
    fill/drain conv2..conv10: min(load, last) + 3 + ((COUT-1) % 16 + 1) (denoise/w4_gaps.py),
               load = ceil(K/4) + 1, last = the compute of the run's own last window as
               sent (the L3 export's); conv1: the measured constant of denoise/w4_gaps.json
               (this network's conv1 board_w4 gap - in_stall = 17), not derived
    predicted  count + fill/drain, one board run per layer (--tile 65536)

Checks, all of them before anything is written (05.png first; on a failure there
the script stops and writes nothing):
  * the export: built with export_layout.write_layout from perms_2.json's orders of
    B-32 ReLU + QAT s1 (read with export_layout.read_orders, the CLI's own reader: no
    adapter is needed for perms_2.json); with --l3-export the given folder must be
    byte for byte that build. Independently of fold.py and export_layout.py, every
    layer's config.bin is rebuilt from the original's INT32 words (rows: output
    channel order[i] in row i for a relabelled producer; columns: slot s*C + (p + s)
    % C reads original column s*C + order[p] of the producer's order on a skewed
    layer) and must be the export's byte for byte; manifest.json must be the
    original's with the per-channel lists in the new row order and tap_order (the
    skew order) on conv2..conv9 and nothing else; every slot's bank is
    (s + class) % 4, class = the channel's position mod 4;
  * the emulation: the original export is emulated on the same image; every L3
    window is the original's with its columns in that mapping (conv1, conv10
    unchanged), every accumulator the original's with the output columns in the
    row order, the denoised image identical (array and PSNR = int_eval.json), the
    driver marks taps_reordered on conv2..conv9 only, and the original's records
    are board_prediction_2.json's Original records exactly (same emulation, same rule);
  * the counts: every image's L3 count (conv1..conv10, fill and drain left out)
    equals bankperm/results_2.json's L3 W=4 total of that image; the Original's
    equals results_2.json's L0.

Savings are given against board_prediction_2.json's Original and Skew of the same
image (predicted and count). Nothing of L3 has run on the board.
"""
import argparse
import concurrent.futures
import contextlib
import datetime
import hashlib
import io
import json
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
import export_layout  # noqa: E402
import run_denoise  # noqa: E402
from b32_board import MODEL, ORIGINAL, rel  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from predict_board_2 import layer_record, pct, total  # noqa: E402  (the PROTOCOL_2 rule, unchanged)
from predict_w4 import P, T  # noqa: E402
from skew_count import skew_order  # noqa: E402

ADDENDUM = HERE/'PROTOCOL_2_ADDENDUM.md'
ADDENDUM_COMMIT = 'd6521ec'
PERMS_2 = HERE/'perms_2.json'
NET_LABEL = 'B-32 ReLU + QAT s1'
PRED_2 = HERE/'board_prediction_2.json'
RESULTS_2 = HERE/'results_2.json'
LAYOUT = 'l3'
SET = 'Set12'
IMAGES = ('05.png', '06.png', '07.png', '08.png')
VALIDATE_IMAGE = '05.png'
W = 4
TILE = 65536
SKEWED = tuple(f'conv{i}' for i in range(2, 10))
LIST_KEYS = ('requant', 'w_scale', 'a_scale_out')          # per-output-channel lists fold.fold reorders
TEXT = {'.json', '.txt', '.md'}
CODE = ('scripts/run_denoise.py', 'scripts/run_cifar.py', 'scripts/run_board_xsdb.tcl', 'bankperm/export_layout.py',
        'bankperm/fold.py', 'bankperm/predict_board_2.py', 'bankperm/predict_board_3.py')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def lf_sha(path):
    """SHA-256 of a file, text files (.json, .txt, .md) with CRLF read as LF (prepare_layouts.lf_sha)."""
    data = Path(path).read_bytes()
    return sha256(data.replace(b'\r\n', b'\n') if Path(path).suffix in TEXT else data)


def git_bytes(spec):
    try:
        return subprocess.run(['git', '-C', str(ROOT), 'show', spec], capture_output=True, check=True).stdout, None
    except (OSError, subprocess.CalledProcessError) as e:
        return None, str(e)


# ------------------------------------------------------------------ the L3 mapping, written independently ---
def l3_mapping(layers, orders, img_ch):
    """Per layer {name: (cols, rows, skewed)}, without fold.py or export_layout.py.

    cols[j] = the original window column sent in slot j; rows[i] = the original output
    channel computed in row i. A producer in `orders` computes channel order[i] in row i
    (ReLU only here: no pooled maps). A consumer reads, at channel position p of its
    concatenated input, the original channel order[p] of that input's producer (the
    image and unlisted producers keep their order). On the skewed layers (conv2..conv(L-1)
    with one input map of C % 4 == 0, PROTOCOL_2 L2/L3) channel position p of 3x3
    position s goes to slot s*C + (p + s) % C; elsewhere to s*C + p."""
    by_name = {L['name']: L for L in layers}
    if 'image' in orders or layers[-1]['name'] in orders:
        raise SystemExit('the image and the last layer\'s output are never relabelled')
    out = {}
    for i, L in enumerate(layers):
        if L['post'] != 'none':
            raise SystemExit(f'{L["name"]}: post-op {L["post"]}; this mapping covers ReLU chains only')
        taps = L['kh']*L['kw']
        chan = []                               # original input channel at each position of the concatenation
        for parent in L['inputs']:
            n = img_ch if parent == 'image' else by_name[parent]['COUT']
            o = [int(v) for v in orders.get(parent, range(n))]
            assert sorted(o) == list(range(n)), (L['name'], parent)
            off = len(chan)
            chan += [off + v for v in o]
        c = len(chan)
        assert c*taps == L['K'], L['name']
        chan = np.asarray(chan, np.int64)
        skewed = 0 < i < len(layers)-1 and len(L['inputs']) == 1 and c % 4 == 0
        cols = np.empty(L['K'], np.int64)
        for s in range(taps):
            for p in range(c):
                slot = s*c + ((p + s) % c if skewed else p)
                cols[slot] = s*c + chan[p]
        assert np.array_equal(np.sort(cols), np.arange(L['K'])), L['name']
        rows = np.asarray(orders.get(L['name'], range(L['COUT'])), np.int64)
        assert np.array_equal(np.sort(rows), np.arange(L['COUT'])), L['name']
        out[L['name']] = (cols, rows, skewed)
    return out


def bank_rule_holds(cols, order, taps):
    """Every slot's bank (slot % 4) is (s + class) % 4, class = position of the channel in `order`, mod 4."""
    c = len(order)
    pos = np.empty(c, np.int64)
    pos[np.asarray(order)] = np.arange(c)
    s, ch = np.divmod(cols, c)
    return bool(np.array_equal(np.arange(taps*c) % T, (s + pos[ch] % 4) % T))


def rebuilt_config(words, k, cout, cols, rows):
    """The config.bin of a layer from the original's INT32 words: weights (COUT x K), then bias."""
    w = words[:cout*k].reshape(cout, k)[rows][:, cols]
    return np.concatenate([w.reshape(-1), words[cout*k:][rows]]).astype('<i4').tobytes()


def check_export(l3, orders):
    """The L3 export against the original, independently of fold.py and export_layout.py."""
    raw0 = json.loads((ORIGINAL/'manifest.json').read_text(encoding='utf-8'))
    raw3 = json.loads((l3/'manifest.json').read_text(encoding='utf-8'))
    man0, layers0 = run_denoise.load_layers(ORIGINAL)
    m = l3_mapping(layers0, orders, int(man0['img_ch']))
    want_skew = [int(v) for v in skew_order(288, 32)]
    per_layer, ok = [], True
    for n0, n3, L in zip(raw0['layers'], raw3['layers'], layers0):
        cols, rows, skewed = m[L['name']]
        k, cout = L['K'], L['COUT']
        words = np.frombuffer((ORIGINAL/n0['config']).read_bytes(), '<i4')
        assert words.size == cout*k + cout, n0['config']
        mine = rebuilt_config(words, k, cout, cols, rows)
        got = (l3/n3['config']).read_bytes()
        exp_node = dict(n0)
        for key in LIST_KEYS:
            if isinstance(exp_node.get(key), list):
                exp_node[key] = [n0[key][r] for r in rows]
        if skewed:
            exp_node['tap_order'] = [int(v) for v in skew_order(k, k//(L['kh']*L['kw']))]
        rec = dict(name=L['name'], skewed=skewed, outputs_relabeled=bool(L['name'] in orders),
                   inputs_relabeled=bool(any(p in orders for p in L['inputs'])),
                   config=n3['config'], config_sha256=sha256(got), rebuilt_config_sha256=sha256(mine),
                   config_identical_to_rebuilt=got == mine,
                   config_identical_to_original=got == (ORIGINAL/n0['config']).read_bytes(),
                   manifest_entry_as_expected=n3 == exp_node,
                   tap_order_as_expected=(n3.get('tap_order') == want_skew) if skewed else 'tap_order' not in n3)
        if skewed:
            taps = L['kh']*L['kw']
            order = np.asarray(orders.get(L['inputs'][0], range(k//taps)), np.int64)
            rec['bank_rule_holds'] = bank_rule_holds(cols, order, taps)
            # what the export's own two steps compose to: the fold's columns, then its tap_order
            c = len(order)
            fold_cols = (np.arange(taps)[:, None]*c + order[None, :]).reshape(-1)
            rec['fold_then_tap_order_is_the_mapping'] = bool(np.array_equal(fold_cols[np.asarray(n3['tap_order'])], cols))
        ok &= all(v for kk, v in rec.items() if isinstance(v, bool) and kk not in
                  ('skewed', 'outputs_relabeled', 'inputs_relabeled', 'config_identical_to_original'))
        per_layer.append(rec)
    top_same = {k: v for k, v in raw0.items() if k != 'layers'} == {k: v for k, v in raw3.items() if k != 'layers'}
    names_same = [x['name'] for x in raw0['layers']] == [x['name'] for x in raw3['layers']]
    int_eval_same = (l3/'int_eval.json').read_bytes() == (ORIGINAL/'int_eval.json').read_bytes()
    expect = dict(skewed=list(SKEWED), outputs_relabeled=[f'conv{i}' for i in range(1, 9)],
                  inputs_relabeled=list(SKEWED), config_unchanged=['conv10'])
    got_sets = dict(skewed=[r['name'] for r in per_layer if r['skewed']],
                    outputs_relabeled=[r['name'] for r in per_layer if r['outputs_relabeled']],
                    inputs_relabeled=[r['name'] for r in per_layer if r['inputs_relabeled']],
                    config_unchanged=[r['name'] for r in per_layer if r['config_identical_to_original']])
    ok &= top_same and names_same and int_eval_same and got_sets == expect
    return dict(layers=per_layer, manifest_top_level_identical=top_same, layer_names_identical=names_same,
                int_eval_identical=int_eval_same, layer_sets=got_sets, layer_sets_expected=expect,
                all_ok=bool(ok)), m


def build_and_compare(orders, given, tmp):
    """Build the L3 export with export_layout.write_layout; with `given`, require it byte for byte."""
    fresh = Path(tmp)/'l3'
    lm = export_layout.write_layout(ORIGINAL, fresh, 'skew', orders, PERMS_2)
    if given is None:
        return fresh, dict(built_here=True, files_identical_to_a_fresh_build=None)
    names = sorted({p.name for p in fresh.iterdir()} | {p.name for p in given.iterdir()})
    diff = [n for n in names if not (fresh/n).is_file() or not (given/n).is_file()
            or (fresh/n).read_bytes() != (given/n).read_bytes()]
    return given, dict(built_here=False, files_identical_to_a_fresh_build=not diff, differing_files=diff,
                       fresh_layout_manifest_tap_orders_equal=lm['tap_orders'] == json.loads(
                           (given/'layout_manifest.json').read_text(encoding='utf-8')).get('tap_orders'))


# ------------------------------------------------------------------------------------------ emulation ---
def emulate(export, image, conv1_gap, tile, hook=None):
    """run_denoise.denoise (the driver's host path) on one image -> layer records, output, driver records."""
    man, layers = run_denoise.load_layers(export)
    _, clean, noisy = next(t for t in test_noise(load_set(SET), man['sigma'], seed=0) if t[0] == image)
    q_in = np.rint(noisy*QMAX_A).astype(np.uint8)          # as int_eval and run_denoise.py
    rows = []
    real = run_denoise.run_layer

    def capture(L, x, args, tag):
        i = len(rows)
        acc, info = real(L, x, args, tag)
        k = L['K']
        rec = layer_record(i, L, x, conv1_gap, tile)
        rec['config_sha256'] = sha256(Path(L['cfg']).read_bytes())
        # as streamed: K % 4 == 0 means no zero taps; N*K % 4 == 0 no zero windows (run_layer)
        rec['zero_padding'] = dict(taps=(-k) % W, windows=0 if (x.shape[0]*k) % 4 == 0 else None)
        rows.append(rec)
        if hook is not None:
            hook(i, L, x, acc)
        return acc, info

    run_denoise.run_layer = capture
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out, recs = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'pred3')
    finally:
        run_denoise.run_layer = real
    p = float(psnr(clean, out.astype(np.float32)/255))
    int_eval = json.loads((export/'int_eval.json').read_text())[SET]['per_image'][image]
    return dict(rows=rows, out=out, psnr=p, int_eval=int_eval, driver=recs, layers=layers, man=man)


def run_image(image, l3, orders, conv1_gap, tile, pred2_original):
    """The original and the L3 export on one image: the L3 records and every check against the original."""
    t0 = time.time()
    keep = []
    e0 = emulate(ORIGINAL, image, conv1_gap, tile, hook=lambda i, L, x, acc: keep.append((x.copy(), acc.copy())))
    m = l3_mapping(e0['layers'], orders, int(e0['man']['img_ch']))
    per = []

    def check(i, L, x, acc):
        x0, a0 = keep[i]
        cols, rows, skewed = m[L['name']]
        per.append(dict(name=L['name'], skewed=skewed,
                        windows_are_the_originals_in_the_mapping=bool(x.shape == x0.shape and np.array_equal(x, x0[:, cols])),
                        windows_identical_to_the_original=bool(x.shape == x0.shape and np.array_equal(x, x0)),
                        accumulators_are_the_originals_in_the_row_order=bool(np.array_equal(acc, a0[:, rows])),
                        nonzeros_equal=int((x != 0).sum()) == int((x0 != 0).sum())))
    e3 = emulate(l3, image, conv1_gap, tile, hook=check)
    r0, r3 = e0['rows'], e3['rows']
    for rec, L, d in zip(r3, e3['layers'], e3['driver']):
        rec['taps_reordered'] = bool(d.get('taps_reordered', False))   # what the board report will mark
        rec['outputs_relabeled'] = L['name'] in orders
    want_same = [r['name'] for r in per if not r['skewed']]
    chk = dict(
        layers=per,
        windows_identical_to_the_original_on=[r['name'] for r in per if r['windows_identical_to_the_original']],
        unchanged_layers_expected=want_same,
        taps_reordered_on=[r['name'] for r in r3 if r['taps_reordered']],
        denoised_identical=bool(np.array_equal(e3['out'], e0['out'])),
        psnr=dict(l3=e3['psnr'], original=e0['psnr'], int_eval=e3['int_eval'],
                  agrees_1e5=abs(e3['psnr'] - e3['int_eval']) <= 1e-5 and abs(e0['psnr'] - e0['int_eval']) <= 1e-5),
        original_records_equal_board_prediction_2=([{k: v for k, v in r.items() if k != 'zero_padding'} for r in r0]
                                                   == pred2_original[image]['layers']),
        conv1_record_as_the_originals=({k: v for k, v in r3[0].items() if k not in ('config_sha256', 'taps_reordered',
                                                                                  'outputs_relabeled')}
                                       == {k: v for k, v in r0[0].items() if k != 'config_sha256'}),
        conv10_record_as_the_originals=({k: v for k, v in r3[-1].items() if k not in ('taps_reordered', 'outputs_relabeled')}
                                        == r0[-1]),
        no_zero_padding=all(r['zero_padding'] == dict(taps=0, windows=0) for r in r3),
        one_board_run_per_layer=all(r['board_runs'] == 1 for r in r3))
    flat = [all(v for k, v in r.items() if isinstance(v, bool) and k not in ('skewed', 'windows_identical_to_the_original'))
            for r in per]
    flat += [chk['windows_identical_to_the_original_on'] == want_same, chk['taps_reordered_on'] == list(SKEWED),
             chk['denoised_identical'], chk['psnr']['agrees_1e5'], chk['original_records_equal_board_prediction_2'],
             chk['conv1_record_as_the_originals'], chk['conv10_record_as_the_originals'], chk['no_zero_padding'],
             chk['one_board_run_per_layer']]
    chk['all_ok'] = bool(all(flat))
    return image, r3, total(r0), chk, round(time.time() - t0, 1)


# ------------------------------------------------------------------------------------------------ main ---
def protocol_record():
    text = ADDENDUM.read_bytes()
    rec = dict(file=rel(ADDENDUM), commit=ADDENDUM_COMMIT, sha256=sha256(text), adds_to='bankperm/PROTOCOL_2.md',
               test='a layer is predicted if CYCLES - IN_STALL equals it exactly; every miss is listed')
    blob, err = git_bytes(f'{ADDENDUM_COMMIT}:bankperm/PROTOCOL_2_ADDENDUM.md')
    rec['identical_to_commit'] = None if blob is None else blob == text.replace(b'\r\n', b'\n')
    if err:
        rec['git_error'] = err
    return rec


def file_record(path):
    blob, err = git_bytes(f'HEAD:{rel(path)}')
    return dict(file=rel(path), lf_sha256=lf_sha(path),
                identical_to_head=None if blob is None else blob == Path(path).read_bytes().replace(b'\r\n', b'\n'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--l3-export', type=Path, help='the L3 export (bankperm/export_layout.py --layout skew --orders '
                                                   'bankperm/perms_2.json); default: built here in a temp dir')
    ap.add_argument('--tile', type=int, default=TILE, help='windows per board run, as run_denoise.py --tile')
    ap.add_argument('--jobs', type=int, default=1, help='processes for 06-08 (at most 2)')
    ap.add_argument('--out', type=Path, default=HERE/'board_prediction_3.json')
    args = ap.parse_args()
    t0 = time.time()

    gaps = json.loads((ROOT/'denoise'/'w4_gaps.json').read_text())
    net_label, net = next((k, v) for k, v in gaps['networks'].items() if v['model'] == MODEL)
    g1 = net['layers'][0]['board_w4']
    assert net['layers'][0]['name'] == 'conv1'
    conv1_gap = g1['gap'] - g1['in_stall']

    perms2 = json.loads(PERMS_2.read_text(encoding='utf-8'))
    entry = perms2['networks'][NET_LABEL]
    assert entry['model'] == MODEL
    orders = export_layout.read_orders(PERMS_2, MODEL)          # what export_layout.py --orders reads
    assert orders == entry['orders'], 'export_layout.read_orders does not give perms_2.json\'s B-32 ReLU s1 orders'
    pred2 = json.loads(PRED_2.read_text(encoding='utf-8'))
    assert pred2['model'] == MODEL and pred2['all_checks_passed'] is True
    res2 = json.loads(RESULTS_2.read_text(encoding='utf-8'))['networks'][NET_LABEL]
    assert res2['model'] == MODEL and res2['layouts'][:4] == ['L0', 'L1', 'L2', 'L3']

    with tempfile.TemporaryDirectory() as tmp:
        l3, built = build_and_compare(orders, args.l3_export.resolve() if args.l3_export else None, tmp)
        export_chk, _ = check_export(l3, orders)
        man3 = json.loads((l3/'manifest.json').read_text(encoding='utf-8'))
        if man3.get('model') != MODEL:
            raise SystemExit(f'{l3} is a {man3.get("model")} export, not {MODEL}')
        export_ok = export_chk['all_ok'] and built['files_identical_to_a_fresh_build'] is not False
        print(f'L3 export {export_layout.rel(l3)}: {"OK" if export_ok else "FAILED"}', flush=True)
        if not export_ok:
            print(json.dumps(dict(built=built, export=export_chk), indent=1))
            raise SystemExit('the L3 export check failed: nothing written')
        files = {p.name: dict(sha256=sha256(p.read_bytes()), lf_sha256=lf_sha(p))
                 for p in sorted(l3.iterdir()) if p.is_file()}
        lm = json.loads((l3/'layout_manifest.json').read_text(encoding='utf-8'))

        pred2_original = pred2['runs']['original']
        image, r05, o05, c05, sec = run_image(VALIDATE_IMAGE, l3, orders, conv1_gap, args.tile, pred2_original)
        print(f'{image} emulated in {sec} s', flush=True)
        key = f'{SET}/{VALIDATE_IMAGE}'
        val = dict(l3_count_w4_vs_results_2=dict(count=total(r05)['count_w4'], results_2=res2['per_image_totals'][key]['w4'][3]),
                   original_count_w4_vs_results_2=dict(count=o05['count_w4'], results_2=res2['per_image_totals'][key]['w4'][0]),
                   original_predicted_vs_board_prediction_2=dict(
                       predicted=o05['predicted'], board_prediction_2=pred2['predictions']['original'][VALIDATE_IMAGE]['total']))
        for v in val.values():
            a, b = list(v.values())
            v['equal'] = a == b
        val['checks_05'] = dict(equal=c05['all_ok'])
        ok05 = all(v['equal'] for v in val.values())
        for k, v in val.items():
            print(f'  validate {k:<42} {"OK" if v["equal"] else "FAILED"}  {v}')
        if not ok05:
            print(json.dumps(c05, indent=1))
            raise SystemExit('validation on 05.png failed: nothing written')

        per_image = {image: (r05, o05, c05, sec)}
        rest = [i for i in IMAGES if i != VALIDATE_IMAGE]
        jobs = max(1, min(args.jobs, 2))
        if jobs == 1:
            for i in rest:
                image, r, o, c, sec = run_image(i, l3, orders, conv1_gap, args.tile, pred2_original)
                per_image[image] = (r, o, c, sec)
                print(f'{image} emulated in {sec} s', flush=True)
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
                futs = [pool.submit(run_image, i, l3, orders, conv1_gap, args.tile, pred2_original) for i in rest]
                for f in concurrent.futures.as_completed(futs):
                    image, r, o, c, sec = f.result()
                    per_image[image] = (r, o, c, sec)
                    print(f'{image} emulated in {sec} s', flush=True)
        export_path = export_layout.rel(l3) if args.l3_export else '(built in a temporary directory by this script)'

    runs, predictions, counts, savings, checks = {}, {}, {}, {}, {}
    for i in IMAGES:
        rows, o_tot, chk, _ = per_image[i]
        t = total(rows)
        runs[i] = dict(layers=rows, total=t)
        predictions[i] = dict(layers={r['name']: r['predicted'] for r in rows}, total=t['predicted'])
        r2 = res2['per_image_totals'][f'{SET}/{i}']['w4']
        counts[i] = dict(l3_count_w4=t['count_w4'], results_2_L3_w4=r2[3], equal=t['count_w4'] == r2[3],
                         original_count_w4=o_tot['count_w4'], results_2_L0_w4=r2[0],
                         original_equal=o_tot['count_w4'] == r2[0],
                         skew_count_w4_board_prediction_2=pred2['runs']['skew'][i]['total']['count_w4'],
                         results_2_L2_w4=r2[2],
                         skew_equal=pred2['runs']['skew'][i]['total']['count_w4'] == r2[2])
        sv = {}
        for n in ('original', 'skew'):
            b = pred2['runs'][n][i]['total']
            sv[f'vs_{n}'] = dict(board_prediction_2_predicted=b['predicted'], l3_predicted=t['predicted'],
                                 predicted_cycles=b['predicted'] - t['predicted'],
                                 predicted_pct=pct(b['predicted'], t['predicted']),
                                 board_prediction_2_count_w4=b['count_w4'], l3_count_w4=t['count_w4'],
                                 count_cycles=b['count_w4'] - t['count_w4'], count_pct=pct(b['count_w4'], t['count_w4']),
                                 fill_drain_difference=b['fill_drain_w4'] - t['fill_drain_w4'],
                                 conv2_9_predicted_cycles=b['conv2_9']['predicted'] - t['conv2_9']['predicted'],
                                 conv2_9_predicted_pct=pct(b['conv2_9']['predicted'], t['conv2_9']['predicted']))
        savings[i] = sv
        checks[i] = chk
    pooled = {}
    for label, ims in (('05_08', IMAGES), ('06_08', IMAGES[1:])):
        lay = sum(runs[i]['total']['predicted'] for i in ims)
        rec = dict(images=list(ims), l3_predicted=lay)
        for n in ('original', 'skew'):
            b = sum(pred2['runs'][n][i]['total']['predicted'] for i in ims)
            rec[f'{n}_predicted'] = b
            rec[f'saving_vs_{n}_pct'] = pct(b, lay)
        pooled[label] = rec

    all_checks = bool(export_ok and all(c['all_ok'] for c in checks.values())
                      and all(c['equal'] and c['original_equal'] and c['skew_equal'] for c in counts.values()))
    config_sha = {r['name']: r['config_sha256'] for r in runs[IMAGES[0]]['layers']}
    same_cfg = all({r['name']: r['config_sha256'] for r in runs[i]['layers']} == config_sha for i in IMAGES)
    all_checks &= same_cfg and config_sha == {r['name']: r['config_sha256'] for r in export_chk['layers']}
    res = dict(
        what=('exact W=4 board cycles predicted for the L3 board runs of PROTOCOL_2_ADDENDUM.md, written before any '
              'of them; per layer CYCLES - IN_STALL must equal "predicted" exactly'),
        written_utc=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        script='bankperm/predict_board_3.py',
        protocol=protocol_record(),
        model=MODEL, network='B-32 ReLU + QAT s1', layout=LAYOUT, set=SET, images=list(IMAGES),
        noise='sigma 25 (the manifest\'s), test_noise seed 0, the board driver\'s host emulation',
        board=dict(bitstream='the existing W=4 bitstream (build zed_v4_p16_t4_w4_*), the one of PROTOCOL_2\'s runs',
                   core_id='0x4d410303', driver_flags='scripts/run_denoise.py --w4 --mode 1 --fclk 50', tile=args.tile,
                   runs_folder='denoise/board_runs/q1_layouts3/ (PROTOCOL_2_ADDENDUM.md)',
                   board_runs_per_layer=sorted({r['board_runs'] for i in IMAGES for r in runs[i]['layers']}),
                   padding=('none: every K (36, 288, 324) is a multiple of 4, so no zero taps and, every window '
                            'being whole beats, no zero windows are added (checked per layer)')),
        core=f'P = {P} lanes, T = {T} banks, tap t of a window in bank t % 4, sparse mode (mode 1)',
        rule=dict(
            count='count_w4 = sum over windows of max(ceil(K/4) + 1, ceil(COUT/16) * max(1, max_b nnz_b), COUT) '
                  '(denoise/predict_w4.py window_cycles, W = 4, sparse)',
            fill_drain=('conv2..conv10, per board run: min(load, last) + 3 + ((COUT-1) % 16 + 1), load = ceil(K/4) + 1, '
                        'last = ceil(COUT/16) * max(1, max bank nnz) of the run\'s last window as the L3 export sends it '
                        f'(denoise/w4_gaps.py); conv1: the measured constant {conv1_gap} per run'),
            conv1_constant=dict(value=conv1_gap, source=f'denoise/w4_gaps.json networks["{net_label}"] conv1 board_w4',
                                gap=g1['gap'], in_stall=g1['in_stall'],
                                note=('measured on the board on 05.png (the Original), not derived; conv1 reads the '
                                      'image, so its windows are the Original\'s in L3 too (checked); its output rows '
                                      'are relabelled, which changes no window cycle')),
            predicted='count_w4 + fill_drain_w4',
            code='bankperm/predict_board_2.py layer_record and total, imported unchanged (the PROTOCOL_2 rule)'),
        layouts={LAYOUT: dict(
            orders_source=dict(network=NET_LABEL, **file_record(PERMS_2)),
            orders=orders,
            orders_meaning=('keyed by producer: order[p] = the original output channel at position p of its map; '
                            'class p % 4 (fit.order_from_group); a consumer\'s channel position p of 3x3 position s is '
                            'sent in slot s*32 + (p + s) % 32 (bank (s + class) % 4) on conv2..conv9'),
            export_command=('python bankperm/export_layout.py --layout skew --orders bankperm/perms_2.json '
                            f'--model {MODEL} --out DIR'),
            export_path=export_path, export_build=built,
            no_adapter=('export_layout.read_orders reads perms_2.json directly (networks.<label>.orders of the entry '
                        'with this model) and gives exactly perms_2.json\'s B-32 ReLU + QAT s1 orders (asserted); the '
                        'independent mapping below is a second construction of the same export, not an adapter'),
            export_check=export_chk,
            config_sha256=config_sha,
            config_sha256_meaning=('SHA-256 of each layer\'s <layer>_config.bin in the L3 export, the bytes the driver '
                                   'streams as the layer\'s configuration; identical to the independent rebuild from '
                                   'the original\'s INT32 words and on every image\'s record'),
            tap_order_layers=list(lm['tap_orders']),
            tap_order_288_32=[int(v) for v in skew_order(288, 32)],
            tap_order_meaning='tap_order[slot] = the folded export\'s tap index sent in that slot (x_l3 = x_folded[:, order])',
            export_files=files,
            platform_note=('the config.bin files and manifest.json (export_layout.py writes it with LF) are the same '
                           'bytes wherever the export is built; int_eval.json is copied from the checkout, so compare '
                           'it with CRLF read as LF (lf_sha256). permutation_manifest.json (fold.fold: derived_from = '
                           'str(relative path), written with write_text) has backslashes in derived_from and CRLF '
                           'line ends when the export is built on Windows, and layout_manifest.json records that '
                           'file\'s raw hash: those two do not carry the same hash there and are not what the '
                           'board streams'),
            layout_manifest_sha256=files['layout_manifest.json']['sha256'])},
        comparison_sources=dict(board_prediction_2=dict(**file_record(PRED_2), written_utc=pred2['written_utc']),
                                results_2=file_record(RESULTS_2)),
        validation=dict(image=f'{SET} {VALIDATE_IMAGE}', results=val, passed=ok05),
        counts_vs_results_2=counts,
        checks=checks,
        config_sha256_same_on_every_image=same_cfg,
        all_checks_passed=all_checks,
        predictions={LAYOUT: predictions},
        savings=savings,
        pooled=pooled,
        never_run_on_the_board=[f'{LAYOUT} {i}' for i in IMAGES],
        assumptions=[
            'one board run per layer: every layer here has at most 65536 windows (16,384 on 05-07, 65,536 on 08.png), '
            'so run_denoise.py --tile 65536 runs each layer once; with another tile each run pays its own fill/drain',
            'the L3 run is scripts/run_denoise.py --export-dir <the L3 export> on the W=4 bitstream: conv2..conv9 '
            'windows with their columns in the export\'s tap_order (the skew order) after the relabeling folded into '
            'the producers, conv1 and conv10 windows as the Original\'s; the config.bin streamed per layer has the '
            'SHA-256 in layouts.l3.config_sha256. A host path that sends other windows or weights is not what is '
            'predicted',
            'conv1\'s fill and drain is the 05.png Original\'s measured 17 on every image (not a prediction)',
            'CYCLES - IN_STALL is compared; this bitstream\'s IN_STALL does not count starvation at window '
            'boundaries (PROTOCOL_2), so a miss is a miss even with IN_STALL = 0',
        ],
        code={n: lf_sha(ROOT/n) for n in CODE},
        runs={LAYOUT: runs},
        seconds=round(time.time() - t0, 1))
    args.out.write_bytes(json.dumps(res, indent=1).encode('utf-8') + b'\n')

    print(f'\n{"":<16}' + ''.join(f'{i:>22}' for i in IMAGES))
    print(f'{"L3 predicted":<16}' + ''.join(f'{predictions[i]["total"]:>22,}' for i in IMAGES))
    for n in ('original', 'skew'):
        print(f'{"vs " + n:<16}' + ''.join(f'{savings[i]["vs_" + n]["predicted_cycles"]:>12,} ({savings[i]["vs_" + n]["predicted_pct"]:.3f}%)'
                                            for i in IMAGES))
    print('L3 counts = results_2.json:', all(c['equal'] for c in counts.values()))
    print('all checks passed:', all_checks)
    print(f'wrote {rel(args.out)} in {time.time()-t0:.0f} s')
    if not all_checks:
        raise SystemExit('a check failed: see "checks", "counts_vs_results_2" and layouts.l3.export_check in the JSON')


if __name__ == '__main__':
    main()
