"""Check the L3 export (skew + relabeling) before any L3 board run (bankperm/PROTOCOL_2_ADDENDUM.md).

    python bankperm/check_l3_export.py              # writes bankperm/l3_export_check.json (about a minute)
    python bankperm/check_l3_export.py --no-board   # without the stand-in debugger run (it needs tclsh)

The L3 export is bankperm/export_layout.py's --orders path on dn_d10_c32_us_fx_qat
(B-32 ReLU + QAT s1) with the L3 orders of bankperm/perms_2.json, read as they are:
export_layout.read_orders takes the "networks" entry whose model is this one and its
"orders" ({producer: [original channel at each position]}, the perms.json encoding of
DEVIATIONS_2.md section 2), so no adapter or second orders file is needed. The
relabeling is folded into the producers (bankperm/fold.fold), then the skew is put on
the inputs of conv2..conv9 (skew_count.skew_order). RUN_W4_L3.cmd writes the same
export on the board PC with

    python bankperm/export_layout.py --layout skew --model dn_d10_c32_us_fx_qat --orders bankperm/perms_2.json --out build/layout_exports/l3

What is checked, all of it on the host (nothing here touches a board):

  inputs      the orders read by export_layout.read_orders are perms_2.json's for this
              network, the "order" of every fitted layer there, and a permutation; the
              class of each channel (its position mod 4) is the fit's
              class_of_original_channel; perms_2.json is the committed file
  export      every config.bin, rebuilt from the original export without fold.py: the
              weight rows (and bias) in the layer's output order (orders[layer] for
              conv1..conv8, the identity for conv9, conv10) and the columns in
              evaluate_2.skew_columns(order of the producer) on conv2..conv9 (the windows
              results_2.json counted for L3), the identity on conv1 and conv10; every
              skewed slot's bank (slot mod 4) is (s + class of its channel) mod 4;
              tap_order = skew_count.skew_order(288, 32) on conv2..conv9 and nowhere
              else; manifest.json the original's with its per-channel lists in the
              output order plus tap_order and nothing else; int_eval.json the
              original's byte for byte; against the original, conv1..conv9 config.bin and
              manifest.json differ and conv10_config.bin and int_eval.json are the same
              (files_against_original; layout_manifest.json's changed_files is against
              fold.py's intermediate, not the original); the intermediate fold.fold
              export, with the skew on top, gives the same files; the command line export
              (as RUN_W4_L3.cmd runs it) is byte for byte the in-process one
  emulation   the original and the L3 export emulated (run_denoise.denoise, the
              driver's own host path) on Set12 05.png and BSD68 test001.png: denoised
              image and PNG bytes identical; every layer's INT32 accumulators the
              original's up to the column order (acc_l3 == acc_0[:, output order]);
              every layer's windows the original's with the L3 columns; per layer the
              W = 1, 2, 4 counts (denoise/predict_w4.window_cycles), summed equal to
              results_2.json's L3 (and L0) per-image totals for that image. Then the
              same two runs through the command line (run_denoise.py --emulate
              [--export-dir]): PNGs identical, report.json identical but for
              export_dir, host_seconds and the taps_reordered marks on conv2..conv9
  board path  scripts/run_denoise.py on the board path (--w4 --mode 1 --fclk 50 --tile
              65536, Set12 05.png) with xsdb replaced by the repository's stand-in
              debugger (bankperm/check_skew_export.py fake_xsdb: the bytes its DMA
              streams are recorded): per layer the configuration stream is the L3
              export's config.bin and the window stream the emulated L3 windows; on
              conv2..conv9 both differ from the original's; 10 board runs, the
              taps_reordered marks on conv2..conv9 only, and the PNG the emulated one.
              The stand-in core copies gold into the results, so its mismatches and
              cycles say nothing; what it checks is what the driver writes and sends
  unchanged   the files RUN_W4_LAYOUTS.cmd runs, imports or its setup.json pins (the
              PROTOCOL_2 board plan, its prediction, the exports and ZIPs, the driver,
              the comparison and every repository module they import) are the committed
              ones and those of the addendum's commit d6521ec; over the whole tree,
              git diff d6521ec names only the L3 files, results of the board runs and
              documentation (*.md other than PROTOCOL_2*.md, bankperm/figures/); and the
              skew export written now has every hash bankperm/skew_export_check.json records
  imports     the repository modules the L3 steps import (prepare_l3, compare_board_3,
              export_layout with fold, run_denoise) are all in prepare_l3.TOOLS or the
              driver files, and those the PROTOCOL_2 steps import (prepare_layouts,
              compare_board_2, export_layout with fold, run_denoise) all in the unchanged list
  run script  RUN_W4_L3.cmd has LF line ends, is ASCII, holds the export, check, pin and
              board-run lines this check is for (the --w4 --mode 1 --fclk 50 --tile 65536
              flags of the stand-in run), and none of its commands names a PROTOCOL_2
              folder or script
  build       python -m py_compile on the L3 files
  (info)      prediction_3: whether bankperm/board_prediction_3.json, if there, lists this
              export's config.bin digests (not part of all_ok; prepare_l3.py --bitstream
              requires it on the board PC)

tool_code_lf_sha256 records the hash (CRLF read as LF) of every file of prepare_l3.TOOLS
(RUN_W4_L3.cmd, the L3 scripts, this one included, and the modules they import), which
prepare_l3.py --verify and --bitstream require on the board PC: change any of them and
this check must be run again (and its output committed) before the L3 runs.

export_files_lf_sha256 records the hash of every file of the L3 export and of the
original (text files with CRLF read as LF), which bankperm/prepare_l3.py --verify
compares on the board PC. permutation_manifest.json is compared there with fold.py's
"derived_from" path separators read as "/" (fold.py writes the platform's separator),
export_files_portable_sha256; on this machine the two hashes are the same.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import check_skew_export as cse  # noqa: E402 (the stand-in debugger, emulation and command line helpers)
import export_layout  # noqa: E402
import fold  # noqa: E402
import prepare_l3  # noqa: E402
import run_denoise  # noqa: E402
from common import psnr  # noqa: E402
from evaluate_2 import check_bank_rule, skew_columns  # noqa: E402
from predict_w4 import window_cycles  # noqa: E402
from skew_count import skew_order  # noqa: E402

MODEL = prepare_l3.MODEL
LABEL = 'B-32 ReLU + QAT s1'
ORIGINAL = prepare_l3.ORIGINAL
PERMS_2 = prepare_l3.PERMS_2
RESULTS_2 = HERE/'results_2.json'
IMAGES = [('Set12', '05.png'), ('BSD68', 'test001.png')]
SKEWED = [f'conv{i}' for i in range(2, 10)]
NEW_FILES = ['bankperm/check_l3_export.py', 'bankperm/prepare_l3.py', 'bankperm/compare_board_3.py',
             'bankperm/predict_board_3.py']
# What RUN_W4_LAYOUTS.cmd runs, imports or its setup.json pins: none of it may change for L3.
PROTOCOL_2_FILES = ['RUN_W4_LAYOUTS.cmd', 'bankperm/PROTOCOL_2.md', 'bankperm/PROTOCOL_2_ADDENDUM.md',
                    'bankperm/board_prediction_2.json', 'bankperm/skew_export_check.json',
                    'bankperm/export_layout.py', 'bankperm/prepare_layouts.py', 'bankperm/compare_board_2.py',
                    'bankperm/check_skew_export.py', 'bankperm/predict_board_2.py', 'bankperm/fold.py',
                    'bankperm/skew_count.py', 'bankperm/board_transcribed.json', 'bankperm/perms_2.json',
                    'bankperm/results_2.json', 'scripts/run_denoise.py', 'scripts/run_cifar.py',
                    'scripts/run_board_xsdb.tcl', 'scripts/_fake_xsdb_inner.tcl',
                    'bankperm/fit.py', 'denoise/common.py', 'denoise/count_test_sets.py', 'denoise/predict_w4.py',
                    'scripts/q1_reviewer_bank.py', 'scripts/q1_reviewer_export.py',
                    'research/q1_codesign/artifacts/q1_bank_reordered_export_20261018.zip',
                    'research/q1_codesign/artifacts/q1_multistart_verified_export_20261018.zip'] + sorted(
    (ORIGINAL.relative_to(ROOT)/p.name).as_posix() for p in ORIGINAL.iterdir() if p.is_file())
PROTOCOL_2_REF = 'd6521ec'       # the addendum's commit: none of PROTOCOL_2_FILES may differ from it
# Paths git diff PROTOCOL_2_REF may name (over the whole tree): the L3 files, the results of the board runs, and
# documentation (another workflow rewrites the paper, README and figures); nothing that is run or pinned.
L3_PATHS = ['RUN_W4_L3.cmd', 'bankperm/board_prediction_3.json', 'bankperm/l3_export_check.json',
            'bankperm/board_measured_2.json', 'bankperm/board_measured_3.json'] + NEW_FILES
RESULT_DIRS = ['denoise/board_runs/q1_layouts2/', 'denoise/board_runs/q1_layouts2_attempts/',
               'denoise/board_runs/q1_layouts3/', 'denoise/board_runs/q1_layouts3_attempts/']
DOC_DIRS = ['bankperm/figures/']
# The modules the L3 steps and the PROTOCOL_2 steps import (as scripts run by RUN_W4_L3.cmd / RUN_W4_LAYOUTS.cmd).
L3_MODULES = ['prepare_l3', 'compare_board_3', 'export_layout', 'fold', 'skew_count', 'run_denoise']
PROTOCOL_2_MODULES = ['prepare_layouts', 'compare_board_2', 'export_layout', 'fold', 'skew_count', 'run_denoise']
TRACE = r'''
import json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root/'bankperm'), str(root/'denoise'), str(root/'scripts')]
for m in sys.argv[2].split(','):
    __import__(m)
print(json.dumps(sorted(Path(m.__file__).resolve().relative_to(root).as_posix() for m in list(sys.modules.values())
                        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(root))))
'''
RUN_SCRIPT = ROOT/'RUN_W4_L3.cmd'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rel(p):
    return prepare_l3.rel(p)


def git(*args):
    r = subprocess.run(['git', '-C', str(ROOT)] + list(args), capture_output=True)
    return r.returncode, r.stdout, r.stderr.decode(errors='replace').strip()


def lf(path):
    return Path(path).read_bytes().replace(b'\r\n', b'\n')


# ----------------------------------------------------------------------------- the L3 layout

def out_order(L, orders):
    return np.asarray(orders[L['name']], np.int64) if L['name'] in orders else np.arange(L['COUT'])


def l3_columns(L, orders):
    """The original window columns each slot of the L3 window reads (results_2.json's L3)."""
    if L['name'] in SKEWED:
        assert len(L['inputs']) == 1 and L['K'] == 9*32, L['name']
        return skew_columns(orders[L['inputs'][0]], 9)
    if any(p in orders for p in L['inputs']):
        raise SystemExit(f'{L["name"]} reads a relabelled map but is not skewed: not the L3 of PROTOCOL_2')
    return np.arange(L['K'])


def check_inputs(orders):
    p2 = json.loads(PERMS_2.read_text(encoding='utf-8'))
    net = p2['networks'][LABEL]
    rows = []
    for f in net['fitted']:
        o = orders.get(f['producer'])
        cls = [o.index(c) % 4 for c in range(len(o))] if o else None
        rows.append(dict(layer=f['layer'], producer=f['producer'], order_equals_fitted_order=o == f['order'],
                         is_permutation=sorted(o or []) == list(range(f['C_in'])),
                         classes_equal_fitted_classes=cls == f['class_of_original_channel'],
                         class_sizes=[int(v) for v in np.bincount(np.arange(f['C_in']) % 4)]))
    rec = dict(perms_2=dict(file=rel(PERMS_2), **prepare_l3.text_record(PERMS_2)), network=LABEL,
               model=net['model'], read_by='bankperm/export_layout.py read_orders (networks entry of the model)',
               orders_equal_perms_2_entry=orders == net['orders'], producers=sorted(orders, key=lambda c: int(c[4:])),
               fitted=rows)
    rc, out, _ = git('rev-parse', f'HEAD:{rel(PERMS_2)}')
    rec['perms_2']['committed_blob'] = out.decode().strip() if not rc else None
    rec['perms_2']['is_committed_version'] = rec['perms_2']['committed_blob'] == rec['perms_2']['git_blob']
    rec['all_ok'] = bool(net['model'] == MODEL and rec['orders_equal_perms_2_entry'] and rec['perms_2']['is_committed_version']
                         and rec['producers'] == [f'conv{i}' for i in range(1, 9)]
                         and all(r['order_equals_fitted_order'] and r['is_permutation'] and r['classes_equal_fitted_classes']
                                 for r in rows))
    return rec


def check_export(l3, lm, orders, work):
    """The L3 export against the original, file by file, without fold.py; then fold.py's intermediate."""
    raw0 = json.loads((ORIGINAL/'manifest.json').read_bytes())
    _, lay0 = run_denoise.load_layers(ORIGINAL)
    p2 = json.loads(PERMS_2.read_text(encoding='utf-8'))['networks'][LABEL]
    classes = {f['layer']: f['class_of_original_channel'] for f in p2['fitted']}
    rows, ok = {}, True
    for L in lay0:
        po, cols = out_order(L, orders), l3_columns(L, orders)
        want = np.concatenate([L['wq'].astype('<i4')[po][:, cols].reshape(-1), L['bq'].astype('<i4')[po]])
        got = (l3/L['config']).read_bytes()
        r = dict(rows_in_output_order=not np.array_equal(po, np.arange(L['COUT'])),
                 columns_l3=L['name'] in SKEWED, rebuilt_from_original=want.tobytes() == got,
                 identical_to_original=got == (ORIGINAL/L['config']).read_bytes())
        if L['name'] in SKEWED:
            r['bank_rule_skewed'] = check_bank_rule(cols, classes[L['name']], 9)
        ok &= r['rebuilt_from_original'] and r.get('bank_rule_skewed', True)
        ok &= r['identical_to_original'] == (L['name'] == 'conv10')
        rows[L['config']] = r
    raw1 = json.loads((l3/'manifest.json').read_bytes())
    taps = {n['name']: n.get('tap_order') for n in raw1['layers'] if 'tap_order' in n}
    want_order = [int(v) for v in skew_order(288, 32)]
    stripped = json.loads(json.dumps(raw1))
    for n in stripped['layers']:
        n.pop('tap_order', None)
    expect = json.loads(json.dumps(raw0))
    for n, L in zip(expect['layers'], lay0):
        po = out_order(L, orders)
        for key in ('requant', 'w_scale', 'a_scale_out'):
            if isinstance(n.get(key), list):
                n[key] = [n[key][i] for i in po]
    man = dict(tap_order_layers=sorted(taps, key=lambda c: int(c[4:])),
               tap_order_is_skew_order_288_32={k: v == want_order for k, v in taps.items()},
               layout_manifest_tap_orders_same=lm['tap_orders'] == taps,
               original_with_lists_in_output_order_plus_tap_order=stripped == expect,
               bytes_in_exporter_format=export_layout.manifest_bytes(raw1) + b'\n' == (l3/'manifest.json').read_bytes())
    ok &= (man['tap_order_layers'] == SKEWED and all(man['tap_order_is_skew_order_288_32'].values())
           and man['layout_manifest_tap_orders_same'] and man['original_with_lists_in_output_order_plus_tap_order']
           and man['bytes_in_exporter_format'])
    pm = l3/'permutation_manifest.json'
    others = dict(int_eval_json_identical_to_original=(l3/'int_eval.json').read_bytes() == (ORIGINAL/'int_eval.json').read_bytes(),
                  permutation_manifest_orders_are_perms_2=pm.is_file() and json.loads(pm.read_bytes()).get('orders') == orders,
                  files=sorted(p.name for p in l3.iterdir()))
    ok &= others['int_eval_json_identical_to_original'] and others['permutation_manifest_orders_are_perms_2']
    vs = prepare_l3.files_against_original(cse.lf_hashes(l3, skip=()))
    want_diff = sorted([f'conv{i}_config.bin' for i in range(1, 10)] + ['manifest.json'])
    vs['as_expected'] = (vs['differ_from_original'] == want_diff
                         and vs['same_as_original'] == ['conv10_config.bin', 'int_eval.json']
                         and vs['not_in_original'] == ['layout_manifest.json', 'permutation_manifest.json'])
    vs['layout_manifest_changed_files'] = lm['changed_files']
    vs['layout_manifest_unchanged_files'] = lm['unchanged_files']
    ok &= vs['as_expected']
    # fold.fold's intermediate, then the skew, as export_layout.py says it does
    folded = work/'folded'
    if folded.exists():
        shutil.rmtree(folded)
    fold.fold(ORIGINAL, orders, folded)
    _, layf = run_denoise.load_layers(folded)
    via = {}
    for L in layf:
        b = (folded/L['config']).read_bytes()
        if L['name'] in SKEWED:
            w = np.frombuffer(b, '<i4')
            k, c = L['K'], L['COUT']
            b = np.concatenate([w[:c*k].reshape(c, k)[:, skew_order(k, 32)].reshape(-1), w[c*k:]]).astype('<i4').tobytes()
        via[L['config']] = b == (l3/L['config']).read_bytes()
    mf = json.loads((folded/'manifest.json').read_bytes())
    fold_rec = dict(config_bins_equal=all(via.values()), differing=sorted(k for k, v in via.items() if not v),
                    manifest_equal_without_tap_order=mf == stripped,
                    permutation_manifest_identical=pm.is_file()
                    and (folded/'permutation_manifest.json').read_bytes() == pm.read_bytes())
    ok &= fold_rec['config_bins_equal'] and fold_rec['manifest_equal_without_tap_order'] and fold_rec['permutation_manifest_identical']
    return dict(layout=lm['layout'], layers_reordered=lm['layers_reordered'], changed_files=lm['changed_files'],
                config_bins=rows, manifest=man, other_files=others, files_against_original=vs,
                fold_then_skew=fold_rec, all_ok=bool(ok))


def command_line_export(work, l3):
    """The export as RUN_W4_L3.cmd writes it (relative --orders path, from the repository root)."""
    out = work/'exports'/'l3_cli'
    if out.exists():
        shutil.rmtree(out)
    cmd = [sys.executable, 'bankperm/export_layout.py', '--layout', 'skew', '--model', MODEL,
           '--orders', 'bankperm/perms_2.json', '--out', str(out)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    files = sorted(p.name for p in l3.iterdir())
    same = r.returncode == 0 and files == sorted(p.name for p in out.iterdir()) and all(
        (l3/n).read_bytes() == (out/n).read_bytes() for n in files)
    rerun = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    same_rerun = rerun.returncode == 0 and all((l3/n).read_bytes() == (out/n).read_bytes() for n in files)
    return dict(command=' '.join(['python'] + cmd[1:-1] + ['<out>']), exit_code=r.returncode,
                every_file_byte_identical_incl_layout_manifest=same, rerun_into_same_folder_exit_code=rerun.returncode,
                rerun_byte_identical=same_rerun, all_ok=bool(same and same_rerun))


# ----------------------------------------------------------------------------- emulation

def counts(L, x):
    return {f'w{w}': int(window_cycles(x, L['K'], L['COUT'], w).sum()) for w in (1, 2, 4)}


def emulation(l3, orders):
    r2 = json.loads(RESULTS_2.read_text(encoding='utf-8'))['networks'][LABEL]
    assert r2['model'] == MODEL
    i0, i3 = r2['layouts'].index('L0'), r2['layouts'].index('L3')
    man, _ = run_denoise.load_layers(ORIGINAL)
    ie = json.loads((ORIGINAL/'int_eval.json').read_text(encoding='utf-8'))
    rows = []
    for set_name, image in IMAGES:
        clean, q_in = cse.noisy(set_name, image, man['sigma'])
        out0, got0 = cse.emulate(ORIGINAL, q_in)
        out1, got1 = cse.emulate(l3, q_in)
        layers, tot = [], {'L0': {}, 'L3': {}}
        for (L0, x0, a0), (L1, x1, a1) in zip(got0, got1):
            assert L0['name'] == L1['name']
            po, cols = out_order(L0, orders), l3_columns(L0, orders)
            c0, c1 = counts(L0, x0), counts(L1, x1)
            for key, c in (('L0', c0), ('L3', c1)):
                for w, v in c.items():
                    tot[key][w] = tot[key].get(w, 0) + v
            layers.append(dict(
                name=L0['name'], taps_reordered=L1.get('tap_order') is not None,
                outputs_relabelled=not np.array_equal(po, np.arange(L0['COUT'])),
                windows_are_original_with_l3_columns=bool(np.array_equal(x1, x0[:, cols])),
                windows_differ_from_original=not np.array_equal(x1, x0),
                accumulators_equal_up_to_column_order=bool(np.array_equal(a1, a0[:, po])),
                accumulators_identical=bool(np.array_equal(a1, a0)),
                window_sha256=sha(np.ascontiguousarray(x1).tobytes()),
                original_window_sha256=sha(np.ascontiguousarray(x0).tobytes()),
                accumulator_sha256=sha(np.ascontiguousarray(a1).tobytes()), count_l0=c0, count_l3=c1))
        key = f'{set_name}/{image}'
        ref = r2['per_image_totals'][key]
        p0, p1 = cse.png_bytes(out0), cse.png_bytes(out1)
        ps = float(psnr(clean, out1.astype(np.float32)/255))
        row = dict(set=set_name, image=image, output_identical=bool(np.array_equal(out0, out1)), png_identical=p0 == p1,
                   png_sha256=sha(p1), psnr=ps, psnr_matches_int_eval=abs(ps - ie[set_name]['per_image'][image]) <= 1e-5,
                   layers=layers, totals=tot,
                   results_2_json={'L0': {w: ref[w][i0] for w in ('w1', 'w2', 'w4')},
                                   'L3': {w: ref[w][i3] for w in ('w1', 'w2', 'w4')}, 'key': key})
        row['l3_w4_total_equals_results_2'] = tot['L3']['w4'] == ref['w4'][i3]
        row['all_totals_equal_results_2'] = all(tot[k][w] == row['results_2_json'][k][w] for k in ('L0', 'L3')
                                                for w in ('w1', 'w2', 'w4'))
        row['all_ok'] = bool(
            row['output_identical'] and row['png_identical'] and row['psnr_matches_int_eval']
            and row['l3_w4_total_equals_results_2'] and row['all_totals_equal_results_2']
            and all(r['windows_are_original_with_l3_columns'] and r['accumulators_equal_up_to_column_order']
                    and r['taps_reordered'] == (r['name'] in SKEWED)
                    and r['windows_differ_from_original'] == (r['name'] in SKEWED)
                    and r['outputs_relabelled'] == (r['name'] in orders)
                    and r['accumulators_identical'] == (r['name'] not in orders) for r in layers))
        rows.append(row)
        del got0, got1
    return rows


def cli(work, l3):
    rows = []
    for set_name, image in IMAGES:
        stem = Path(image).stem
        common = ['--emulate', '--set', set_name, '--images', image]
        rc0, o0, _ = cse.driver('new', common, work, f'cli_original_{stem}')
        rc1, o1, _ = cse.driver('new', common + ['--export-dir', str(l3)], work, f'cli_l3_{stem}')
        r0, r1 = cse.report(o0), cse.report(o1)
        same = marked = None
        if r0 and r1:
            marked = [L['name'] for L in r1['images'][0]['layers'] if L.get('taps_reordered')]
            a, b = cse.strip(r0), cse.strip(r1, ('taps_reordered',))
            a['export_dir'] = b['export_dir'] = None
            same = a == b
        pngs = sorted(p.name for p in o0.glob('*.png')) if rc0 == 0 else []
        row = dict(set=set_name, image=image, exit_codes=[rc0, rc1], pngs=pngs,
                   pngs_identical=bool(pngs) and rc1 == 0 and all((o0/n).read_bytes() == (o1/n).read_bytes() for n in pngs),
                   report_identical_but_export_dir_timing_marks=same, layers_marked_taps_reordered=marked)
        row['all_ok'] = bool(row['exit_codes'] == [0, 0] and row['pngs_identical'] and same and marked == SKEWED)
        rows.append(row)
    return rows


def board(work, l3, xsdb, emu):
    """The L3 export through the board path with the stand-in debugger, Set12 05.png."""
    e05 = next(r for r in emu if (r['set'], r['image']) == ('Set12', '05.png'))
    win = {r['name']: r['window_sha256'] for r in e05['layers']}
    win0 = {r['name']: r['original_window_sha256'] for r in e05['layers']}
    r = cse.board_run('new', l3, work, 'l3', xsdb)
    _, layers = run_denoise.load_layers(l3)
    rows = []
    for i, L in enumerate(layers):
        cfg, inp = r['streams'][i] if i < len(r['streams']) else (None, None)
        row = dict(name=L['name'], tap_order=L.get('tap_order') is not None)
        if cfg is None:
            row['streamed'] = False
        else:
            c, x = cfg.read_bytes(), inp.read_bytes()
            row.update(streamed=True, config_stream_is_l3_config=c == (l3/L['config']).read_bytes(),
                       config_stream_is_original_config=c == (ORIGINAL/L['config']).read_bytes(),
                       window_stream_is_emulated_l3_windows=sha(x) == win[L['name']],
                       window_stream_is_original_windows=sha(x) == win0[L['name']],
                       config_stream_sha256=sha(c), window_stream_sha256=sha(x))
        rows.append(row)
    rep = r['report']
    recs = rep['images'][0]['layers'] if rep else []
    png = r['out']/'05_denoised.png'
    res = dict(image='Set12 05.png', args=cse.BOARD_ARGS, exit_code=r['exit_code'], seconds=r['seconds'],
               runs=len(r['streams']), layers=rows, core_ids=sorted({c for L in recs for c in L['core_id']}),
               fclk_mhz=sorted({f for L in recs for f in L['fclk_mhz']}),
               layers_marked_taps_reordered=[L['name'] for L in recs if L.get('taps_reordered')],
               png_sha256=sha(png.read_bytes()) if png.is_file() else None)
    res['png_identical_to_emulation'] = res['png_sha256'] == e05['png_sha256']
    hidden = [x for x in rows if x['name'] in SKEWED]
    ends = [x for x in rows if x['name'] not in SKEWED]
    ok = (len(hidden) == 8 and all(x['streamed'] and x['tap_order'] and x['config_stream_is_l3_config']
                                   and not x['config_stream_is_original_config']
                                   and x['window_stream_is_emulated_l3_windows']
                                   and not x['window_stream_is_original_windows'] for x in hidden)
          and all(x['streamed'] and not x['tap_order'] and x['config_stream_is_l3_config']
                  and x['window_stream_is_emulated_l3_windows'] and x['window_stream_is_original_windows']
                  for x in ends))
    res['conv2_9_streams_are_l3'] = bool(ok)
    res['all_ok'] = bool(ok and r['exit_code'] == 0 and len(r['streams']) == 10 and res['png_identical_to_emulation']
                         and res['layers_marked_taps_reordered'] == SKEWED)
    res['note'] = ('stand-in core (scripts/_fake_xsdb_inner.tcl, fault "wide": ID 0x4d410302) copies gold into the '
                   'results and reports fixed cycles, so mismatches and cycles here say nothing about hardware; the '
                   'streams are the bytes its DMA was asked to send from the fake DDR the driver loaded. conv1 '
                   '(outputs relabelled) streams the L3 weights and the image windows; conv10 the original\'s')
    return res


# ----------------------------------------------------------------------------- unchanged

def allowed_change(path):
    return (path in L3_PATHS or any(path.startswith(d) for d in RESULT_DIRS + DOC_DIRS)
            or (path.endswith('.md') and not Path(path).name.startswith('PROTOCOL_2')))


def whole_tree_since_ref():
    """git diff --name-only PROTOCOL_2_REF over the whole working tree: every path must be an allowed one."""
    rc, out, err = git('diff', '--name-only', PROTOCOL_2_REF)
    names = out.decode().splitlines() if not rc else []
    rc2, out2, _ = git('ls-files', '--others', '--exclude-standard')
    untracked = out2.decode().splitlines() if not rc2 else []
    bad = sorted(n for n in names if not allowed_change(n))
    return dict(command=f'git diff --name-only {PROTOCOL_2_REF}', exit_code=rc, error=err or None, changed=names,
                not_allowed=bad, untracked=untracked, untracked_not_allowed=sorted(n for n in untracked if not allowed_change(n)),
                allowed=dict(l3_files=L3_PATHS, result_dirs=RESULT_DIRS, doc_dirs=DOC_DIRS,
                             docs='*.md other than PROTOCOL_2*.md'),
                all_ok=rc == 0 and not bad)


def protocol_2_unchanged(work):
    rows = {}
    for name in PROTOCOL_2_FILES:
        p = ROOT/name
        text = Path(name).suffix in prepare_l3.prepare_layouts.TEXT or Path(name).suffix in ('.py', '.cmd', '.tcl')
        norm = (lambda b: b.replace(b'\r\n', b'\n')) if text else (lambda b: b)
        here = norm(p.read_bytes()) if p.is_file() else None
        rc, blob, _ = git('show', f'HEAD:{name}')
        rc0, blob0, _ = git('show', f'{PROTOCOL_2_REF}:{name}')
        rows[name] = dict(committed=rc == 0, working_tree_is_head=rc == 0 and here == norm(blob),
                          same_as_addendum_commit=rc0 == 0 and here == norm(blob0))
    rc, _, _ = git('diff', '--quiet', PROTOCOL_2_REF, '--', *PROTOCOL_2_FILES)
    skew = work/'exports'/'skew'
    if skew.exists():
        shutil.rmtree(skew)
    export_layout.write_layout(ORIGINAL, skew, 'skew')
    rec = json.loads((HERE/'skew_export_check.json').read_text(encoding='utf-8'))['export_files_lf_sha256']
    now = cse.lf_hashes(skew)
    res = dict(ref=PROTOCOL_2_REF, files=rows, git_diff_quiet_since_ref=rc == 0,
               whole_tree_since_ref=whole_tree_since_ref(),
               skew_export_written_now_has_the_hashes_of_skew_export_check_json=now == rec['skew'],
               original_export_has_the_hashes_of_skew_export_check_json=cse.lf_hashes(ORIGINAL) == rec['original'])
    res['all_ok'] = bool(all(r['committed'] and r['working_tree_is_head'] and r['same_as_addendum_commit']
                             for r in rows.values()) and res['git_diff_quiet_since_ref']
                         and res['whole_tree_since_ref']['all_ok']
                         and res['skew_export_written_now_has_the_hashes_of_skew_export_check_json']
                         and res['original_export_has_the_hashes_of_skew_export_check_json'])
    return res


def imports():
    """The repository modules the L3 and the PROTOCOL_2 steps import must all be in the lists checked here."""
    def trace(mods):
        r = subprocess.run([sys.executable, '-c', TRACE, str(ROOT), ','.join(mods)], capture_output=True, text=True,
                           cwd=str(ROOT))
        return (json.loads(r.stdout) if r.returncode == 0 else None), r.returncode
    l3, rc1 = trace(L3_MODULES)
    p2, rc2 = trace(PROTOCOL_2_MODULES)
    covered_l3 = set(prepare_l3.TOOLS) | set(prepare_l3.CODE)
    res = dict(l3_modules=L3_MODULES, l3_imports=l3, l3_not_in_tools=None if l3 is None else sorted(set(l3) - covered_l3),
               protocol_2_modules=PROTOCOL_2_MODULES, protocol_2_imports=p2,
               protocol_2_not_in_unchanged_list=None if p2 is None else sorted(set(p2) - set(PROTOCOL_2_FILES)),
               exit_codes=[rc1, rc2])
    res['all_ok'] = bool(l3 is not None and p2 is not None and not res['l3_not_in_tools']
                         and not res['protocol_2_not_in_unchanged_list'])
    return res


def build_checks():
    rc, text, _ = cse.run([sys.executable, '-m', 'py_compile'] + NEW_FILES)
    return dict(py_compile=dict(files=NEW_FILES, exit_code=rc, output=text.strip()), all_ok=rc == 0)


def run_script():
    """RUN_W4_L3.cmd: LF line ends, ASCII, and the export and board-run lines this check is for."""
    data = RUN_SCRIPT.read_bytes()
    text = data.decode('ascii', errors='replace')
    flags = ' '.join(cse.BOARD_ARGS).replace('--images 05.png', '--images %%b')
    want = {
        'export': r'python bankperm\export_layout.py --layout skew --model %MODEL% --orders bankperm\perms_2.json '
                  r'--out %L3EXP%',
        'export_folder': r'set "L3EXP=build\layout_exports\l3"',
        'runs_folder': r'set "RUNS=denoise\board_runs\q1_layouts3"',
        'model': f'set "MODEL={MODEL}"',
        'verify': r'python bankperm\prepare_l3.py --verify %L3EXP% --require-check',
        'pin': (r'python bankperm\prepare_l3.py --bitstream "%W4BUILD%" --export %L3EXP% --record %RUNS%\setup.json '
                r'%ALLOWBIT% %ALLOWQ2%'),
        'override_arguments': 'for %%a in (%2 %3) do if not "%%~a"=="" (',
        'choice_carries_on_only_on_y': ') else if not errorlevel 1 (',
        'board_run': (r'python scripts\run_denoise.py --model %MODEL% --export-dir %L3EXP% --xsdb "%XSDB%" '
                      r'--build "%W4BUILD%" ' + flags + r' --out "!OUT!" --board-dir "build\q1_layouts3_io\l3_%%~nb"'),
        'images': 'for %%b in (05.png 06.png 07.png 08.png) do',
    }
    code = '\n'.join(l for l in text.splitlines() if not l.lstrip().lower().startswith('rem'))
    res = dict(file=rel(RUN_SCRIPT), lf_sha256=sha(data), no_cr=b'\r' not in data, ascii=data.isascii(),
               lines_present={k: v in text for k, v in want.items()},
               touches_no_protocol_2_folder=not any(s in code for s in (
                   'q1_layouts2', 'layout_exports\\skew', 'layout_exports\\frozen', 'layout_exports\\multistart',
                   'compare_board_2', 'prepare_layouts', 'board_prediction_2')))
    res['all_ok'] = bool(res['no_cr'] and res['ascii'] and all(res['lines_present'].values())
                         and res['touches_no_protocol_2_folder'])
    return res


def prediction_3(l3):
    """Information only: whether bankperm/board_prediction_3.json (if there) was made with this export's config.bin."""
    p = HERE/'board_prediction_3.json'
    if not p.is_file():
        return dict(present=False)
    pred = json.loads(p.read_text(encoding='utf-8'))
    man = json.loads((l3/'manifest.json').read_bytes())
    runs = (pred.get('runs') or {}).get('l3') or {}
    same = {im: [L.get('config_sha256') for L in (runs.get(im) or {}).get('layers', [])]
            == [sha((l3/n['config']).read_bytes()) for n in man['layers']] for im in ('05.png', '06.png', '07.png', '08.png')}
    return dict(present=True, file=rel(p), **prepare_l3.text_record(p), config_sha256_equal_to_this_export=same,
                note='not part of all_ok: bankperm/prepare_l3.py --bitstream checks it on the board PC before the runs')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=prepare_l3.CHECK)
    ap.add_argument('--work', type=Path, help='keep the exports and runs here (default: a temporary directory)')
    ap.add_argument('--no-board', action='store_true', help='skip the stand-in debugger run')
    args = ap.parse_args()
    t0 = time.time()
    tmp = None if args.work else tempfile.TemporaryDirectory()
    work = (args.work or Path(tmp.name)).resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work/'runs').mkdir(exist_ok=True)
    exports = work/'exports'
    if exports.exists():
        shutil.rmtree(exports)
    orders = export_layout.read_orders(PERMS_2, MODEL)
    l3 = exports/'l3'
    lm = export_layout.write_layout(ORIGINAL, l3, 'skew', orders, PERMS_2)
    res = dict(model=MODEL, network=LABEL, what=__doc__.split('\n')[0],
               export_command=('python bankperm/export_layout.py --layout skew --model dn_d10_c32_us_fx_qat '
                               '--orders bankperm/perms_2.json --out build/layout_exports/l3'),
               layout_manifest={k: lm[k] for k in ('layout', 'rule', 'tap_order_semantics', 'layers_reordered',
                                                   'changed_files', 'unchanged_files', 'files')})
    res['layout_manifest']['relabeling_source'] = lm['relabeling']['source']
    print('inputs', flush=True)
    res['inputs'] = check_inputs(orders)
    print('export', flush=True)
    res['export'] = check_export(l3, lm, orders, work)
    res['command_line_export'] = command_line_export(work, l3)
    print('emulation', flush=True)
    res['emulation'] = emulation(l3, orders)
    print('command line', flush=True)
    res['cli'] = cli(work, l3)
    xsdb = None if args.no_board else cse.fake_xsdb(work)
    if xsdb:
        print('board path (stand-in debugger)', flush=True)
        res['board'] = board(work, l3, xsdb, res['emulation'])
    else:
        res['board'] = dict(ran=False, why='--no-board' if args.no_board else 'no tclsh on this machine')
    print('unchanged PROTOCOL_2 files', flush=True)
    res['protocol_2_unchanged'] = protocol_2_unchanged(work)
    res['imports'] = imports()
    res['build'] = build_checks()
    res['run_script'] = run_script()
    res['prediction_3'] = prediction_3(l3)
    res['export_files_lf_sha256'] = dict(original=cse.lf_hashes(ORIGINAL), l3=cse.lf_hashes(l3))
    res['export_files_portable_sha256'] = dict(
        rule=prepare_l3.PORTABLE_RULE, original={p.name: prepare_l3.portable_sha(p) for p in sorted(ORIGINAL.iterdir()) if p.is_file()},
        l3={p.name: prepare_l3.portable_sha(p) for p in sorted(l3.iterdir()) if p.is_file() and p.name != 'layout_manifest.json'})
    res['driver_code_lf_sha256'] = {n: prepare_l3.code_sha(ROOT/n) for n in prepare_l3.CODE}
    res['tool_code_lf_sha256'] = prepare_l3.tool_hashes()      # prepare_l3.py --verify / --bitstream require these
    portable_same = all(res['export_files_portable_sha256'][k] == res['export_files_lf_sha256'][k] for k in ('original', 'l3'))
    parts = dict(inputs=res['inputs']['all_ok'], export=res['export']['all_ok'],
                 command_line_export=res['command_line_export']['all_ok'],
                 emulation=all(r['all_ok'] for r in res['emulation']), cli=all(r['all_ok'] for r in res['cli']),
                 protocol_2_unchanged=res['protocol_2_unchanged']['all_ok'], imports=res['imports']['all_ok'],
                 build=res['build']['all_ok'], tool_hashes_complete=None not in res['tool_code_lf_sha256'].values(),
                 run_script=res['run_script']['all_ok'],
                 portable_hashes_equal_lf_hashes_here=portable_same)
    if xsdb:
        parts['board_l3'] = res['board']['all_ok']
    res['parts_ok'] = parts
    res['all_ok'] = all(parts.values())
    res['not_checked'] = [] if xsdb else ['board path (stand-in debugger)']
    res['seconds'] = round(time.time() - t0, 1)
    args.out.write_bytes((json.dumps(res, indent=1) + '\n').encode('utf-8'))
    for k, v in parts.items():
        print(f'  {k:<36} {"ok" if v else "FAILED"}')
    print(f'all ok: {res["all_ok"]}   ({res["seconds"]} s) -> {rel(args.out)}')
    if tmp:
        tmp.cleanup()
    return 0 if res['all_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
