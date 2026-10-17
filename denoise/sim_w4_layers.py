"""RTL simulation of the four-wide (W=4) board build on real windows of every layer.

    python denoise/sim_w4_layers.py                 # writes denoise/w4_rtl_sim.json

Not a board measurement. For each of the four board networks it takes the windows
Set12 05.png gives every layer (the board driver's host emulation, as in
predict_w4.py), picks --windows of them in four contiguous blocks spread over the
layer, and streams them through rtl/window_mac_axis.sv built as the board
bitstream (K=1152, COUT=128, P=16, T=4, IMPL=3, DEPTH=2, runtime geometry) in
sim/tb_axis_wrapper.sv: sparse mode, as every board run, with the zero padding
the host does at W=4 and an unthrottled stream (a DMA that keeps up). The bench
checks every output against the integer oracle and reads the CYCLES register.

The same windows run at W=4 and at W=1. Each total is compared with the
per-window count predict_w4.py made its prediction with (window_cycles), summed
over the same windows. At W=1 that count matched the board on whole layers to
within each layer's fill and drain; here it is checked against the RTL at both
widths on the real data, which no synthetic vector did.

Needs Icarus Verilog (iverilog, vvp). About 40 minutes on 3 cores.
"""
import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'scripts')]
from predict_w4 import MODELS, layer_windows, window_cycles  # noqa: E402
from legacy_run_checks import export_vectors  # noqa: E402

BUILD = dict(KMAX=1152, COUTMAX=128, P=16, DEPTH=2, IMPL=3, T=4, RUNTIME_GEOM=1)
SOURCES = ['rtl/overlapped_window_mac.sv', 'rtl/banked_window_mac.sv', 'rtl/window_mac_axis.sv',
           'sim/tb_axis_wrapper.sv']
PASS_RE = re.compile(r'PASS ALL checked_values=(\d+) windows=(\d+) cycles=(\d+) in_stall=(\d+) out_stall=(\d+)')


def sample(n, want, blocks=4):
    """Indices of `want` windows in `blocks` contiguous runs spread evenly over n."""
    if n <= want:
        return np.arange(n)
    per = want // blocks
    starts = [int(round((2*b+1)*n/(2*blocks) - per/2)) for b in range(blocks)]
    return np.concatenate([np.arange(s, s+per) for s in starts])


def run(dest, vec, k, cout, n, w):
    dest.mkdir(parents=True, exist_ok=True)
    params = dict(K=k, COUT=cout, N=n, MODE_SEQ=1, IN_GAP=0, OUT_GAP=0, EXPECT_CYCLES=0, W=w, **BUILD)
    argv = ['iverilog', '-g2012', '-s', 'tb_axis_wrapper', '-o', str(dest/'sim.vvp')]
    argv += [f'-Ptb_axis_wrapper.{a}={b}' for a, b in params.items()] + [str(ROOT/s) for s in SOURCES]
    subprocess.run(argv, check=True, capture_output=True, text=True)
    out = subprocess.run(['vvp', str(dest/'sim.vvp'), f'+VEC={vec}'], capture_output=True, text=True,
                         cwd=dest).stdout
    (dest/'sim.log').write_text(out)
    m = PASS_RE.search(out)
    if not m:
        raise RuntimeError(f'{dest}: no PASS line\n{out[-2000:]}')
    checked, wins, cyc, ins, outs = map(int, m.groups())
    assert checked == n*cout and wins == n and ins == 0 and outs == 0, (dest, m.group(0))
    return cyc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--windows', type=int, default=256, help='windows per layer (four blocks)')
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--work', type=Path, default=ROOT/'build'/'w4_rtl_sim')
    ap.add_argument('--out', type=Path, default=HERE/'w4_rtl_sim.json')
    args = ap.parse_args()
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--'] + SOURCES,
                           capture_output=True, text=True).stdout.strip()
    jobs, recs = [], {}
    for label, model in MODELS.items():
        got, _ = layer_windows(model)
        recs[label] = dict(model=model, layers=[])
        for L, x in got:
            idx = sample(x.shape[0], args.windows)
            xs = x[idx]
            name = f'{model}_{L["name"]}'
            vec = args.work/name/'vectors'
            export_vectors(vec, xs.astype(int).tolist(), L['wq'].astype(int).tolist(), L['bq'].astype(int).tolist(),
                           source={'model': model, 'layer': L['name'], 'image': '05.png', 'window_index': idx.tolist()})
            row = dict(name=L['name'], K=L['K'], COUT=L['COUT'], windows_in_layer=int(x.shape[0]),
                       windows=int(len(idx)), nonzero_fraction=float((xs != 0).mean()))
            for w in (1, 4):
                row[f'model_w{w}'] = int(window_cycles(xs, L['K'], L['COUT'], w).sum())
                jobs.append((label, len(recs[label]['layers']), w, args.work/name/f'w{w}', vec, L['K'], L['COUT'], len(idx)))
            recs[label]['layers'].append(row)
    print(f'{len(jobs)} simulations', flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(run, d, v, k, c, n, w): (label, i, w) for label, i, w, d, v, k, c, n in jobs}
        for f in concurrent.futures.as_completed(futs):
            label, i, w = futs[f]
            row = recs[label]['layers'][i]
            row[f'rtl_w{w}'] = f.result()
            row[f'gap_w{w}'] = row[f'rtl_w{w}'] - row[f'model_w{w}']
            print(f'  {label:<18} {row["name"]:<7} W={w}: RTL {row[f"rtl_w{w}"]:>8,}  '
                  f'count {row[f"model_w{w}"]:>8,}  gap {row[f"gap_w{w}"]:>4}', flush=True)
    for label, r in recs.items():
        for w in (1, 4):
            r[f'rtl_w{w}'] = sum(l[f'rtl_w{w}'] for l in r['layers'])
            r[f'model_w{w}'] = sum(l[f'model_w{w}'] for l in r['layers'])
        r['rtl_speedup_w1_over_w4'] = r['rtl_w1']/r['rtl_w4']
        gaps = [l['gap_w4'] for l in r['layers']]
        print(f'{label:<18} sampled windows: W=1 RTL {r["rtl_w1"]:,} (count {r["model_w1"]:,}), '
              f'W=4 RTL {r["rtl_w4"]:,} (count {r["model_w4"]:,}); W=4 per-layer gaps {min(gaps)}..{max(gaps)}')
    out = dict(what='RTL simulation (Icarus) of window_mac_axis at the board build, on sampled real windows; '
                    'not a board measurement',
               build=BUILD, image='05.png', mode='sparse (MODE_SEQ=1)', windows_per_layer=args.windows,
               sampling='four contiguous blocks centred at 1/8, 3/8, 5/8, 7/8 of the layer',
               rtl_commit=commit, rtl_sources_modified_since_commit=bool(dirty),
               rtl_sha256={s: hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in SOURCES},
               networks=recs)
    args.out.write_text(json.dumps(out, indent=2)+'\n')
    print('wrote', args.out)


if __name__ == '__main__':
    main()
