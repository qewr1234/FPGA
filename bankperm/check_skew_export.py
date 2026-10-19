"""Check the skewed layout's host path: the export, the driver, the board files, and the unchanged paths.

    python bankperm/check_skew_export.py              # writes bankperm/skew_export_check.json (about 5 minutes)
    python bankperm/check_skew_export.py --no-board   # without the stand-in debugger runs (they need tclsh)

The skew export is bankperm/export_layout.py's (--layout skew) of
dn_d10_c32_us_fx_qat, the board network of PROTOCOL_2.md; scripts/run_denoise.py
puts a layer's window columns in its 'tap_order'. What is checked, all of it on the
host (nothing here touches a board):

  export      the skewed layers' config.bin are the original's INT32 words with the
              weight columns in skew_count.skew_order, bias unchanged; every other
              file is byte for byte the original's; manifest.json is the original
              plus 'tap_order' and nothing else (with the entries taken out it
              re-serializes to the original's bytes)
  (a)         the original and the skew export emulated (run_denoise.denoise, the
  emulation   driver's own host path) on Set12 05.png and BSD68 test001.png: the
              denoised images identical (array and PNG bytes), every layer's INT32
              accumulators identical (the skew permutes taps, not outputs), every
              skewed layer's windows the original's with the columns in the skew
              order and every other layer's identical; per layer the W = 1, 2, 4
              window counts (denoise/predict_w4.window_cycles) and the line-buffer
              count, equal to skew_count.counts on the same windows, and summed equal
              to bankperm/skew_count.json's numbers for that image. Then the same two
              runs through the command line (run_denoise.py --emulate [--export-dir]):
              PNGs identical, report.json identical but for export_dir, host_seconds
              and the taps_reordered marks on conv2..conv9.
  (b) board   scripts/run_denoise.py on the board path (--w4 --mode 1 --fclk 50
  path        --tile 65536) with xsdb replaced by scripts/_fake_xsdb_inner.tcl (the
              stand-in debugger of scripts/test_run_board_xsdb.tcl, with a four-wide
              core), the whole network on Set12 05.png for the original and the skew
              export. The stand-in records the bytes its DMA streams to the core: per
              layer the configuration stream must be the layer's config.bin of that
              export (the skewed weights on conv2..conv9, which are not the
              original's) and the window stream the emulated windows of (a) (the
              skewed columns on conv2..conv9). The stand-in core copies gold into the
              results, so its mismatch count and cycles say nothing; what it checks
              is what the driver writes and sends. Also scripts/test_run_board_xsdb.tcl
              itself (after scripts/export_board_data.py --frames 512).
  (c)         run_denoise.py as it was before the tap order (git show
  unchanged   --before-ref:scripts/run_denoise.py, run with __file__ at the real
              path; scripts/run_cifar.py must be unchanged since) against the
              current one, without a tap order: --emulate on the original (05.png,
              test001.png), Frozen and Multi-start (05.png) exports, and the
              stand-in board run of each on 05.png: report.json identical but for
              host_seconds and wall_seconds, PNGs identical, every streamed byte
              identical.
  L3          --orders: the Frozen relabeling folded first, then the skew; the
              emulated output identical to the original's.
  guards      bankperm/fold.fold refuses an export that has a tap order (it assumes
              the (ky, kx, channel) order), and export_layout --orders refuses a
              source export outside the repository with a message, not a traceback.
  build       python -m py_compile on every file of this change, and the q1
              unittests (python -m unittest discover -s scripts -p 'test_q1_*.py').

export_files_lf_sha256 records the hash of every export file (text files with CRLF
read as LF), which bankperm/prepare_layouts.py --verify compares on the board PC.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import export_layout  # noqa: E402
import prepare_layouts  # noqa: E402
import run_denoise  # noqa: E402
import skew_count  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from predict_w4 import window_cycles  # noqa: E402

MODEL = 'dn_d10_c32_us_fx_qat'
ORIGINAL = ROOT/'denoise'/'export'/MODEL
IMAGES = [('Set12', '05.png'), ('BSD68', 'test001.png')]
BEFORE_REF = 'ad9e671'           # HEAD before the tap order was added to scripts/run_denoise.py
CHANGED = ['scripts/run_denoise.py', 'bankperm/export_layout.py', 'bankperm/prepare_layouts.py',
           'bankperm/compare_board_2.py', 'bankperm/check_skew_export.py', 'bankperm/fold.py',
           'bankperm/predict_board_2.py']
BOARD_ARGS = ['--w4', '--mode', '1', '--fclk', '50', '--set', 'Set12', '--images', '05.png', '--tile', '65536']
VOLATILE = ('host_seconds', 'wall_seconds')
ENTRY_TCL = r'''# Records the streams the stand-in DMA sends to the core, then runs the driver's wrapper.
rename dma_run_mm2s _check_dma_run_mm2s
proc dma_run_mm2s {bytes} {
    global CFG_MODE ARMED D
    set kind [expr {$CFG_MODE ? "cfg" : ($ARMED ? "in" : "")}]
    if {$kind ne "" && [info exists ::env(WM_CAPTURE_DIR)]} {
        set dir $::env(WM_CAPTURE_DIR)
        set n [llength [glob -nocomplain -directory $dir *_$kind.bin]]
        set fh [open [file join $dir [format %02d_%s.bin $n $kind]] w]
        fconfigure $fh -translation binary
        set a [expr {$D(mm2s_sa) & 0xffffffff}]
        set words [expr {$bytes / 4}]
        for {set i 0} {$i < $words} {incr i 65536} {
            set vals {}
            set e [expr {min($words, $i + 65536)}]
            for {set j $i} {$j < $e} {incr j} { lappend vals [memrd [expr {$a + $j * 4}]] }
            puts -nonewline $fh [binary format i* $vals]
        }
        close $fh
    }
    _check_dma_run_mm2s $bytes
}
source $::env(WM_WRAPPER)
'''
OLD_RUNNER = '''import sys
src, real = sys.argv[1], sys.argv[2]
sys.argv = [real] + sys.argv[3:]
g = {'__name__': '__main__', '__file__': real}
exec(compile(open(src, encoding='utf-8').read(), real, 'exec'), g)
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rel(p):
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


def png_bytes(out):
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format='PNG')
    return buf.getvalue()


def noisy(set_name, image, sigma):
    name, clean, nz = next(t for t in test_noise(load_set(set_name), sigma, seed=0) if t[0] == image)
    return clean, np.rint(nz*QMAX_A).astype(np.uint8)


def emulate(export, q_in):
    """run_denoise.denoise in emulation; -> (output, [(L, windows, accumulators)])."""
    man, layers = run_denoise.load_layers(export)
    got = []
    real = run_denoise.run_layer

    def capture(L, x, args, tag):
        acc, info = real(L, x, args, tag)
        got.append((L, x, acc))
        return acc, info

    run_denoise.run_layer = capture
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out, _ = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'chk')
    finally:
        run_denoise.run_layer = real
    return out, got


def layer_counts(L, x):
    k, cout = L['K'], L['COUT']
    c = {f'w{w}': int(window_cycles(x, k, cout, w).sum()) for w in (1, 2, 4)}
    sc = skew_count.counts(L, x)
    c['line_buffer'] = sc['line_buffer']
    c['same_as_skew_count_counts'] = all(c[s] == sc[s] for s in skew_count.STRUCTS)
    return c


def check_export(skew, lm):
    """The skew export against the original, file by file."""
    _, layers = run_denoise.load_layers(ORIGINAL)
    rows, ok = {}, True
    for L in layers:
        o = lm['tap_orders'].get(L['name'])
        a = (ORIGINAL/L['config']).read_bytes()
        b = (skew/L['config']).read_bytes()
        if o is None:
            same = a == b
            rows[L['config']] = dict(skewed=False, byte_identical=same)
            ok &= same
            continue
        k, cout = L['K'], L['COUT']
        c = k // (L['kh']*L['kw'])
        wa = np.frombuffer(a, '<i4')
        want = np.concatenate([wa[:cout*k].reshape(cout, k)[:, skew_count.skew_order(k, c)].reshape(-1), wa[cout*k:]])
        r = dict(skewed=True, tap_order_is_skew_order=o == [int(v) for v in skew_count.skew_order(k, c)],
                 columns_permuted_bias_same=want.astype('<i4').tobytes() == b, differs_from_original=a != b,
                 banks_of_each_channel=sorted({tuple(np.bincount([(o.index(s*c + p)) % 4 for s in range(9)],
                                                                 minlength=4)) for p in range(c)}))
        r['banks_of_each_channel'] = [list(map(int, t)) for t in r['banks_of_each_channel']]
        rows[L['config']] = r
        ok &= r['tap_order_is_skew_order'] and r['columns_permuted_bias_same'] and r['differs_from_original']
    raw0 = (ORIGINAL/'manifest.json').read_bytes()
    m0, m1 = json.loads(raw0), json.loads((skew/'manifest.json').read_bytes())
    for node in m1['layers']:
        node.pop('tap_order', None)
    man = dict(content_equal_without_tap_order=m0 == m1,
               bytes_equal_without_tap_order=export_layout.manifest_bytes(m1) == raw0.replace(b'\r\n', b'\n'),
               layers_with_tap_order=lm['layers_reordered'])
    others = {n: (ORIGINAL/n).read_bytes() == (skew/n).read_bytes()
              for n in lm['unchanged_files'] if not n.endswith('_config.bin')}
    ok &= man['content_equal_without_tap_order'] and man['bytes_equal_without_tap_order'] and all(others.values())
    return dict(config_bins=rows, manifest=man, other_files_byte_identical=others, all_ok=bool(ok))


def emulation(skew):
    counts_ref = json.loads((HERE/'skew_count.json').read_text())['networks']['B-32 ReLU + QAT s1']
    assert counts_ref['model'] == MODEL
    man, _ = run_denoise.load_layers(ORIGINAL)
    ie = json.loads((ORIGINAL/'int_eval.json').read_text())
    rows = []
    for set_name, image in IMAGES:
        clean, q_in = noisy(set_name, image, man['sigma'])
        out0, got0 = emulate(ORIGINAL, q_in)
        out1, got1 = emulate(skew, q_in)
        layers, tot = [], {'original': {}, 'skew': {}}
        for (L0, x0, a0), (L1, x1, a1) in zip(got0, got1):
            assert L0['name'] == L1['name']
            o = L1.get('tap_order')
            c0, c1 = layer_counts(L0, x0), layer_counts(L1, x1)
            for key, c in (('original', c0), ('skew', c1)):
                for s in skew_count.STRUCTS:
                    tot[key][s] = tot[key].get(s, 0) + c[s]
            layers.append(dict(
                name=L0['name'], skewed=o is not None,
                windows_as_expected=bool(np.array_equal(x1, x0[:, o] if o is not None else x0)),
                windows_differ=None if o is None else not np.array_equal(x1, x0),
                accumulators_identical=bool(np.array_equal(a0, a1)), accumulator_sha256=sha(a1.tobytes()),
                window_sha256=sha(np.ascontiguousarray(x1).tobytes()), count_original=c0, count_skew=c1))
        ref = counts_ref['images'][f'{set_name} {image}']
        p0, p1 = png_bytes(out0), png_bytes(out1)
        ps = float(psnr(clean, out1.astype(np.float32)/255))
        rows.append(dict(
            set=set_name, image=image, output_identical=bool(np.array_equal(out0, out1)), png_identical=p0 == p1,
            png_sha256=sha(p1), psnr=ps, psnr_matches_int_eval=abs(ps - ie[set_name]['per_image'][image]) <= 1e-5,
            layers=layers, totals=tot,
            skew_count_json={k: {s: ref[k][s] for s in skew_count.STRUCTS} for k in ('conventional', 'skewed')},
            totals_equal_skew_count_json=all(tot['original'][s] == ref['conventional'][s] and
                                             tot['skew'][s] == ref['skewed'][s] for s in skew_count.STRUCTS)))
        rows[-1]['all_ok'] = bool(rows[-1]['output_identical'] and rows[-1]['png_identical']
                                  and rows[-1]['psnr_matches_int_eval'] and rows[-1]['totals_equal_skew_count_json']
                                  and all(r['windows_as_expected'] and r['accumulators_identical']
                                          and r['count_original']['same_as_skew_count_counts']
                                          and r['count_skew']['same_as_skew_count_counts']
                                          and r['windows_differ'] in (None, True) for r in layers))
        del got0, got1
    return rows


def strip(rep, extra=()):
    """report.json without the timing fields (and `extra` per-layer keys)."""
    rep = json.loads(json.dumps(rep))
    for im in rep.get('images', []):
        for L in im.get('layers', []):
            for k in VOLATILE + tuple(extra):
                L.pop(k, None)
    return rep


def run(cmd, env=None, log=None):
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if log:
        Path(log).write_text(r.stdout, encoding='utf-8')
    return r.returncode, r.stdout, round(time.time() - t0, 1)


def driver(code, args, work, tag, env=None):
    """scripts/run_denoise.py (code 'new') or the --before-ref one ('old') with args; -> (rc, out dir)."""
    out = work/'runs'/tag
    if out.exists():
        shutil.rmtree(out)
    if code == 'new':
        cmd = [sys.executable, str(ROOT/'scripts'/'run_denoise.py')]
    else:
        cmd = [sys.executable, str(work/'old_runner.py'), str(work/'run_denoise_before.py'),
               str(ROOT/'scripts'/'run_denoise.py')]
    rc, text, secs = run(cmd + ['--model', MODEL] + args + ['--out', str(out)], env, work/'runs'/f'{tag}.log')
    return rc, out, secs


def report(out):
    p = out/'report.json'
    return json.loads(p.read_text()) if p.is_file() else None


def cli(work, skew):
    rows = []
    for set_name, image in IMAGES:
        stem = Path(image).stem
        common = ['--emulate', '--set', set_name, '--images', image]
        rc0, o0, _ = driver('new', common, work, f'cli_original_{stem}')
        rc1, o1, _ = driver('new', common + ['--export-dir', str(skew)], work, f'cli_skew_{stem}')
        r0, r1 = report(o0), report(o1)
        same = marked = None
        if r0 and r1:
            marked = [L['name'] for L in r1['images'][0]['layers'] if L.get('taps_reordered')]
            a, b = strip(r0), strip(r1, ('taps_reordered',))
            a['export_dir'] = b['export_dir'] = None
            same = a == b
        rows.append(dict(set=set_name, image=image, exit_codes=[rc0, rc1],
                         png_identical=(o0/f'{stem}_denoised.png').read_bytes() == (o1/f'{stem}_denoised.png').read_bytes()
                         if rc0 == 0 and rc1 == 0 else False,
                         report_identical_but_export_dir_timing_marks=same,
                         layers_marked_taps_reordered=marked))
        rows[-1]['all_ok'] = bool(rows[-1]['exit_codes'] == [0, 0] and rows[-1]['png_identical'] and same
                                  and marked == [f'conv{i}' for i in range(2, 10)])
    return rows


def fake_xsdb(work):
    if not shutil.which('tclsh') or os.name == 'nt':
        return None
    d = work/'fake'
    (d/'repo').mkdir(parents=True, exist_ok=True)
    (d/'entry.tcl').write_text(ENTRY_TCL)
    sh = d/'xsdb.sh'
    sh.write_text('#!/bin/sh\n# Stand-in for xsdb: the repo\'s fake debugger with a four-wide core (ID bit 9).\n'
                  f'WM_WRAPPER="$1" exec tclsh "{ROOT/"scripts"/"_fake_xsdb_inner.tcl"}" "{d/"repo"}" 0 wide '
                  f'"{d/"entry.tcl"}"\n')
    sh.chmod(0o755)
    return sh


def board_run(code, export, work, tag, xsdb):
    cap = work/'capture'/tag
    if cap.exists():
        shutil.rmtree(cap)
    cap.mkdir(parents=True)
    env = dict(os.environ, WM_CAPTURE_DIR=str(cap))
    args = (['--export-dir', str(export)] if export else []) + ['--xsdb', str(xsdb)] + BOARD_ARGS + [
        '--board-dir', str(work/'io'/tag)]
    rc, out, secs = driver(code, args, work, f'board_{tag}', env)
    streams = [(cap/f'{i:02d}_cfg.bin', cap/f'{i:02d}_in.bin') for i in range(len(list(cap.glob('*_cfg.bin'))))]
    return dict(exit_code=rc, seconds=secs, report=report(out), out=out, streams=streams)


def board(work, skew, xsdb, emu):
    """(b): the original and the skew export through the board path with the stand-in debugger."""
    win = {r['name']: r['window_sha256'] for r in emu[0]['layers']}     # skew windows of Set12 05.png
    _, base_layers = run_denoise.load_layers(ORIGINAL)
    clean, q_in = noisy('Set12', '05.png', 25)
    _, got0 = emulate(ORIGINAL, q_in)
    win0 = {L['name']: sha(np.ascontiguousarray(x).tobytes()) for L, x, _ in got0}
    del got0
    png0 = png_bytes(emulate(ORIGINAL, q_in)[0])
    res = {}
    for tag, export, wins in (('original', None, win0), ('skew', skew, win)):
        r = board_run('new', export, work, f'new_{tag}', xsdb)
        exp = export or ORIGINAL
        _, layers = run_denoise.load_layers(exp)
        rows = []
        for i, L in enumerate(layers):
            cfg, inp = r['streams'][i] if i < len(r['streams']) else (None, None)
            row = dict(name=L['name'], tap_order=L.get('tap_order') is not None)
            if cfg is None:
                row['streamed'] = False
            else:
                c, x = cfg.read_bytes(), inp.read_bytes()
                row.update(streamed=True, config_stream_is_export_config=c == (exp/L['config']).read_bytes(),
                           config_stream_is_original_config=c == (ORIGINAL/base_layers[i]['config']).read_bytes(),
                           window_stream_is_emulated_windows=sha(x) == wins[L['name']],
                           window_stream_is_original_windows=sha(x) == win0[L['name']],
                           config_stream_sha256=sha(c), window_stream_sha256=sha(x))
            rows.append(row)
        rep = r['report']
        recs = rep['images'][0]['layers'] if rep else []
        res[tag] = dict(exit_code=r['exit_code'], seconds=r['seconds'], runs=len(r['streams']), layers=rows,
                        core_ids=sorted({c for L in recs for c in L['core_id']}),
                        fclk_mhz=sorted({f for L in recs for f in L['fclk_mhz']}),
                        layers_marked_taps_reordered=[L['name'] for L in recs if L.get('taps_reordered')],
                        png_identical_to_emulation=(r['out']/'05_denoised.png').is_file() and
                        (r['out']/'05_denoised.png').read_bytes() == png0)
        skewed = [x for x in rows if x['tap_order']]
        if tag == 'skew':
            ok = (len(skewed) == 8 and all(x['streamed'] and x['config_stream_is_export_config']
                                           and not x['config_stream_is_original_config']
                                           and x['window_stream_is_emulated_windows']
                                           and not x['window_stream_is_original_windows'] for x in skewed)
                  and all(x['streamed'] and x['config_stream_is_original_config']
                          and x['window_stream_is_original_windows'] for x in rows if not x['tap_order'])
                  and res[tag]['layers_marked_taps_reordered'] == [f'conv{i}' for i in range(2, 10)])
        else:
            ok = all(x['streamed'] and x['config_stream_is_original_config'] and x['window_stream_is_original_windows']
                     for x in rows) and not res[tag]['layers_marked_taps_reordered']
        res[tag]['all_ok'] = bool(ok and r['exit_code'] == 0 and len(r['streams']) == 10
                                  and res[tag]['png_identical_to_emulation'])
    res['note'] = ('stand-in core (scripts/_fake_xsdb_inner.tcl, fault "wide": ID 0x4d410302) copies gold into the '
                   'results and reports fixed cycles, so mismatches and cycles here say nothing about hardware; the '
                   'streams are the bytes its DMA was asked to send from the fake DDR the driver loaded')
    return res


def tcl_selftest(work):
    if not shutil.which('tclsh'):
        return dict(ran=False, why='no tclsh')
    rc0, t0, s0 = run([sys.executable, 'scripts/export_board_data.py', '--frames', '512'], log=work/'export_board_data.log')
    rc1, t1, s1 = run(['tclsh', 'scripts/test_run_board_xsdb.tcl'], log=work/'test_run_board_xsdb.log')
    lines = t1.splitlines()
    return dict(ran=True, export_board_data_exit=rc0, exit_code=rc1, seconds=s0 + s1,
                ok_cases=sum(l.strip().startswith('ok') for l in lines),
                failed_cases=[l.strip() for l in lines if l.strip().startswith('FAIL')],
                last_line=lines[-1] if lines else '', all_ok=rc0 == 0 and rc1 == 0)


def unchanged(work, xsdb, ref):
    """(c): the run_denoise.py of --before-ref against the current one, without a tap order."""
    src = subprocess.run(['git', 'show', f'{ref}:scripts/run_denoise.py'], cwd=str(ROOT), capture_output=True)
    cif = subprocess.run(['git', 'show', f'{ref}:scripts/run_cifar.py'], cwd=str(ROOT), capture_output=True)
    if src.returncode or cif.returncode:
        return dict(ran=False, why=f'git show {ref} failed: {src.stderr.decode()[:200]}')
    (work/'run_denoise_before.py').write_bytes(src.stdout)
    (work/'old_runner.py').write_text(OLD_RUNNER)
    res = dict(ref=ref, before_sha256=sha(src.stdout),
               run_cifar_unchanged_since_ref=cif.stdout == (ROOT/'scripts'/'run_cifar.py').read_bytes(), emulate=[],
               board=[])
    zips = work/'exports'
    targets = [('original', None, 'Set12', '05.png'), ('original', None, 'BSD68', 'test001.png'),
               ('frozen', zips/'frozen', 'Set12', '05.png'), ('multistart', zips/'multistart', 'Set12', '05.png')]
    for name, export, set_name, image in targets:
        stem = Path(image).stem
        args = ['--emulate', '--set', set_name, '--images', image] + (['--export-dir', str(export)] if export else [])
        outs = {code: driver(code, args, work, f'c_{code}_{name}_{stem}') for code in ('old', 'new')}
        r = {code: report(o) for code, (_, o, _) in outs.items()}
        pngs = {code: {p.name: p.read_bytes() for p in sorted(o.glob('*.png'))} for code, (_, o, _) in outs.items()}
        row = dict(export=name, set=set_name, image=image, exit_codes=[outs['old'][0], outs['new'][0]],
                   report_identical_but_host_seconds=bool(r['old'] and r['new'] and strip(r['old']) == strip(r['new'])),
                   pngs_identical=bool(pngs['old']) and pngs['old'] == pngs['new'], pngs=sorted(pngs['new']))
        row['all_ok'] = row['exit_codes'] == [0, 0] and row['report_identical_but_host_seconds'] and row['pngs_identical']
        res['emulate'].append(row)
    if xsdb:
        for name, export, _, _ in [t for t in targets if t[3] == '05.png']:
            runs = {code: board_run(code, export, work, f'c_{code}_{name}', xsdb) for code in ('old', 'new')}
            st = {code: [(sha(c.read_bytes()), sha(i.read_bytes())) for c, i in r['streams']] for code, r in runs.items()}
            r = {code: runs[code]['report'] for code in runs}
            pngs = {code: {p.name: p.read_bytes() for p in sorted(runs[code]['out'].glob('*.png'))} for code in runs}
            row = dict(export=name, exit_codes=[runs['old']['exit_code'], runs['new']['exit_code']],
                       board_runs=[len(st['old']), len(st['new'])], streams_identical=st['old'] == st['new'],
                       report_identical_but_timing=bool(r['old'] and r['new'] and strip(r['old']) == strip(r['new'])),
                       pngs_identical=bool(pngs['old']) and pngs['old'] == pngs['new'])
            row['all_ok'] = (row['exit_codes'] == [0, 0] and row['board_runs'] == [10, 10] and row['streams_identical']
                             and row['report_identical_but_timing'] and row['pngs_identical'])
            res['board'].append(row)
    res['all_ok'] = bool(res['run_cifar_unchanged_since_ref'] and all(x['all_ok'] for x in res['emulate'] + res['board']))
    return res


def l3_smoke(work):
    """--orders: the Frozen relabeling folded, then skewed; the output must be the original's."""
    orders_path = work/'exports'/'frozen'/'permutation_manifest.json'
    orders = export_layout.read_orders(orders_path, MODEL)
    dest = work/'exports'/'l3_frozen_skew'
    lm = export_layout.write_layout(ORIGINAL, dest, 'skew', orders, orders_path)
    clean, q_in = noisy('Set12', '05.png', 25)
    out0, _ = emulate(ORIGINAL, q_in)
    out1, got = emulate(dest, q_in)
    return dict(layout=lm['layout'], layers_reordered=lm['layers_reordered'],
                output_identical=bool(np.array_equal(out0, out1)), all_ok=bool(np.array_equal(out0, out1)))


