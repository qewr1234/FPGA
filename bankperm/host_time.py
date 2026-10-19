"""Host time per image beside the core, and the Amdahl bound on the end-to-end saving (B-32 ReLU + QAT s1, W=4).

    python bankperm/host_time.py [--runs 5]       # writes bankperm/host_time.json (about a minute)

What the board run needs from the host besides the core, per image, for
dn_d10_c32_us_fx_qat on Set12 05.png (256 x 256, sigma 25, test_noise seed 0),
timed on THIS machine with the board driver's own functions
(scripts/run_denoise.py denoise(), scripts/run_cifar.py im2col / requant,
denoise/common.py pad_mult / unshuffle2 / to_image / shuffle2):

  input      the 7-bit quantization of the noisy image, padding to even sides
             and the 2x2 unshuffle into 4 phases (the network's input);
  per layer  the gather of its input maps (np.concatenate), im2col, and for
             conv1..conv9 the requantization of the INT32 accumulators and the
             (N, COUT) -> (COUT, h, w) layout of the next layer's input map; no
             pooling (post 'none' on every layer of this network) and no W-padding
             (K = 36, 288, 324 are multiples of 4, so write_board_files pads
             nothing);
  output     the last layer's accumulators -> 8-bit pixels (to_image) and the
             2x2 shuffle back to 256 x 256.

Two timings of the same work, each the median of --runs runs:
  'driver loop'  run_denoise.denoise() itself, with run_layer replaced by a
                 lookup of the accumulators computed beforehand (so the core and
                 the board I/O cost nothing) and the driver's functions wrapped to
                 time them in place; it also contains the driver's reporting
                 ((x != 0).mean() per layer, one print per layer, to a buffer);
  'per op'       each step above called on its own, on the same inputs.
For context, and NOT part of the host work a deployment needs, per op also:
the integer oracle (the gold the harness checks every board word against), the
serialization of the windows and the gold to bytes (write_board_files; the file
writes and the JTAG session are not timed) and the driver's nonzero fraction;
and the column gather x[:, skew order] that the skewed layout (PROTOCOL_2.md L2)
would add on conv2..conv9 if it were done after im2col (an implementation that
writes the skewed order inside im2col would not need it; not measured).

Both the Original export and the Multi-start export (the two layouts whose W=4
board totals are below) are timed; their host work is the same operations on
arrays of the same shapes, so it should not differ beyond noise.

Single thread: OMP/OpenBLAS/MKL/numexpr threads are set to 1 before numpy is
imported (numpy's integer matmul and elementwise operations do not use BLAS
threads anyway); the process is not pinned to a CPU (--cpu pins it). The CPU
model, core count, load average and the process CPU time are recorded, so a
timing taken while other work shared the machine can be recognised (CPU time
well below wall time).

Core time: the W=4 board cycles (bankperm/b32_board.json exact predictions, equal
to the board numbers of bankperm/board_transcribed.json for every layer of
Original and Multi-start, checked here) at the 50 MHz core clock of those runs.
Amdahl bound on the end-to-end saving of Multi-start over Original, with H the
host time per image (layout-independent) and C the core time:
  back to back (no overlap)   (C_orig - C_ms) / (H + C_orig)
  perfect overlap (pipelined over images)   (max(H, C_orig) - max(H, C_ms)) / max(H, C_orig)
  per-layer overlap (host work of a layer hidden under the same layer's core
  time only; layers depend on each other)   sum_l max(H_l, C_l), same formula.
Transfer time is not counted in any of them: neither the host -> DDR copy of
the windows nor the results back (on the JTAG harness that is most of the wall
time; with the core's own DMA streaming from DDR, the core cycles already
include the stream, IN_STALL = 0 on these runs). Host and core numbers come
from different machines (this machine; the ZedBoard at 50 MHz). The JTAG
harness's measured wall time (denoise/board_runs/dn_d10_c32_us_fx_qat_05_w4.json,
the board PC) is given for context.
"""
import os

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
           'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'):
    os.environ[_v] = '1'

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import platform  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import run_cifar  # noqa: E402
import run_denoise  # noqa: E402
import common  # noqa: E402
from common import QMAX_A, load_set, psnr, test_noise  # noqa: E402
from b32_board import ZIPS, layouts  # noqa: E402
from skew_count import skew_order  # noqa: E402

