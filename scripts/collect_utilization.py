"""Collect every out-of-context run in build/ into the rows paper/figures/data.py wants.

Reading these by hand is how the numbers went wrong before: the summary table's
"Slice LUTs" is not the same quantity as the hierarchical report's "Total LUTs",
and a DSP-inferred run is not comparable with a DSP-free one. This reads the
hierarchical report's own (top) row, carries the DSP column so the gate is
visible, and pulls WNS from the timing summary.

    python scripts/collect_utilization.py            # every run
    python scripts/collect_utilization.py --dsp-free # only the comparable ones
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Hierarchical report columns, in order, after Instance and Module.
COLS = ['total_luts', 'logic_luts', 'lutrams', 'srls', 'ffs',
        'ramb36', 'ramb18', 'dsp']


def read_settings(d):
    out = {}
    f = d/'settings.txt'
    if not f.exists():
        return out
    for line in f.read_text(errors='replace').splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            out[k.strip()] = v.strip()
    return out


def top_row(rpt):
    """The (top) row of report_utilization -hierarchical."""
    if not rpt.exists():
        return None
    for line in rpt.read_text(errors='replace').splitlines():
        if '(top)' not in line or '|' not in line:
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        nums = [c for c in cells if re.fullmatch(r'-?\d+', c)]
        if len(nums) >= len(COLS):
            return dict(zip(COLS, (int(n) for n in nums[:len(COLS)])))
    return None


def wns(rpt):
    """Worst negative slack from report_timing_summary."""
    if not rpt.exists():
        return None
    lines = rpt.read_text(errors='replace').splitlines()
    for i, line in enumerate(lines):
        if 'WNS(ns)' not in line:
            continue
        for nxt in lines[i+1:i+6]:
            m = re.search(r'(-?\d+\.\d+)', nxt)
            if m:
                return float(m.group(1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dsp-free', action='store_true',
                    help='drop runs where the tool inferred DSP blocks')
    args = ap.parse_args()

    rows = []
    for d in sorted((ROOT/'build').glob('ooc_*')):
        st = read_settings(d)
        for core in sorted(p for p in d.iterdir() if p.is_dir()):
            u = top_row(core/'routed_utilization.rpt')
            if u is None:
                print(f'# {d.name}/{core.name}: no (top) row in routed_utilization.rpt')
                continue
            rows.append(dict(run=d.name, core=core.name,
                             P=st.get('P', '?'), T=st.get('T', '?'),
                             max_dsp=st.get('max_dsp', '?'),
                             wns=wns(core/'routed_timing.rpt'), **u))

    if not rows:
        raise SystemExit('no build/ooc_* runs found -- run RUN_SYNTH.cmd first')

    kept = [r for r in rows if not (args.dsp_free and r['dsp'])]
    name = {'overlapped_window_mac': 'v3', 'banked_window_mac': 'v4',
            'sparse_window_mac': 'v1', 'continuous_window_mac': 'v2'}
    print(f'{"core":>4} {"P":>4} {"T":>3} {"LUT":>7} {"logic":>7} {"LUTRAM":>7} '
          f'{"FF":>7} {"DSP":>4} {"WNS":>7}  max_dsp  run')
    for r in sorted(kept, key=lambda r: (name.get(r['core'], r['core']), int(r['P']))):
        w = f"{r['wns']:+.3f}" if r['wns'] is not None else '   -   '
        print(f"{name.get(r['core'], r['core']):>4} {r['P']:>4} {r['T']:>3} "
              f"{r['total_luts']:>7} {r['logic_luts']:>7} {r['lutrams']:>7} "
              f"{r['ffs']:>7} {r['dsp']:>4} {w:>7}  {r['max_dsp']:>7}  {r['run']}")

    print('\n# rows for paper/figures/data.py UTIL (DSP-free only):')
    for r in sorted(kept, key=lambda r: (name.get(r['core'], r['core']), int(r['P']))):
        if r['dsp']:
            continue
        t = r['T'] if name.get(r['core']) == 'v4' else 1
        print(f'    ("{name.get(r["core"], r["core"])}", {int(r["P"]):3d}, {int(t):2d}, '
              f'"?", {r["total_luts"]:7d}, {r["logic_luts"]:6d}, {r["lutrams"]:6d}, '
              f'{r["ffs"]:6d}, 32, {r["ramb18"]:2d}, {r["dsp"]:2d}),')
    dropped = len(rows) - len(kept)
    if dropped:
        print(f'\n# {dropped} run(s) hidden because the tool inferred DSP blocks')


if __name__ == '__main__':
    main()
