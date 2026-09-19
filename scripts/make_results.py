"""Summarise a run_stream_checks build directory into a v1/v2/v3/v4 comparison table.

Usage: python scripts/make_results.py build/stream_<stamp> [--json out.json]
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('build', type=Path)
    ap.add_argument('--json', type=Path, default=None)
    args = ap.parse_args()
    summary = json.loads((args.build/'summary.json').read_text(encoding='utf-8'))
    by_cfg = defaultdict(dict)
    banked = []
    for case in summary['cases']:
        if not case['vector'] in ('calibration', 'evaluation'):
            continue
        key = (case['vector'], case['P'], case['DEPTH'], case['STALL_LEN'])
        if case['IMPL'] == 3:
            banked.append(case)
        else:
            by_cfg[key][case['IMPL']] = case
    rows = []
    print(f'{"data":<12}{"P":>3}{"D":>3}{"stall":>6} | {"v1 serial":>10}{"v2 cont.":>10}{"v3 overlap":>11} | '
          f'{"v3 vs v2":>9}{"v3 vs v1":>9} | {"v3 dense lat":>13}{"v3 sparse lat":>14}')
    for key in sorted(by_cfg):
        cases = by_cfg[key]
        per = {impl: c['cycles_per_window'] for impl, c in cases.items()}
        v3 = cases.get(2)
        row = dict(vector=key[0], P=key[1], DEPTH=key[2], stall=key[3],
                   cycles_per_window={f'v{i+1}': per[i] for i in sorted(per)},
                   windows=next(iter(cases.values()))['windows'])
        if v3:
            row['v3_mean_dense_latency'] = v3['mean_dense_latency']
            row['v3_mean_sparse_latency'] = v3['mean_sparse_latency']
        if 1 in per and 2 in per:
            row['v3_vs_v2_pct'] = 100*(1-per[2]/per[1])
        if 0 in per and 2 in per:
            row['v3_vs_v1_pct'] = 100*(1-per[2]/per[0])
        rows.append(row)
        f = lambda v: f'{v:>10.1f}' if v is not None else f'{"-":>10}'
        print(f'{key[0]:<12}{key[1]:>3}{key[2]:>3}{key[3]:>6} | {f(per.get(0))}{f(per.get(1))}{f(per.get(2)):>11} | '
              f'{row.get("v3_vs_v2_pct", float("nan")):>8.2f}%{row.get("v3_vs_v1_pct", float("nan")):>8.2f}% | '
              f'{(v3 or {}).get("mean_dense_latency") or float("nan"):>13.1f}{(v3 or {}).get("mean_sparse_latency") or float("nan"):>14.1f}')
    print('\ncycles per window = stream total / (512 windows x 2 modes); dense and sparse windows alternate in the stream.')
    if banked:
        # A v4 core at (P, T) spends P*T multipliers, so the comparison that carries a
        # hardware claim is against v3 at P*T lanes ("iso"), not against v3 at P lanes.
        # The same-P column is kept because it isolates what banking does at a fixed
        # lane count, but it compares different amounts of hardware.
        print(f'\n{"data":<12}{"P":>3}{"D":>3}{"stall":>6}{"T":>3} | {"v4 banked":>10}{"v3 same P":>11}{"v3 iso":>10} | '
              f'{"vs same P":>10}{"vs iso":>8} | {"mults P*T":>10}{"v4 sparse lat":>14}')
        for case in sorted(banked, key=lambda c: (c['vector'], c['P'], c['STALL_LEN'], c['T'])):
            key = (case['vector'], case['P'], case['DEPTH'], case['STALL_LEN'])
            mults = case['P']*case['T']
            ref = by_cfg.get(key, {})
            v3 = ref.get(2, {}).get('cycles_per_window')
            v2 = ref.get(1, {}).get('cycles_per_window')
            iso = by_cfg.get((key[0], mults, key[2], key[3]), {}).get(2, {}).get('cycles_per_window')
            row = dict(vector=key[0], P=key[1], DEPTH=key[2], stall=key[3], T=case['T'],
                       v4_cycles_per_window=case['cycles_per_window'], multipliers=mults,
                       v3_same_lanes_cycles_per_window=v3, v3_iso_multiplier_cycles_per_window=iso,
                       v4_mean_dense_latency=case['mean_dense_latency'],
                       v4_mean_sparse_latency=case['mean_sparse_latency'])
            if v3:
                row['v4_vs_v3_same_lanes_pct'] = 100*(1-case['cycles_per_window']/v3)
            if v2:
                row['v4_vs_v2_pct'] = 100*(1-case['cycles_per_window']/v2)
            if iso:
                row['v4_vs_v3_iso_multiplier_pct'] = 100*(1-case['cycles_per_window']/iso)
            rows.append(row)
            print(f'{key[0]:<12}{key[1]:>3}{key[2]:>3}{key[3]:>6}{case["T"]:>3} | {case["cycles_per_window"]:>10.1f}'
                  f'{(v3 or float("nan")):>11.1f}{(iso or float("nan")):>10.1f} | '
                  f'{row.get("v4_vs_v3_same_lanes_pct", float("nan")):>9.2f}%'
                  f'{row.get("v4_vs_v3_iso_multiplier_pct", float("nan")):>7.2f}% | {mults:>10}'
                  f'{case["mean_sparse_latency"] or float("nan"):>14.1f}')
        print('\n"v3 same P" uses the same lane count as v4 and therefore FEWER multipliers (P vs P*T);'
              '\nthat column is not a hardware comparison. "v3 iso" is v3 at P*T lanes, the same multiplier'
              '\nbudget as the v4 row, and a negative "vs iso" means v4 needs more cycles for the same hardware.')
    if args.json:
        args.json.write_text(json.dumps(dict(build=str(args.build), utc=summary['utc'], rows=rows), indent=2)+'\n', encoding='utf-8')
        print(f'wrote {args.json}')


if __name__ == '__main__':
    main()