MODEL = 'dn_d10_c32_us_fx_qat'
SET, IMAGE = 'Set12', '05.png'
FCLK_MHZ = 50.0
BOARD_RUN = ROOT/'denoise'/'board_runs'/f'{MODEL}_05_w4.json'
DRIVER_FILES = ('scripts/run_denoise.py', 'scripts/run_cifar.py', 'denoise/common.py')
NEEDED = ('gather', 'im2col', 'requant', 'layout')        # per layer; plus input and output
EXTRA = ('oracle', 'serialize', 'nonzero_fraction', 'skew_gather')


def ns():
    return time.perf_counter_ns()


def ms(v):
    return round(float(v)/1e6, 4)


def machine():
    info = dict(platform=platform.platform(), python=platform.python_version(), numpy=np.__version__,
                cpu_count=os.cpu_count(), cpus_usable=len(os.sched_getaffinity(0)))
    try:
        txt = Path('/proc/cpuinfo').read_text()
        info['cpu_model'] = next(l.split(':', 1)[1].strip() for l in txt.splitlines() if l.startswith('model name'))
        info['hypervisor'] = ' hypervisor' in next(l for l in txt.splitlines() if l.startswith('flags'))
    except (OSError, StopIteration):
        info['cpu_model'] = platform.processor()
    try:
        lscpu = subprocess.run(['lscpu'], capture_output=True, text=True).stdout
        for key in ('Core(s) per socket', 'Socket(s)', 'Thread(s) per core', 'Hypervisor vendor', 'L2 cache', 'L3 cache'):
            for l in lscpu.splitlines():
                if l.startswith(key + ':'):
                    info[key] = l.split(':', 1)[1].strip()
    except OSError:
        pass
    info['thread_env'] = {v: os.environ[v] for v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')}
    return info


def driver_versions():
    out = {}
    for f in DRIVER_FILES:
        data = (ROOT/f).read_bytes()
        blob = hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()
        try:
            head = subprocess.run(['git', 'rev-parse', f'HEAD:{f}'], cwd=ROOT, capture_output=True,
                                  text=True).stdout.strip()
        except OSError:
            head = ''
        out[f] = dict(git_blob=blob, equals_HEAD=blob == head)
    try:
        out['HEAD'] = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                     text=True).stdout.strip()
    except OSError:
        pass
    return out


def capture(man, layers, q_in):
    """One emulation of the image: every layer's input maps, windows and accumulators, and the output."""
    real = run_denoise.run_layer
    acc, xs = {}, {}

    def keep(L, x, args, tag):
        a, info = real(L, x, args, tag)
        acc[L['name']], xs[L['name']] = a, x
        return a, info

    run_denoise.run_layer = keep
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out, _ = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'host')
    finally:
        run_denoise.run_layer = real
    return acc, xs, out


def driver_loop(man, layers, q_in, acc):
    """run_denoise.denoise() with the core replaced by a lookup; the driver's functions timed in place."""
    rec = {n: [] for n in ('im2col', 'requant', 'to_image', 'shuffle2', 'pad_mult', 'unshuffle2')}
    orig = {n: getattr(run_denoise, n) for n in rec}

    def timed(name):
        f = orig[name]

        def g(*a, **k):
            t = ns()
            r = f(*a, **k)
            rec[name].append(ns() - t)
            return r
        return g

    real = run_denoise.run_layer
    run_denoise.run_layer = lambda L, x, args, tag: (acc[L['name']], dict(emulated=True, runs=0, mismatches=0))
    for n in rec:
        setattr(run_denoise, n, timed(n))
    try:
        buf = io.StringIO()
        c0, t0 = time.process_time_ns(), ns()
        with contextlib.redirect_stdout(buf):
            out, _ = run_denoise.denoise(q_in, man, layers, SimpleNamespace(emulate=True, out=None), 'host')
        wall, cpu = ns() - t0, time.process_time_ns() - c0
    finally:
        run_denoise.run_layer = real
        for n, f in orig.items():
            setattr(run_denoise, n, f)
    return out, wall, cpu, rec