def guards(work, skew):
    """The refusals: fold.fold on a layout export; export_layout --orders on a source outside the repository."""
    import fold
    res = {}
    try:
        fold.fold(skew, {}, work/'guard_fold')
        res['fold_refuses_a_layout_export'] = False
    except SystemExit as e:
        res['fold_refuses_a_layout_export'] = 'tap order' in str(e)
    except Exception as e:                         # noqa: BLE001 (any other failure is not the refusal)
        res['fold_refuses_a_layout_export'] = False
        res['fold_error'] = repr(e)
    res['fold_wrote_nothing'] = not (work/'guard_fold').exists()
    try:
        work.relative_to(ROOT)
        res['outside_source'] = 'not checked: --work is inside the repository'
    except ValueError:
        src = work/'outside_src'
        if src.exists():
            shutil.rmtree(src)
        shutil.copytree(ORIGINAL, src)
        try:
            export_layout.write_layout(src, work/'guard_l3', 'skew', {'conv1': list(range(32))}, None)
            res['export_layout_orders_refuses_a_source_outside_the_repository'] = False
        except SystemExit as e:
            res['export_layout_orders_refuses_a_source_outside_the_repository'] = 'inside the repository' in str(e)
        except Exception as e:                     # noqa: BLE001
            res['export_layout_orders_refuses_a_source_outside_the_repository'] = False
            res['export_layout_error'] = repr(e)
        shutil.rmtree(src)
    res['all_ok'] = all(v is True for k, v in res.items() if not k.endswith(('_source', '_error')))
    res['all_ok'] = res['all_ok'] and not any(k.endswith('_error') for k in res)
    return res


