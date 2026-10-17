"""The four-wide (W=4) board runs against the prediction made before they existed.

    python denoise/compare_w4.py          # writes denoise/w4_measured.json

Reads denoise/w4_prediction.json (committed before the W=4 bitstream was built,
predict_w4.py) and denoise/board_runs/<model>_05_w4.json (RUN_W4_DENOISE.cmd), and
prints, per network and per layer, measured against predicted core cycles, the
stall counters, and the two ratios the paper's claims rest on.

Fixed before any W=4 measurement, so the reading cannot drift toward the result:

  - A measurement counts only if its core ID has bit 9 set (the W=4 bitstream)
    and every layer was compared bit for bit with the host oracle (run_denoise
    stops otherwise).
  - IN_STALL > 0 means the DMA did not deliver a beat every cycle, and CYCLES
    then measures the DMA as well as the core. Such a layer is reported, and
    flagged, not corrected.
  - The prediction leaves out each layer's pipeline fill and drain (tens to a
    few hundred cycles), as the W=1 check in predict_w4.py did; a gap of that
    size is agreement.
  - Claim "with four values per cycle the 6.4x larger network B becomes slower
    than the baseline A": B/A > 1 in cycles per pixel.
  - Claim "pooling stops being free": maxout/ReLU > 1.5 in cycles per pixel
    (1.01 on the one-value port).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', type=Path, default=HERE/'board_runs')
    ap.add_argument('--out', type=Path, default=HERE/'w4_measured.json')
    args = ap.parse_args()
    pred = json.loads((HERE/'w4_prediction.json').read_text())
    out = dict(prediction='denoise/w4_prediction.json', networks={}, ratios={}, claims={})
    per_px = {}
    missing = []
    for label, p in pred['networks'].items():
        f = args.runs/f'{p["model"]}_05_w4.json'
        if not f.exists():
            missing.append(str(f))
            continue
        rep = json.loads(f.read_text())
        img = rep['images'][0]
        if rep.get('emulated') or img['image'] != pred['image']:
            raise SystemExit(f'{f}: not a board run of {pred["image"]}')
        layers = img['layers']
        ids = {c for L in layers for c in L.get('core_id', [])}
        if not ids or not all(int(c, 16) >> 9 & 1 for c in ids):
            raise SystemExit(f'{f}: core ID {sorted(ids)} is not the four-wide bitstream')
        rows = []
        if len(layers) != len(p['layers']):
            raise SystemExit(f'{f}: {len(layers)} layers, the prediction has {len(p["layers"])}')
        for L, q in zip(layers, p['layers']):
            assert L['name'] == q['name'] and L['windows'] == q['windows'], (L['name'], q['name'])
            rows.append(dict(name=L['name'], K=L['K'], COUT=L['COUT'], windows=L['windows'],
                             measured=L['cycles'], predicted=q['predicted_w4'],
                             gap=L['cycles']-q['predicted_w4'], board_w1=q['board_w1'],
                             in_stall=L['in_stall'], out_stall=L['out_stall']))
        meas = sum(r['measured'] for r in rows)
        rec = dict(model=p['model'], core_id=sorted(ids), fclk_mhz=sorted({c for L in layers for c in L['fclk_mhz']}),
                   measured_total=meas, predicted_total=p['predicted_w4_total'],
                   gap=meas-p['predicted_w4_total'],
                   gap_percent=100*(meas-p['predicted_w4_total'])/p['predicted_w4_total'],
                   board_w1_total=p['board_w1_total'], speedup_over_w1=p['board_w1_total']/meas,
                   per_pixel=dict(measured=meas/p['pixels'], predicted=p['per_pixel']['predicted_w4'],
                                  board_w1=p['per_pixel']['board_w1']),
                   in_stall=sum(r['in_stall'] for r in rows), out_stall=sum(r['out_stall'] for r in rows),
                   psnr_denoised=img['psnr_denoised'], layers=rows)
        out['networks'][label] = rec
        per_px[label] = rec['per_pixel']['measured']
        print(f'\n{label} ({p["model"]})  core ID {", ".join(rec["core_id"])}  {rec["fclk_mhz"]} MHz  '
              f'PSNR {rec["psnr_denoised"]:.2f} dB')
        print(f'  {"layer":<7}{"K":>5}{"COUT":>5}{"measured":>13}{"predicted":>13}{"gap":>7}'
              f'{"W=1 board":>13}{"in_stall":>10}{"out_stall":>10}')
        for r in rows:
            flag = '  waited on the DMA' if r['in_stall'] else ''
            print(f'  {r["name"]:<7}{r["K"]:>5}{r["COUT"]:>5}{r["measured"]:>13,}{r["predicted"]:>13,}'
                  f'{r["gap"]:>7}{r["board_w1"]:>13,}{r["in_stall"]:>10,}{r["out_stall"]:>10,}{flag}')
        print(f'  total {meas:,} measured, {p["predicted_w4_total"]:,} predicted '
              f'({rec["gap_percent"]:+.3f}%), {rec["per_pixel"]["measured"]:.1f} cycles/px; '
              f'{rec["speedup_over_w1"]:.2f}x fewer cycles than W=1 ({p["per_pixel"]["board_w1"]:.1f}/px)')
    if missing:
        print('\nnot measured yet: ' + ', '.join(missing))
    have = lambda *ks: all(k in per_px for k in ks)
    if have('A', 'B + QAT'):
        out['ratios']['B/A'] = dict(measured=per_px['B + QAT']/per_px['A'],
                                    predicted=pred['ratios']['B/A at W=4 (predicted)'],
                                    board_w1=pred['ratios']['B/A at W=1 (board)'])
        out['claims']['B slower than A at W=4 (B/A > 1)'] = out['ratios']['B/A']['measured'] > 1
    if have('B-32 maxout + QAT', 'B-32 ReLU + QAT'):
        out['ratios']['maxout/ReLU'] = dict(measured=per_px['B-32 maxout + QAT']/per_px['B-32 ReLU + QAT'],
                                            predicted=pred['ratios']['maxout/ReLU at W=4 (predicted)'],
                                            board_w1=pred['ratios']['maxout/ReLU at W=1 (board)'])
        out['claims']['pooling not free at W=4 (maxout/ReLU > 1.5)'] = out['ratios']['maxout/ReLU']['measured'] > 1.5
    if out['ratios']:
        print()
        for k, v in out['ratios'].items():
            print(f'{k:<12} measured {v["measured"]:.3f}   predicted {v["predicted"]:.3f}   '
                  f'W=1 board {v["board_w1"]:.3f}')
        for k, v in out['claims'].items():
            print(f'{k}: {"holds" if v else "DOES NOT HOLD"}')
    if any(n['in_stall'] for n in out['networks'].values()):
        print('\nSome layers waited on the DMA (in_stall > 0): their cycles include it.')
    args.out.write_text(json.dumps(out, indent=2)+'\n')
    print(f'\nwrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