def per_op(man, layers, noisy, acc, xs, skewed):
    """Each step of the host work on its own, in the driver's order, on the captured inputs; ns per step."""
    t = {}
    t0 = ns()
    q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
    t['input_quantize'] = ns() - t0
    t0 = ns()
    img = common.pad_mult(q_in, man.get('pad_to', 2))
    base = common.unshuffle2(img).astype(np.uint8)
    t['input_pad_unshuffle'] = ns() - t0
    maps = {'image': base}
    per = {}
    for i, L in enumerate(layers):
        r = {}
        t0 = ns()
        q = np.concatenate([maps[k] for k in L['inputs']], 0)
        r['gather'] = ns() - t0
        pad, oh, ow = run_denoise.node_geometry(L, *q.shape[1:])
        t0 = ns()
        x = run_cifar.im2col(q[None], kh=L['kh'], kw=L['kw'], pad=pad, dilation=L['dilation'], stride=L['stride'])
        r['im2col'] = ns() - t0
        assert np.array_equal(x, xs[L['name']]), L['name']
        a = acc[L['name']]
        # harness-only context
        t0 = ns()
        gold = run_cifar.oracle(x, L['wq'], L['bq'])
        r['oracle'] = ns() - t0
        assert np.array_equal(gold, a), L['name']
        t0 = ns()
        _ = np.ascontiguousarray(x, np.uint8).tobytes(), gold.astype('<i4').tobytes()
        r['serialize'] = ns() - t0
        t0 = ns()
        _ = float((x != 0).mean())
        r['nonzero_fraction'] = ns() - t0
        if L['name'] in skewed:
            c = L['K']//(L['kh']*L['kw'])
            order = skew_order(L['K'], c)
            t0 = ns()
            _ = x[:, order]
            r['skew_gather'] = ns() - t0
        if i < len(layers) - 1:
            assert L['post'] == 'none', L['name']          # no pooling in this network
            t0 = ns()
            rq = run_cifar.requant(a, np.asarray(L['requant']))
            r['requant'] = ns() - t0
            t0 = ns()
            maps[L['name']] = np.ascontiguousarray(rq.reshape(oh, ow, L['COUT']).transpose(2, 0, 1))
            r['layout'] = ns() - t0
        else:
            H, W = q_in.shape
            t0 = ns()
            acc_maps = a.T.reshape(L['COUT'], oh, ow)
            out = common.shuffle2(common.to_image(acc_maps, base, L['to_pixel'], False), H, W)
            r['output'] = ns() - t0
        per[L['name']] = r
    return t, per, out


def median_of(runs):
    return float(np.median(runs))


def time_layout(name, export, runs, skewed):
    man, layers = run_denoise.load_layers(Path(export))
    assert man['model'] == MODEL and man.get('unshuffle') and man['sigma'] == 25
    clean, noisy = next((c, q) for n, c, q in test_noise(load_set(SET), man['sigma'], seed=0) if n == IMAGE)
    q_in = np.rint(noisy*QMAX_A).astype(np.uint8)
    acc, xs, out0 = capture(man, layers, q_in)        # also the warm-up run
    p = float(psnr(clean, out0.astype(np.float32)/255))
    ref = json.loads((Path(export)/'int_eval.json').read_text())[SET]['per_image'][IMAGE]
    names = [L['name'] for L in layers]
    loops, ops = [], []
    for _ in range(runs):
        out, wall, cpu, rec = driver_loop(man, layers, q_in, acc)
        assert np.array_equal(out, out0)
        loops.append((wall, cpu, rec))
        t_in, per, out = per_op(man, layers, noisy, acc, xs, skewed)
        assert np.array_equal(out, out0)
        ops.append((t_in, per))
    # driver loop
    wall = [w for w, _, _ in loops]
    cpu = [c for _, c, _ in loops]
    inplace = {}
    for f in ('im2col', 'requant'):
        k = len(loops[0][2][f])
        inplace[f] = dict(per_layer_ms={names[j]: ms(median_of([r[f][j] for _, _, r in loops])) for j in range(k)},
                          total_ms=ms(median_of([sum(r[f]) for _, _, r in loops])))
    for f in ('pad_mult', 'unshuffle2', 'to_image', 'shuffle2'):
        inplace[f] = dict(total_ms=ms(median_of([sum(r[f]) for _, _, r in loops])))
    loop = dict(what=('run_denoise.denoise() on the image, run_layer replaced by a lookup of precomputed accumulators; '
                      'includes the driver\'s reporting ((x != 0).mean() and a print per layer)'),
                runs_wall_ms=[ms(v) for v in wall], median_wall_ms=ms(median_of(wall)),
                runs_cpu_ms=[ms(v) for v in cpu], median_cpu_ms=ms(median_of(cpu)),
                cpu_over_wall=[round(c/w, 3) for c, w in zip(cpu, wall)],
                driver_functions_in_place=inplace)
    # per op
    per_layer = {}
    for L in layers:
        n = L['name']
        keys = [k for k in ops[0][1][n]]
        per_layer[n] = dict(K=L['K'], COUT=L['COUT'], windows=int(xs[n].shape[0]), post=L['post'],
                            median_ms={k: ms(median_of([o[1][n][k] for o in ops])) for k in keys})
        nk = [k for k in NEEDED + ('output',) if k in keys]
        per_layer[n]['needed_ms'] = ms(median_of([sum(o[1][n][k] for k in nk) for o in ops]))
    inp = {k: ms(median_of([o[0][k] for o in ops])) for k in ops[0][0]}
    needed_runs = [sum(o[0].values()) + sum(o[1][n][k] for n in names for k in NEEDED + ('output',) if k in o[1][n])
                   for o in ops]
    extra_runs = {k: [sum(o[1][n].get(k, 0) for n in names) for o in ops] for k in EXTRA}
    by_step = {k: ms(median_of([sum(o[1][n].get(k, 0) for n in names) for o in ops]))
               for k in NEEDED + ('output',)}
    res = dict(export=str(Path(export).relative_to(ROOT)) if Path(export).is_relative_to(ROOT) else Path(export).name,
               psnr_db=p, psnr_equals_int_eval=abs(p - ref) <= 1e-5,
               driver_loop=loop,
               per_op=dict(input_ms=inp, per_layer=per_layer, needed_by_step_ms=by_step,
                           needed_runs_ms=[ms(v) for v in needed_runs], needed_median_ms=ms(median_of(needed_runs)),
                           harness_only_median_ms={k: ms(median_of(v)) for k, v in extra_runs.items()}))
    return res


