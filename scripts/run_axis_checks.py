"""Check the AXI-Stream wrapper against the bare core on the same vectors.

For each configuration this runs tb_stream_compare (the core directly, the bench
that produced RESULTS_KO.md) and tb_axis_wrapper (the core behind window_mac_axis,
driven the way the Zynq DMA will drive it), and requires:

  - every wrapper output matches the integer oracle, in order, with TLAST placed
    on the last channel of the last window only,
  - the wrapper's CYCLES register equals the core bench's total_cycles, so the
    wrapper costs nothing and a hardware number is comparable with the tables,
  - IN_STALL/OUT_STALL are 0 when nothing throttles and nonzero when something
    does, so a DMA-bound hardware run is detectable rather than silently wrong.

Python 3.9+ standard library only. Requires Icarus Verilog (iverilog and vvp).
No synthesis, post-route timing, power or board data.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from legacy_run_checks import export_vectors, fixture, read_probe, sha  # noqa: E402

CORE_SOURCES = ['rtl/sparse_window_mac.sv', 'rtl/continuous_window_mac.sv',
                'rtl/overlapped_window_mac.sv', 'rtl/banked_window_mac.sv']


def command(args, cwd, log, timeout=7200):
    proc = subprocess.run([str(x) for x in args], cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout)
    log.write_text(proc.stdout, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(f'Command failed ({proc.returncode}): {log}\n{proc.stdout[-6000:]}')
    return proc.stdout


def compile_and_run(dest, top, sources, params, vector, iverilog, vvp, tag):
    dest.mkdir(parents=True, exist_ok=True)
    argv = [iverilog, '-g2012', '-Wall', '-s', top, '-o', dest/f'{tag}.vvp']
    argv += [f'-P{top}.{k}={v}' for k, v in params.items()]
    command(argv+[str(s) for s in sources], dest, dest/f'{tag}_compile.log')
    return command([vvp, dest/f'{tag}.vvp', '+VEC='+str(vector.resolve())],
                   dest, dest/f'{tag}_sim.log')


def add_vectors(vectors, out, name, x, w, b, source, pad):
    """Export a fixture, and with pad also its copies padded with zero taps to a
    multiple of 4 (name + '_pad') and of 2 (name + '_pad2'), which is what the
    W=4 and W=2 hosts send."""
    vectors[name] = export_vectors(out/'vectors'/name, x, w, b, source=source)
    k = len(w[0])
    for width, suffix in ((4, '_pad'), (2, '_pad2')):
        if pad and k % width:
            kp = -(-k//width)*width
            vectors[name+suffix] = export_vectors(
                out/'vectors'/(name+suffix), [r+[0]*(kp-k) for r in x], [r+[0]*(kp-k) for r in w], b,
                source=dict(source, zero_taps_appended=kp-k))


def run_case(case, out, vectors, iverilog, vvp):
    name, vec, impl, p, depth, t, mode_seq, in_gap, out_gap = case[:9]
    # Optional tail: build the wrapper larger than the data and tell it the data's
    # shape at run time. 0 means "build at the data's shape", the fixed design.
    # The last is W, the activations the core takes per cycle (1, 2 or 4).
    kmax, coutmax, runtime, width = (list(case[9:])+[0, 0, 0, 1][len(case[9:]):])[:4]
    dest = out/name
    meta = vectors[vec]
    k, cout, n = meta['K'], meta['COUT'], meta['N']
    vector = out/'vectors'/vec
    src = lambda rel: out/'sources'/rel

    # 1. The bare core on the same stream, no stalls, no gaps: the reference cycles.
    #    At W=2 and W=4 it runs the windows padded to a multiple of W, as the
    #    host pads them; the wrapper bench pads the unpadded vector itself.
    core_vec = vec if width == 1 or k % width == 0 else vec+('_pad' if width == 4 else '_pad2')
    core_params = dict(K=vectors[core_vec]['K'], COUT=cout, P=p, DEPTH=depth, N=n, IMPL=impl, STALL_LEN=0,
                       PATTERN=0, INPUT_GAPS=0, MODE_SEQ=mode_seq, RESET_TEST=0, T=t, W=width)
    core_log = compile_and_run(dest, 'tb_stream_compare',
                               [src(s) for s in CORE_SOURCES]+[src('sim/tb_stream_compare.sv')],
                               core_params, out/'vectors'/core_vec, iverilog, vvp, 'core')
    m = re.search(r'PASS ALL checked_values=(\d+) windows=(\d+) total_cycles=(\d+)', core_log)
    assert m, core_log
    core_cycles = int(m.group(3))

    # 2. The same core behind the wrapper. EXPECT_CYCLES makes the bench itself
    #    fail if the wrapper costs a cycle, so the check is inside the simulation.
    expect = 0 if (in_gap or out_gap) else core_cycles
    # K/COUT stay the DATA's shape; KMAX/COUTMAX are what the wrapper is built at.
    # EXPECT_CYCLES still points at the bare core built at the data's shape, so a
    # runtime-geometry build that costs even one cycle more fails here.
    wrap_params = dict(K=k, COUT=cout, P=p, DEPTH=depth, N=n, IMPL=impl, T=t,
                       KMAX=kmax, COUTMAX=coutmax, RUNTIME_GEOM=runtime,
                       MODE_SEQ=mode_seq, IN_GAP=in_gap, OUT_GAP=out_gap, EXPECT_CYCLES=expect,
                       W=width)
    wrap_log = compile_and_run(dest, 'tb_axis_wrapper',
                               [src(s) for s in CORE_SOURCES]+[src('rtl/window_mac_axis.sv'),
                                                               src('sim/tb_axis_wrapper.sv')],
                               wrap_params, vector, iverilog, vvp, 'wrap')
    w = re.search(r'PASS ALL checked_values=(\d+) windows=(\d+) cycles=(\d+) '
                  r'in_stall=(\d+) out_stall=(\d+)', wrap_log)
    assert w, wrap_log
    assert 'FATAL' not in wrap_log and 'ERROR' not in wrap_log, wrap_log
    wrap_cycles, in_stall, out_stall = int(w.group(3)), int(w.group(4)), int(w.group(5))
    nwin = 2*n if mode_seq == 2 else n
    assert int(w.group(1)) == nwin*cout, wrap_log
    if not (in_gap or out_gap):
        assert wrap_cycles == core_cycles, (name, wrap_cycles, core_cycles)
    else:
        # Every cycle a throttled run takes beyond the unthrottled core is a
        # cycle the core waited on the DMA (IN_STALL) or on the sink (OUT_STALL);
        # the counters may also hold waits that hid under compute, so this is a
        # bound, not an equality.
        assert wrap_cycles - core_cycles <= in_stall + out_stall, \
            (name, 'stall counters miss a wait', wrap_cycles, core_cycles, in_stall, out_stall)

    report = dict(name=name, vector=vec, **wrap_params, core_cycles=core_cycles,
                  wrapper_cycles=wrap_cycles, in_stall=in_stall, out_stall=out_stall,
                  cycle_overhead=wrap_cycles-core_cycles, windows=nwin)
    tail = (f'core={core_cycles} wrapper={wrap_cycles} overhead={wrap_cycles-core_cycles}'
            if not (in_gap or out_gap) else
            f'wrapper={wrap_cycles} in_stall={in_stall} out_stall={out_stall} (throttled)')
    print(f'PASS {name}: {nwin} windows, {int(w.group(1))} values, {tail}', flush=True)
    (dest/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--suite', choices=['smoke', 'real', 'geom'], default='smoke',
                    help='smoke: small synthetic geometry. real: VGG11 K=576 COUT=128. '
                         'geom: one large RUNTIME_GEOM build running small layers.')
    ap.add_argument('--windows', type=int, default=32,
                    help='real suite only: frames taken from the split (2x that many windows).')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    ap.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    args = ap.parse_args()
    iverilog, vvp = shutil.which(args.iverilog), shutil.which(args.vvp)
    if not iverilog or not vvp:
        raise SystemExit('Icarus Verilog not found. Put iverilog and vvp on PATH.')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    out = ROOT/'build'/('axis_'+stamp)
    out.mkdir(parents=True)
    print(f'Fresh wrapper run: {out}', flush=True)

    sources = CORE_SOURCES+['rtl/window_mac_axis.sv', 'sim/tb_stream_compare.sv',
                            'sim/tb_axis_wrapper.sv', 'scripts/run_axis_checks.py']
    source_hashes = {}
    for rel in sources:
        saved = out/'sources'/rel
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/rel, saved)
        source_hashes[rel] = sha(saved)
    versions = {n: command([e, '-V'], out, out/(n+'_version.txt'))
                for n, e in [('iverilog', iverilog), ('vvp', vvp)]}

    vectors, cases = {}, []
    if args.suite == 'smoke':
        # The built K must be a multiple of 4: the wrapper packs four activations
        # per beat. k9 is data for a larger runtime-geometry build only.
        for k, c in [(12, 9), (4, 1), (28, 17), (9, 9), (28, 4)]:
            name = f'synthetic_k{k}_c{c}'
            x, w, b = fixture(k, c)
            x = x[:8]
            add_vectors(vectors, out, name, x, w, b, {'synthetic_seed': 20260916+k*100+c}, pad=True)
        for impl, t in [(2, 1), (3, 1), (3, 2), (3, 4)]:
            v = 'v3' if impl == 2 else f'v4t{t}'
            cases.append((f'{v}_k12_p2_d2', 'synthetic_k12_c9', impl, 2, 2, t, 2, 0, 0))
            cases.append((f'{v}_k12_p8_d3', 'synthetic_k12_c9', impl, 8, 3, t, 2, 0, 0))
            cases.append((f'{v}_k4_c1_p1_d1', 'synthetic_k4_c1', impl, 1, 1, t, 0, 0, 0))
            cases.append((f'{v}_k28_c17_p4_d2', 'synthetic_k28_c17', impl, 4, 2, t, 1, 0, 0))
        # Throttled: the stall counters must notice, and results must stay correct.
        for impl, t in [(2, 1), (3, 4)]:
            v = 'v3' if impl == 2 else f'v4t{t}'
            cases.append((f'{v}_k12_ingap', 'synthetic_k12_c9', impl, 2, 2, t, 2, 5, 0))
            cases.append((f'{v}_k12_outgap', 'synthetic_k12_c9', impl, 2, 2, t, 2, 0, 7))
            cases.append((f'{v}_k12_bothgap', 'synthetic_k12_c9', impl, 2, 2, t, 2, 3, 4))
        # The four-wide port (W=4). Unthrottled, IN_STALL must stay 0: the wrapper
        # takes a beat every cycle. k9 on a larger build writes RUN_K=9 and must
        # read back 12, the padded length the bench then streams.
        for p, d in [(2, 2), (8, 3)]:
            cases.append((f'v4t4w4_k12_p{p}_d{d}', 'synthetic_k12_c9', 3, p, d, 4, 2, 0, 0, 0, 0, 0, 4))
        cases.append(('v4t4w4_k4_c1_p1_d1', 'synthetic_k4_c1', 3, 1, 1, 4, 0, 0, 0, 0, 0, 0, 4))
        cases.append(('v4t4w4_k28_c17_p4_d2', 'synthetic_k28_c17', 3, 4, 2, 4, 1, 0, 0, 0, 0, 0, 4))
        cases.append(('v4t4w4_k9_runtime', 'synthetic_k9_c9', 3, 4, 2, 4, 2, 0, 0, 48, 20, 1, 4))
        cases.append(('v4t4w4_k12_ingap', 'synthetic_k12_c9', 3, 2, 2, 4, 2, 5, 0, 0, 0, 0, 4))
        cases.append(('v4t4w4_k12_outgap', 'synthetic_k12_c9', 3, 2, 2, 4, 2, 0, 7, 0, 0, 0, 4))
        cases.append(('v4t4w4_k12_bothgap', 'synthetic_k12_c9', 3, 2, 2, 4, 2, 3, 4, 0, 0, 0, 4))
        # The two-wide port (W=2): half a beat per cycle. k9 on a larger build
        # writes RUN_K=9 and must read back 10, so every other window ends after
        # the first half of a beat and the next one starts on its second half.
        for p, d in [(2, 2), (8, 3)]:
            cases.append((f'v4t4w2_k12_p{p}_d{d}', 'synthetic_k12_c9', 3, p, d, 4, 2, 0, 0, 0, 0, 0, 2))
        cases.append(('v4t4w2_k4_c1_p1_d1', 'synthetic_k4_c1', 3, 1, 1, 4, 0, 0, 0, 0, 0, 0, 2))
        cases.append(('v4t4w2_k28_c17_p4_d2', 'synthetic_k28_c17', 3, 4, 2, 4, 1, 0, 0, 0, 0, 0, 2))
        cases.append(('v4t4w2_k9_runtime', 'synthetic_k9_c9', 3, 4, 2, 4, 2, 0, 0, 48, 20, 1, 2))
        cases.append(('v4t4w2_k12_ingap', 'synthetic_k12_c9', 3, 2, 2, 4, 2, 5, 0, 0, 0, 0, 2))
        cases.append(('v4t4w2_k12_outgap', 'synthetic_k12_c9', 3, 2, 2, 4, 2, 0, 7, 0, 0, 0, 2))
        cases.append(('v4t4w2_k12_bothgap', 'synthetic_k12_c9', 3, 2, 2, 4, 2, 3, 4, 0, 0, 0, 2))
        # Load-bound windows (COUT <= K/W) with a slow DMA: the wait often falls
        # on a window boundary, where the core could start but has no beat yet.
        # (IN_GAP=2 is left out: this bench drops TVALID before a handshake, which
        # AXI-Stream forbids, and at a gap of 2 that can lock it in step with
        # TREADY; it hangs on the RTL before this check too. The UVM driver holds
        # TVALID until accepted, as the DMA does.)
        for width in (1, 2, 4):
            v = f'v4t4w{width}' if width > 1 else 'v4t4'
            for gap in (3, 5):
                cases.append((f'{v}_k28_c4_ingap{gap}', 'synthetic_k28_c4', 3, 4, 2, 4, 0, gap, 0, 0, 0, 0, width))
    elif args.suite == 'geom':
        # One build, many layers. KMAX/COUTMAX are the CIFAR bitstream's built-in
        # maxima; each case feeds it a layer that is smaller in K, in COUT, or in
        # both, and requires the same values and the same cycle count as a core
        # built at exactly that layer's shape.
        #
        # K=27 is deliberate. The stream packs four activations per beat with no
        # per-window alignment, so a layer whose K is not a multiple of four ends
        # its windows mid-beat. Either that works or the driver has to pad every
        # such layer, and guessing which is how the board run goes wrong.
        KMAX, COUTMAX = 1152, 128
        # K=9 and K=297 are the baseline denoiser's first and last layers: at W=2
        # they pad to 10 and 298, so their windows end after half a beat.
        layers = [(36, 32), (288, 32), (288, 64), (576, 64), (1152, 128), (27, 32), (9, 32), (297, 1)]
        for k, c in layers:
            name = f'layer_k{k}_c{c}'
            x, w, b = fixture(k, c)
            x = x[:8]
            add_vectors(vectors, out, name, x, w, b, {'synthetic_seed': 20260916+k*100+c}, pad=True)
        for impl, t, width in [(2, 1, 1), (3, 4, 1), (3, 4, 4), (3, 4, 2)]:
            v = 'v3' if impl == 2 else f'v4t{t}' + (f'w{width}' if width > 1 else '')
            for k, c in layers:
                # mode_seq 2 alternates dense and sparse windows, which is the
                # only mode that exercises both tap counts in one run.
                cases.append((f'{v}_k{k}_c{c}_runtime', f'layer_k{k}_c{c}', impl,
                              8, 2, t, 2, 0, 0, KMAX, COUTMAX, 1, width))
        # The board build exactly (P=16), at W=4, on the 64-output layer.
        cases.append(('v4t4w4_k288_c64_p16_runtime', 'layer_k288_c64', 3, 16, 2, 4, 2, 0, 0,
                      KMAX, COUTMAX, 1, 4))
        cases.append(('v4t4w2_k288_c64_p16_runtime', 'layer_k288_c64', 3, 16, 2, 4, 2, 0, 0,
                      KMAX, COUTMAX, 1, 2))
        # Control: the same large build told to run its full built-in shape, and
        # the same shape built fixed. Both must agree, or RUNTIME_GEOM=1 changed
        # behaviour rather than only adding the ability to shrink.
        cases.append(('v3_full_runtime', 'layer_k1152_c128', 2, 8, 2, 1, 2, 0, 0,
                      KMAX, COUTMAX, 1))
        cases.append(('v3_full_fixed', 'layer_k1152_c128', 2, 8, 2, 1, 2, 0, 0))
    else:
        path = ROOT/'data'/'evaluation.wpr'
        x, w, b, ids, y = read_probe(path)
        x, y, ids = x[:args.windows], y[:args.windows], ids[:args.windows]
        vectors['evaluation'] = export_vectors(
            out/'vectors'/'evaluation', x, w, b, y, ids,
            {'file': 'evaluation.wpr', 'sha256': sha(path),
             'selection': f'first {args.windows} recorded windows'})
        for impl, t in [(2, 1), (3, 1), (3, 4), (3, 8)]:
            v = 'v3' if impl == 2 else f'v4t{t}'
            cases.append((f'{v}_evaluation_p8_d2', 'evaluation', impl, 8, 2, t, 2, 0, 0))
        cases.append(('v4t4w4_evaluation_p8_d2', 'evaluation', 3, 8, 2, 4, 2, 0, 0, 0, 0, 0, 4))
        cases.append(('v4t4w4_evaluation_p16_d2', 'evaluation', 3, 16, 2, 4, 2, 0, 0, 0, 0, 0, 4))
        cases.append(('v4t4w4_evaluation_p16_d2_ingap', 'evaluation', 3, 16, 2, 4, 2, 9, 0, 0, 0, 0, 4))
        cases.append(('v4t4w2_evaluation_p8_d2', 'evaluation', 3, 8, 2, 4, 2, 0, 0, 0, 0, 0, 2))
        cases.append(('v4t4w2_evaluation_p16_d2', 'evaluation', 3, 16, 2, 4, 2, 0, 0, 0, 0, 0, 2))
        cases.append(('v4t4w2_evaluation_p16_d2_ingap', 'evaluation', 3, 16, 2, 4, 2, 9, 0, 0, 0, 0, 2))
        cases.append(('v3_evaluation_p8_d2_ingap', 'evaluation', 2, 8, 2, 1, 2, 9, 0))
        cases.append(('v3_evaluation_p8_d2_outgap', 'evaluation', 2, 8, 2, 1, 2, 0, 11))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_case, c, out, vectors, iverilog, vvp) for c in cases]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    results.sort(key=lambda r: r['name'])

    clean = [r for r in results if not r['IN_GAP'] and not r['OUT_GAP']]
    report = dict(pass_all=True, runtime='Icarus Verilog behavioral RTL simulation',
                  utc=datetime.now(timezone.utc).isoformat(), suite=args.suite,
                  test_cases=len(results),
                  checked_rtl_outputs=sum(r['windows']*r['COUT'] for r in results),
                  max_cycle_overhead=max(r['cycle_overhead'] for r in clean) if clean else None,
                  wrapper_matches_core_cycles=all(r['cycle_overhead'] == 0 for r in clean),
                  fpga_synthesis_performed=False, board_measurement_performed=False,
                  source_sha256=source_hashes, tool_versions=versions, cases=results)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f'\nPASS ALL: {len(results)} wrapper cases, '
          f'{report["checked_rtl_outputs"]} outputs checked.', flush=True)
    print(f'Wrapper cycle overhead vs the bare core: '
          f'{report["max_cycle_overhead"]} (must be 0).', flush=True)
    print('FPGA synthesis / route / board measurements: NOT performed.', flush=True)
    print(f'Results: {out}', flush=True)


if __name__ == '__main__':
    main()
