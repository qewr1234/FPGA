"""The two-wide (W=2) board runs against the prediction made before they existed.

    python denoise/compare_w2.py          # writes denoise/w2_measured.json

Reads denoise/w2_prediction.json (committed before the W=2 bitstream was built,
predict_w2.py; the per-pixel counts are those of wider_ports.json, commit
55f13b4) and denoise/board_runs/<model>_05_w2.json (RUN_W2_DENOISE.cmd), and
prints, per network and per layer, measured against predicted core cycles, the
stall counters, and the ratios the paper's claims rest on.

Fixed before any W=2 measurement, so the reading cannot drift toward the result:

  - A measurement counts only if its core ID has bit 10 set and bit 9 clear
    (the W=2 bitstream) and every layer was compared bit for bit with the host
    oracle (run_denoise stops otherwise).
  - IN_STALL > 0 means the DMA did not deliver half a beat every cycle, and
    CYCLES then measures the DMA as well as the core. Such a layer is reported,
    and flagged, not corrected.
  - Per network, the total must be within 0.01% of the count (the count leaves
    out each layer's fill and drain, tens to a few hundred cycles).
  - Per layer, except the first, the measured cycles minus IN_STALL must EQUAL
    exact_w2: count + min(load, last) + 19 on hidden layers, + COUT + 3 on the
    last layer. This rule was read off the W=1 and W=4 runs (w4_gaps.py); here
    it is tested on runs it has not seen. Every layer that misses is listed.
  - Claim "with two values per cycle pooling stops being free": maxout/ReLU
    > 1.5 in cycles per pixel (1.01 on the one-value port; predicted 1.546).
  - Claim "with two values per cycle the 6.4x larger network B is still faster
    than the baseline A": B/A < 1 (predicted 0.817; 1.19 at four values).
  - If the 10 x 45 ReLU network was run: "it costs fewer cycles than the
    maxout network of the same parameter count": 45-channel/maxout < 1
    (predicted 0.907; 1.383 on the one-value port).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', type=Path, default=HERE/'board_runs')
    ap.add_argument('--out', type=Path, default=HERE/'w2_measured.json')
    args = ap.parse_args()
    pred = json.loads((HERE/'w2_prediction.json').read_text())
    out = dict(prediction='denoise/w2_prediction.json', networks={}, ratios={}, claims={})
    per_px, missing, misses = {}, [], []
    for label, p in pred['networks'].items():
        f = args.runs/f'{p["model"]}_05_w2.json'
        if not f.exists():
            missing.append(str(f))
            continue
        rep = json.loads(f.read_text())
        img = rep['images'][0]
        if rep.get('emulated') or img['image'] != pred['image']:
            raise SystemExit(f'{f}: not a board run of {pred["image"]}')
        layers = img['layers']
        ids = {c for L in layers for c in L.get('core_id', [])}
        if not ids or not all((int(c, 16) >> 10 & 1) and not (int(c, 16) >> 9 & 1) for c in ids):
            raise SystemExit(f'{f}: core ID {sorted(ids)} is not the two-wide bitstream')
        if len(layers) != len(p['layers']):
            raise SystemExit(f'{f}: {len(layers)} layers, the prediction has {len(p["layers"])}')
        rows = []
        for L, q in zip(layers, p['layers']):
            assert L['name'] == q['name'] and L['windows'] == q['windows'], (L['name'], q['name'])
            row = dict(name=L['name'], K=L['K'], COUT=L['COUT'], kind=q['kind'], windows=L['windows'],
                       measured=L['cycles'], predicted=q['predicted_w2'], gap=L['cycles']-q['predicted_w2'],
                       exact=q.get('exact_w2'), board_w1=q.get('board_w1'),
                       in_stall=L['in_stall'], out_stall=L['out_stall'])
            if row['exact'] is not None:
                row['exact_holds'] = (L['cycles'] - L['in_stall'] == row['exact'])
                if not row['exact_holds']:
                    misses.append(f'{label} {L["name"]}: {L["cycles"]} - {L["in_stall"]} stalled, '
                                  f'exact {row["exact"]}')
            rows.append(row)
        meas = sum(r['measured'] for r in rows)
        tot = p['predicted_w2_total']
        rec = dict(model=p['model'], core_id=sorted(ids), fclk_mhz=sorted({c for L in layers for c in L['fclk_mhz']}),
                   measured_total=meas, predicted_total=tot, gap=meas-tot, gap_percent=100*(meas-tot)/tot,
                   within_0_01_percent=abs(meas-tot) <= 1e-4*tot,
                   board_w1_total=p.get('board_w1_total'),
                   per_pixel=dict(measured=meas/p['pixels'], predicted=p['per_pixel']['predicted_w2'],
                                  board_w1=p['per_pixel'].get('board_w1')),
                   in_stall=sum(r['in_stall'] for r in rows), out_stall=sum(r['out_stall'] for r in rows),
                   exact_layers=f'{sum(r.get("exact_holds", False) for r in rows)}/'
                                f'{sum(r["exact"] is not None for r in rows)}',
                   psnr_denoised=img['psnr_denoised'], layers=rows)
        out['networks'][label] = rec
        per_px[label] = rec['per_pixel']['measured']
        print(f'\n{label} ({p["model"]})  core ID {", ".join(rec["core_id"])}  {rec["fclk_mhz"]} MHz  '
              f'PSNR {rec["psnr_denoised"]:.2f} dB')
        print(f'  {"layer":<7}{"K":>5}{"COUT":>5}{"measured":>13}{"predicted":>13}{"gap":>7}{"exact":>13}'
              f'{"in_stall":>10}{"out_stall":>10}')
        for r in rows:
            flag = '  waited on the DMA' if r['in_stall'] else ''
            ex = '-' if r['exact'] is None else f'{r["exact"]:,}' + ('' if r['exact_holds'] else ' MISS')
            print(f'  {r["name"]:<7}{r["K"]:>5}{r["COUT"]:>5}{r["measured"]:>13,}{r["predicted"]:>13,}'
                  f'{r["gap"]:>7}{ex:>13}{r["in_stall"]:>10,}{r["out_stall"]:>10,}{flag}')
        print(f'  total {meas:,} measured, {tot:,} predicted ({rec["gap_percent"]:+.4f}%), '
              f'{rec["per_pixel"]["measured"]:.1f} cycles/px; exact per layer {rec["exact_layers"]}')
    if missing:
        print('\nnot measured yet: ' + ', '.join(missing))
    have = lambda *ks: all(k in per_px for k in ks)
    r2 = pred['ratios']['W=2']
    if have('A', 'B + QAT'):
        out['ratios']['B/A'] = dict(measured=per_px['B + QAT']/per_px['A'], predicted=r2['B/A'])
        out['claims']['B still faster than A at W=2 (B/A < 1)'] = out['ratios']['B/A']['measured'] < 1
    if have('B-32 maxout + QAT', 'B-32 ReLU + QAT'):
        out['ratios']['maxout/ReLU'] = dict(measured=per_px['B-32 maxout + QAT']/per_px['B-32 ReLU + QAT'],
                                            predicted=r2['maxout/ReLU'])
        out['claims']['pooling not free at W=2 (maxout/ReLU > 1.5)'] = out['ratios']['maxout/ReLU']['measured'] > 1.5
    if have('10 x 45 ReLU + QAT', 'B-32 maxout + QAT'):
        out['ratios']['45-channel/maxout'] = dict(
            measured=per_px['10 x 45 ReLU + QAT']/per_px['B-32 maxout + QAT'], predicted=r2['45-channel/maxout'])
        out['claims']['45-channel ReLU cheaper than maxout at W=2 (< 1)'] = \
            out['ratios']['45-channel/maxout']['measured'] < 1
    out['claims']['every total within 0.01% of the count'] = all(n['within_0_01_percent'] for n in out['networks'].values())
    out['claims']['every exact per-layer number holds'] = not misses
    out['exact_misses'] = misses
    print()
    for k, v in out['ratios'].items():
        print(f'{k:<18} measured {v["measured"]:.3f}   predicted {v["predicted"]:.3f}')
    for k, v in out['claims'].items():
        print(f'{k}: {"holds" if v else "DOES NOT HOLD"}')
    for m in misses:
        print('  exact miss: ' + m)
    if any(n['in_stall'] for n in out['networks'].values()):
        print('\nSome layers waited on the DMA (in_stall > 0): their cycles include it.')
    args.out.write_text(json.dumps(out, indent=2)+'\n')
    print(f'\nwrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