def core_times():
    b = json.loads((HERE/'b32_board.json').read_text())
    assert b['model'] == MODEL and b['image'] == f'{SET} {IMAGE}'
    bvp = b['board_vs_prediction']
    board_layers = {'original': bvp['original_rep1_layers'], 'multistart': bvp['multistart_rep1_layers']}
    out = {}
    for lay in ('original', 'frozen', 'multistart'):
        L = b['layouts'][lay]['layers']
        per = {r['name']: r['exact_w4'] for r in L}
        tot = b['layouts'][lay]['total']['exact_w4']
        assert sum(per.values()) == tot
        rec = dict(exact_w4_cycles=tot, core_ms_at_50MHz=round(tot/(FCLK_MHZ*1e3), 4),
                   per_layer_cycles=per, per_layer_core_ms={k: round(v/(FCLK_MHZ*1e3), 4) for k, v in per.items()})
        if lay in board_layers:
            rec['board_rep1_equals_exact_every_layer'] = all(
                r['board'] - r['in_stall'] == per[r['name']] and r['board_minus_in_stall_minus_predicted'] == 0
                for r in board_layers[lay])
            rec['board_rep1_in_stall'] = sum(r['in_stall'] for r in board_layers[lay])
        reps = [r[lay]['total'] for r in bvp['repeats'] if lay in r]
        rec['board_repeat_totals'] = [dict(board=r['board'], in_stall=r['in_stall'],
                                           board_minus_in_stall=r['board'] - r['in_stall']) for r in reps]
        rec['board_repeats_minus_in_stall_equal_exact'] = all(r['board'] - r['in_stall'] == tot for r in reps)
        out[lay] = rec
    skew = json.loads((HERE/'skew_count.json').read_text())['networks']['B-32 ReLU + QAT s1']['images']['Set12 05.png']
    out['skew_count_only'] = dict(
        what=('PROTOCOL_2.md L2 skew, the count without fill and drain (not a board number and not an exact '
              'prediction; bankperm/board_prediction_2.json will have that); for scale only'),
        count_w4_cycles=skew['skewed']['w4'], core_ms_at_50MHz=round(skew['skewed']['w4']/(FCLK_MHZ*1e3), 4),
        original_count_w4_cycles=skew['conventional']['w4'],
        original_count_ms_at_50MHz=round(skew['conventional']['w4']/(FCLK_MHZ*1e3), 4))
    return out