def build_checks(work):
    rc, text, _ = run([sys.executable, '-m', 'py_compile'] + CHANGED)
    rc2, text2, secs = run([sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_q1_*.py'],
                           log=work/'unittests.log')
    ran = [l for l in text2.splitlines() if l.startswith('Ran ')]
    return dict(py_compile=dict(files=CHANGED, exit_code=rc, output=text.strip()),
                unittests=dict(exit_code=rc2, ran=ran[-1] if ran else None, last_line=text2.strip().splitlines()[-1]),
                all_ok=rc == 0 and rc2 == 0)


def lf_hashes(d, skip=('layout_manifest.json',)):
    return {p.name: prepare_layouts.lf_sha(p) for p in sorted(Path(d).iterdir()) if p.is_file() and p.name not in skip}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=HERE/'skew_export_check.json')
    ap.add_argument('--work', type=Path, help='keep the exports and runs here (default: a temporary directory)')
    ap.add_argument('--before-ref', default=BEFORE_REF)
    ap.add_argument('--no-board', action='store_true', help='skip the stand-in debugger runs and the Tcl self test')
    args = ap.parse_args()
    t0 = time.time()
    tmp = None if args.work else tempfile.TemporaryDirectory()
    work = (args.work or Path(tmp.name)).resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work/'runs').mkdir(exist_ok=True)
    exports = work/'exports'
    if exports.exists():
        shutil.rmtree(exports)
    skew = exports/'skew'
    lm = export_layout.write_layout(ORIGINAL, skew, 'skew')
    with contextlib.redirect_stdout(io.StringIO()):
        for name in prepare_layouts.ZIPS:
            prepare_layouts.unpack(name, exports)
    res = dict(model=MODEL, what=__doc__.split('\n')[0], layout_manifest={k: lm[k] for k in (
        'layout', 'rule', 'tap_order_semantics', 'layers_reordered', 'changed_files', 'unchanged_files', 'files')})
    print('export', flush=True)
    res['export'] = check_export(skew, lm)
    print('emulation', flush=True)
    res['emulation'] = emulation(skew)
    print('command line', flush=True)
    res['cli'] = cli(work, skew)
    xsdb = None if args.no_board else fake_xsdb(work)
    if xsdb:
        print('board path (stand-in debugger)', flush=True)
        res['board'] = board(work, skew, xsdb, res['emulation'])
        print('test_run_board_xsdb.tcl', flush=True)
        res['tcl_selftest'] = tcl_selftest(work)
    else:
        res['board'] = dict(ran=False, why='--no-board' if args.no_board else 'no tclsh on this machine')
    print('unchanged paths', flush=True)
    res['unchanged'] = unchanged(work, xsdb, args.before_ref)
    print('L3 smoke test', flush=True)
    res['l3_orders'] = l3_smoke(work)
    print('guards', flush=True)
    res['guards'] = guards(work, skew)
    print('py_compile, unittests', flush=True)
    res['build'] = build_checks(work)
    res['export_files_lf_sha256'] = dict(original=lf_hashes(ORIGINAL), skew=lf_hashes(skew),
                                         frozen=lf_hashes(exports/'frozen'), multistart=lf_hashes(exports/'multistart'))
    parts = dict(export=res['export']['all_ok'], emulation=all(r['all_ok'] for r in res['emulation']),
                 cli=all(r['all_ok'] for r in res['cli']), unchanged=res['unchanged'].get('all_ok', False),
                 l3_orders=res['l3_orders']['all_ok'], guards=res['guards']['all_ok'], build=res['build']['all_ok'])
    if xsdb:
        parts.update(board_original=res['board']['original']['all_ok'], board_skew=res['board']['skew']['all_ok'],
                     tcl_selftest=res['tcl_selftest']['all_ok'])
    res['parts_ok'] = parts
    res['all_ok'] = all(parts.values())
    res['not_checked'] = [] if xsdb else ['board path (stand-in debugger)', 'test_run_board_xsdb.tcl']
    res['seconds'] = round(time.time() - t0, 1)
    args.out.write_text(json.dumps(res, indent=1) + '\n', encoding='utf-8')
    for k, v in parts.items():
        print(f'  {k:<16} {"ok" if v else "FAILED"}')
    print(f'all ok: {res["all_ok"]}   ({res["seconds"]} s) -> {rel(args.out)}')
    if tmp:
        tmp.cleanup()
    return 0 if res['all_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