def amdahl(h_ms, c0_ms, c1_ms, h_layer=None, c0_layer=None, c1_layer=None):
    core = 100*(c0_ms - c1_ms)/c0_ms
    seq = 100*(c0_ms - c1_ms)/(h_ms + c0_ms)
    ov0, ov1 = max(h_ms, c0_ms), max(h_ms, c1_ms)
    out = dict(host_ms=round(h_ms, 4), core_orig_ms=round(c0_ms, 4), core_new_ms=round(c1_ms, 4),
               core_saving_pct=round(core, 4),
               back_to_back=dict(end_to_end_orig_ms=round(h_ms + c0_ms, 4), end_to_end_new_ms=round(h_ms + c1_ms, 4),
                                 saving_pct=round(seq, 4), core_share_pct=round(100*c0_ms/(h_ms + c0_ms), 2)),
               perfect_overlap_over_images=dict(end_to_end_orig_ms=round(ov0, 4), end_to_end_new_ms=round(ov1, 4),
                                                saving_pct=round(100*(ov0 - ov1)/ov0, 4),
                                                bound_by='core' if c0_ms >= h_ms else 'host'))
    if h_layer is not None:
        o0 = sum(max(h_layer[n], c0_layer[n]) for n in h_layer)
        o1 = sum(max(h_layer[n], c1_layer[n]) for n in h_layer)
        out['per_layer_overlap'] = dict(end_to_end_orig_ms=round(o0, 4), end_to_end_new_ms=round(o1, 4),
                                        saving_pct=round(100*(o0 - o1)/o0, 4),
                                        layers_host_bound=[n for n in h_layer if h_layer[n] > c0_layer[n]])
    return out


def harness_wall():
    d = json.loads(BOARD_RUN.read_text())
    img = d['images'][0]
    L = img['layers']
    wall = sum(r['wall_seconds'] for r in L)
    host = sum(r['host_seconds'] for r in L)
    cyc = sum(r['cycles'] for r in L)
    return dict(source=str(BOARD_RUN.relative_to(ROOT)), model=d['model'], image=img['image'],
                emulated=d['emulated'], activations_per_cycle=d['activations_per_cycle'],
                fclk_mhz=sorted({f for r in L for f in r['fclk_mhz']}), core_id=sorted({c for r in L for c in r['core_id']}),
                layers=len(L), board_cycles=cyc, core_seconds_at_50MHz=round(cyc/(FCLK_MHZ*1e6), 4),
                xsdb_wall_seconds_sum=round(wall, 1), run_layer_host_seconds_sum=round(host, 1),
                per_layer_xsdb_wall_seconds={r['name']: r['wall_seconds'] for r in L},
                core_share_of_xsdb_wall_pct=round(100*cyc/(FCLK_MHZ*1e6)/wall, 4),
                what=('wall_seconds: one xsdb session per layer (bitstream load over JTAG, the layer\'s config, windows '
                      'and results over JTAG, the core run, the board-side check); host_seconds: run_denoise.run_layer '
                      'around it (also the oracle and the file writes); measured on the board PC (Windows), not this '
                      'machine; the windows\' im2col and the requantization are outside both'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--cpu', type=int, help='pin the process to this CPU')
    ap.add_argument('--out', type=Path, default=HERE/'host_time.json')
    args = ap.parse_args()
    if args.cpu is not None:
        os.sched_setaffinity(0, {args.cpu})
    t0 = time.time()
    mach = machine()
    load_before = os.getloadavg()
    man, layers = run_denoise.load_layers(ROOT/'denoise'/'export'/MODEL)
    skewed = {L['name'] for i, L in enumerate(layers)
              if 0 < i < len(layers) - 1 and len(L['inputs']) == 1 and (L['K']//(L['kh']*L['kw'])) % 4 == 0}
    timing = {}
    with tempfile.TemporaryDirectory() as tmp:
        lay = layouts({'multistart': ZIPS['multistart']}, tmp)
        for name in ('original', 'multistart'):
            timing[name] = time_layout(name, lay[name][1], args.runs, skewed)
            timing[name]['export'] = (str(Path(lay[name][0]).relative_to(ROOT)))
            print(f'{name:<11} driver loop {timing[name]["driver_loop"]["median_wall_ms"]:8.2f} ms '
                  f'(cpu {timing[name]["driver_loop"]["median_cpu_ms"]:.2f})   per-op needed '
                  f'{timing[name]["per_op"]["needed_median_ms"]:8.2f} ms', flush=True)
    load_after = os.getloadavg()
    core = core_times()
    c0, c1 = core['original']['core_ms_at_50MHz'], core['multistart']['core_ms_at_50MHz']
    cf = core['frozen']['core_ms_at_50MHz']
    h_orig = timing['original']['per_op']
    h_layer = {}
    for n, r in h_orig['per_layer'].items():
        h_layer[n] = r['needed_ms']
    h_layer['conv1'] += sum(h_orig['input_ms'].values())                  # the input steps go with conv1
    H = h_orig['needed_median_ms']
    Hloop = timing['original']['driver_loop']['median_wall_ms']
    am = {
        'multistart_vs_original_host_per_op': amdahl(H, c0, c1, h_layer, core['original']['per_layer_core_ms'],
                                                     core['multistart']['per_layer_core_ms']),
        'multistart_vs_original_host_driver_loop': amdahl(Hloop, c0, c1),
        'frozen_vs_original_host_per_op': amdahl(H, c0, cf),
    }
    skew_extra = timing['original']['per_op']['harness_only_median_ms']['skew_gather']
    am['skew_count_vs_original_host_per_op_plus_skew_gather'] = dict(
        what=('for scale only, not a board figure: core times from the counts of skew_count.json (Original and skew, '
              'both without fill and drain), host time plus the column gather on conv2..conv9 that the skew adds if '
              'it is not written by im2col itself'),
        **amdahl(H + skew_extra, core['skew_count_only']['original_count_ms_at_50MHz'],
                 core['skew_count_only']['core_ms_at_50MHz']))
    res = dict(
        model=MODEL, image=f'{SET} {IMAGE} (256 x 256; 4 phases of 128 x 128, 16384 windows per layer)',
        noise='sigma 25, test_noise seed 0',
        machine=mach, load_average_before=load_before, load_average_after=load_after,
        driver=driver_versions(),
        runs=args.runs, statistic=f'median of {args.runs} runs, after one capture run (warm-up) per export',
        threads='single thread: *_NUM_THREADS=1 before numpy; integer matmul and elementwise numpy are single-threaded',
        pinned_cpu=args.cpu,
        host_work=('needed: input quantization + pad + unshuffle; per layer gather + im2col; conv1-conv9 requant + '
                   'layout to (C, h, w); conv10 to_image + shuffle2. No pooling and no W-padding in this network. '
                   'harness_only (not needed by a deployment): oracle, serialize, nonzero_fraction; skew_gather: what '
                   'the skewed layout would add if done as a column gather after im2col'),
        timing=timing, core=core, amdahl=am, jtag_harness=harness_wall(),
        caveats=[
            'host times are from this machine (see machine), not from the board PC that ran the JTAG harness nor '
            'from the ZedBoard\'s ARM cores; a Cortex-A9 at 667 MHz would be many times slower',
            'transfer time is not counted: the host -> DDR copy of the windows and the results back are left out '
            '(on the JTAG harness they dominate the wall time); the core cycles include the DMA stream from DDR',
            'host and core run on different machines; the Amdahl figures combine the two',
            'perfect overlap over images needs a second image in flight; per-layer overlap hides a layer\'s host work '
            'only under the same layer\'s core time (layers depend on each other), streaming tiles',
            'core time is the board cycle count at 50 MHz (exact predictions, equal to the board numbers of the '
            'repeat-1 runs for every layer of Original and Multi-start)',
            'the driver loop also contains the driver\'s per-layer reporting, so it is above the per-op sum',
            'the machine may be shared with other work: compare cpu with wall time and the load averages'],
        seconds=round(time.time() - t0, 1))
    args.out.write_text(json.dumps(res, indent=1) + '\n')
    a = am['multistart_vs_original_host_per_op']
    print(f'core {c0:.2f} ms (Original) / {c1:.2f} ms (Multi-start) at 50 MHz; host {H:.2f} ms per image')
    print(f'end-to-end saving: back to back {a["back_to_back"]["saving_pct"]:.3f}%, perfect overlap '
          f'{a["perfect_overlap_over_images"]["saving_pct"]:.3f}%, per-layer overlap '
          f'{a["per_layer_overlap"]["saving_pct"]:.3f}% (core alone {a["core_saving_pct"]:.3f}%)')
    j = res['jtag_harness']
    print(f'JTAG harness: xsdb wall {j["xsdb_wall_seconds_sum"]} s for {j["core_seconds_at_50MHz"]} s of core')
    print(f'wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out} in {time.time()-t0:.0f} s')


if __name__ == '__main__':
    main()
