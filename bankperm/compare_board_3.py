"""The L3 board runs (bankperm/PROTOCOL_2_ADDENDUM.md) against their exact prediction and the PROTOCOL_2 runs.

    python bankperm/compare_board_3.py                              # writes bankperm/board_measured_3.json
    python bankperm/compare_board_3.py --run-state DIR --image 05.png   # RUN_W4_L3.cmd, before a run
    python bankperm/compare_board_3.py --check-run DIR --image 05.png   # RUN_W4_L3.cmd, after it
    python bankperm/compare_board_3.py --canary DIR --image 05.png      # RUN_W4_L3.cmd, 05.png against its prediction

Reads denoise/board_runs/q1_layouts3/l3_<image stem>/report.json (scripts/run_denoise.py
on the W=4 bitstream with --export-dir build/layout_exports/l3, RUN_W4_L3.cmd) for Set12
05.png, 06.png, 07.png, 08.png, whichever are there, and bankperm/board_prediction_3.json
(the exact per-layer cycles committed before the runs). It is a separate script from
bankperm/compare_board_2.py, whose behaviour for the PROTOCOL_2 runs is unchanged; it
uses that script's helpers as they are.

Every run is first checked as compare_board_2.py checks a PROTOCOL_2 run: a board run (not
emulated), this model, Set12, W=4, sparse mode, one board run per layer, no mismatches,
core ID 0x4d410303 and 50 MHz on every layer, the L3 export (export_dir ending in
layout_exports/l3), and conv2..conv9 (and only they) marked taps_reordered. A run that
fails a check is listed and left out of the comparison.

Per run and layer: CYCLES, IN_STALL, OUT_STALL, the exact prediction, and match =
(CYCLES - IN_STALL == exact), the test of PROTOCOL_2 (this bitstream's IN_STALL does not
count starvation at window boundaries). Then the totals, L3's own count of the image in
bankperm/results_2.json (fill and drain left out) beside them, every miss, and the saving
of L3 against the Original and the Skew of the same image from the PROTOCOL_2 board runs
(denoise/board_runs/q1_layouts2/<layout>_<stem>, each checked with compare_board_2.validate;
their predictions from bankperm/board_prediction_2.json) when those runs are there: measured
CYCLES, CYCLES - IN_STALL and predicted, in total and per layer. Whether the two folders'
setup.json pin the same bitstream and driver is recorded.

The prediction of a run is read from exactly one place,
predictions["l3"][<image>]["layers"] of the prediction file, which must hold an int for
each of conv1..conv10; otherwise the run is listed as unpredicted, with the reason. The
prediction file is identified by its git blob id and SHA-256 with CRLF read as LF, and
compared with the one bankperm/prepare_l3.py pinned in denoise/board_runs/q1_layouts3/
setup.json before the first run.

--run-state exits 10 if DIR holds a complete run that passes the checks (the run is
skipped); otherwise it moves DIR, if it exists, to
denoise/board_runs/q1_layouts3_attempts/<name>_attempt<N> (kept, not deleted) and exits 0.
--check-run exits 10 if the run passes, 1 if not. --canary compares a run that passes the
checks with its prediction, layer by layer: exit 10 if every layer is exact, 11 if any
misses (the layers are printed). Any other exit code is an error.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE)]
import compare_board_2 as cb2  # noqa: E402 (used unchanged)

MODEL = cb2.MODEL
LAYOUT = 'l3'
IMAGES = cb2.IMAGES
LAYERS = cb2.LAYERS
SKEWED = cb2.SKEWED                                       # conv2..conv9, as export_layout.py skews this model
CORE_ID = cb2.CORE_ID
FCLK_MHZ = cb2.FCLK_MHZ
RUNS = ROOT/'denoise'/'board_runs'/'q1_layouts3'
ATTEMPTS = ROOT/'denoise'/'board_runs'/'q1_layouts3_attempts'
PREDICTION = HERE/'board_prediction_3.json'
OUT = HERE/'board_measured_3.json'
Q2_RUNS = cb2.RUNS                                        # denoise/board_runs/q1_layouts2
PREDICTION_2 = cb2.PREDICTION
RESULTS_2 = HERE/'results_2.json'
RESULTS_2_LABEL = 'B-32 ReLU + QAT s1'
AGAINST = ('original', 'skew')
SETUP = cb2.SETUP
DONE = cb2.DONE
MISSED = cb2.MISSED
rel = cb2.rel


def run_name(image):
    return f'{LAYOUT}_{image[:-4]}'


def validate(rep, image):
    """What is wrong with report.json `rep` as the L3 run of `image` (empty: nothing)."""
    bad = []

    def need(cond, msg):
        if not cond:
            bad.append(msg)
    need(rep.get('emulated') is False, 'not a board run (emulated)')
    need(rep.get('model') == MODEL, f'model {rep.get("model")}')
    need(rep.get('set') == 'Set12', f'set {rep.get("set")}')
    need(rep.get('activations_per_cycle') == 4, f'activations_per_cycle {rep.get("activations_per_cycle")}, not 4')
    need(rep.get('mode_seq') == 1, f'mode_seq {rep.get("mode_seq")}, not 1 (sparse)')
    need(rep.get('mismatches') == 0, f'mismatches {rep.get("mismatches")}')
    parts = cb2.path_parts(rep.get('export_dir', ''))
    want = ['layout_exports', LAYOUT]
    need(parts[-len(want):] == want, f'export_dir {rep.get("export_dir")} is not the L3 export (.../{"/".join(want)})')
    ims = rep.get('images') or []
    need(len(ims) == 1, f'{len(ims)} images in one report')
    if len(ims) != 1:
        return bad
    im = ims[0]
    need(im.get('image') == image, f'image {im.get("image")}, not {image}')
    need(im.get('start_layer') == 1, f'started at layer {im.get("start_layer")}')
    layers = im.get('layers') or []
    need([L.get('name') for L in layers] == list(LAYERS), f'layers {[L.get("name") for L in layers]}')
    for L in layers:
        n = L.get('name')
        need(L.get('emulated') is False and L.get('mismatches') == 0, f'{n}: emulated or mismatches')
        need(L.get('core_id') == [CORE_ID], f'{n}: core ID {L.get("core_id")}, not [{CORE_ID}]')
        f = L.get('fclk_mhz') or []
        need(len(f) == 1 and abs(f[0] - FCLK_MHZ) < 0.01, f'{n}: PL clock {f} MHz, not {FCLK_MHZ}')
        need(L.get('runs') == 1, f'{n}: {L.get("runs")} board runs (the prediction has one fill and drain)')
        need(all(isinstance(L.get(k), int) for k in ('cycles', 'in_stall', 'out_stall')), f'{n}: no counters')
        reordered = bool(L.get('taps_reordered'))
        need(reordered == (n in SKEWED), f'{n}: taps_reordered {reordered}, expected {n in SKEWED}')
    return bad


def load_prediction(path=None):
    return cb2.load_prediction(path or PREDICTION)


def prediction_of(pred, image):
    """{layer: exact} of one L3 run, from predictions["l3"][image]["layers"] only. -> (dict, None) or (None, why)."""
    where = f'predictions/{LAYOUT}/{image}/layers'
    try:
        node = pred['predictions'][LAYOUT][image]['layers']
    except (KeyError, TypeError):
        return None, f'no {where} in the prediction file'
    if not isinstance(node, dict) or sorted(node) != sorted(LAYERS):
        return None, f'{where} does not hold exactly {LAYERS[0]}..{LAYERS[-1]}'
    bad = [k for k in LAYERS if not isinstance(node[k], int) or isinstance(node[k], bool)]
    if bad:
        return None, f'{where}: not an integer on {bad}'
    return {k: node[k] for k in LAYERS}, None


def totals(rows):
    tot = dict(cycles=sum(r['cycles'] for r in rows), in_stall=sum(r['in_stall'] for r in rows),
               out_stall=sum(r['out_stall'] for r in rows))
    tot['cycles_minus_in_stall'] = tot['cycles'] - tot['in_stall']
    if rows and all(r['exact'] is not None for r in rows):
        tot['exact'] = sum(r['exact'] for r in rows)
        tot['difference'] = tot['cycles_minus_in_stall'] - tot['exact']
    return tot


def canary(d, image, pred_path=None):
    """A finished L3 run against its prediction, layer by layer, before the other runs start."""
    rep, why = cb2.load_report(d)
    problems = [why] if why else validate(rep, image)
    if problems:
        print(f'{LAYOUT} {image}: the run in {rel(d)} does not pass the checks:')
        for p in problems:
            print('  ' + p)
        return 1
    pred = load_prediction(pred_path)
    exact, why = prediction_of(pred, image) if pred is not None else (None, f'no {rel(pred_path or PREDICTION)}')
    if exact is None:
        print(f'{LAYOUT} {image}: no prediction to compare with ({why})')
        return 1
    rows = cb2.run_rows(rep, exact)
    for r in rows:
        print(f'  {r["name"]:<7} cycles {r["cycles"]:>9,}  in_stall {r["in_stall"]:>4}  out_stall {r["out_stall"]:>4}  '
              f'predicted {r["exact"]:>9,}  difference {r["difference"]:>+6}  {"exact" if r["match"] else "MISS"}')
    bad = [r['name'] for r in rows if not r['match']]
    if bad:
        print(f'{LAYOUT} {image}: CYCLES - IN_STALL is not the prediction on {", ".join(bad)}')
        return MISSED
    print(f'{LAYOUT} {image}: every layer exact (CYCLES - IN_STALL == prediction)')
    return DONE


def run_state(d, image, move, attempts=ATTEMPTS):
    rep, why = cb2.load_report(d)
    problems = [why] if why else validate(rep, image)
    if not problems:
        print(f'{LAYOUT} {image}: complete run in {rel(d)}, checks pass')
        return DONE
    if not move:
        print(f'{LAYOUT} {image}: the run in {rel(d)} does not pass:')
        for p in problems:
            print('  ' + p)
        return 1
    if d.is_dir() and not any(d.iterdir()):
        d.rmdir()                                   # an empty folder holds nothing to keep
    elif d.exists():
        attempts.mkdir(parents=True, exist_ok=True)
        k = 1
        while (attempts/f'{d.name}_attempt{k}').exists():
            k += 1
        dest = attempts/f'{d.name}_attempt{k}'
        shutil.move(str(d), str(dest))
        print(f'{LAYOUT} {image}: {rel(d)} held an unfinished or failing run ({problems[0]}); kept as {rel(dest)}')
    return 0


def results_2_counts(path=RESULTS_2):
    """{image: {L0, L1, L2, L3: W=4 count}} of B-32 ReLU s1 on Set12 05-08 (bankperm/results_2.json)."""
    if not Path(path).is_file():
        return {}
    net = json.loads(Path(path).read_text(encoding='utf-8'))['networks'][RESULTS_2_LABEL]
    assert net['model'] == MODEL
    out = {}
    for im in IMAGES:
        w4 = net['per_image_totals'][f'Set12/{im}']['w4']
        out[im] = {lay: w4[net['layouts'].index(lay)] for lay in ('L0', 'L1', 'L2', 'L3')}
    return out


def setup_of(d):
    p = Path(d)/SETUP
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def pct(a, b):
    return cb2.pct(a, b)


def against_q2(q2_runs, pred2):
    """The Original and Skew runs of the same images (PROTOCOL_2), checked as compare_board_2.py checks them."""
    out, invalid = {}, {}
    for im in IMAGES:
        for lay in AGAINST:
            name = f'{lay}_{im[:-4]}'
            d = q2_runs/name
            if not d.is_dir():
                continue
            rep, why = cb2.load_report(d)
            problems = [why] if why else cb2.validate(rep, lay, im)
            if problems:
                invalid[name] = problems
                continue
            exact, _ = cb2.prediction_of(pred2, lay, im) if pred2 is not None else (None, None)
            rows = cb2.run_rows(rep, exact or {})
            out.setdefault(im, {})[lay] = dict(run=rel(d), layers=rows, total=totals(rows),
                                               layers_matched=sum(r['match'] is True for r in rows))
    return out, invalid


def savings(l3, other):
    """L3 against another run of the same image: total and per layer."""
    a, b = other['total'], l3['total']
    row = dict(cycles=a['cycles'] - b['cycles'], cycles_pct=pct(a['cycles'], b['cycles']),
               cycles_minus_in_stall=a['cycles_minus_in_stall'] - b['cycles_minus_in_stall'],
               cycles_minus_in_stall_pct=pct(a['cycles_minus_in_stall'], b['cycles_minus_in_stall']))
    if 'exact' in a and 'exact' in b:
        row.update(predicted=a['exact'] - b['exact'], predicted_pct=pct(a['exact'], b['exact']))
    row['layers'] = [dict(name=x['name'], cycles=x['cycles'] - y['cycles'], cycles_pct=pct(x['cycles'], y['cycles']),
                          cycles_minus_in_stall=x['cycles_minus_in_stall'] - y['cycles_minus_in_stall'])
                     for x, y in zip(other['layers'], l3['layers'])]
    return row


def pooled(res, images):
    """Summed over `images` where L3 and the other run are both there."""
    out = {}
    for lay in AGAINST:
        ims = [im for im in images if run_name(im) in res['runs'] and lay in res['against_protocol_2_runs'].get(im, {})]
        if not ims:
            continue
        a = sum(res['against_protocol_2_runs'][im][lay]['total']['cycles'] for im in ims)
        b = sum(res['runs'][run_name(im)]['total']['cycles'] for im in ims)
        a1 = sum(res['against_protocol_2_runs'][im][lay]['total']['cycles_minus_in_stall'] for im in ims)
        b1 = sum(res['runs'][run_name(im)]['total']['cycles_minus_in_stall'] for im in ims)
        out[lay] = dict(images=ims, cycles=a - b, cycles_pct=pct(a, b), cycles_minus_in_stall=a1 - b1,
                        cycles_minus_in_stall_pct=pct(a1, b1))
    return out


def compare(runs_dir, pred_path, attempts=ATTEMPTS, q2_runs=Q2_RUNS, pred2_path=PREDICTION_2, results_2=RESULTS_2):
    pred = load_prediction(pred_path)
    setup = setup_of(runs_dir)                       # RUN_W4_L3.cmd, prepare_l3.py --bitstream --record
    pinned = (setup or {}).get('prediction') or {}
    pr = dict(file=rel(pred_path), present=pred is not None)
    if pred is not None:
        pr.update(cb2.text_digest(pred_path), written_utc=pred.get('written_utc'),
                  all_checks_passed=pred.get('all_checks_passed'))
        pr['pinned_before_the_runs'] = pinned.get('git_blob')
        pr['same_as_pinned'] = None if not pinned else pinned.get('git_blob') == pr['git_blob']
        pr['committed_in'] = pinned.get('committed_in')
        pr['committed_at'] = pinned.get('committed_at')
    counts = results_2_counts(results_2)
    res = dict(what='L3 board runs (PROTOCOL_2_ADDENDUM.md, W=4 bitstream) against the exact per-layer prediction, '
                    'and against the Original and Skew runs of PROTOCOL_2',
               model=MODEL, layout='L3 (skew + relabeling, bankperm/perms_2.json)', core_id=CORE_ID, fclk_mhz=FCLK_MHZ,
               runs_dir=rel(runs_dir), match_rule='CYCLES - IN_STALL == exact', prediction=pr,
               runs={}, invalid_runs={}, missing_runs=[], ignored=[], misses=[], unpredicted=[])
    known = {run_name(im): im for im in IMAGES}
    if runs_dir.is_dir():
        res['ignored'] = sorted(p.name for p in runs_dir.iterdir() if p.name not in known and p.name != SETUP)
    res['setup'] = setup
    for name, im in known.items():
        d = runs_dir/name
        if not d.is_dir():
            res['missing_runs'].append(name)
            continue
        rep, why = cb2.load_report(d)
        problems = [why] if why else validate(rep, im)
        if problems:
            res['invalid_runs'][name] = problems
            continue
        exact, why = prediction_of(pred, im) if pred is not None else (None, 'no prediction file')
        if exact is None:
            res['unpredicted'].append(dict(run=name, why=why))
        rows = cb2.run_rows(rep, exact or {})
        for row in rows:
            if row['exact'] is not None and not row['match']:
                res['misses'].append(dict(run=name, image=im, layer=row['name'], cycles=row['cycles'],
                                          in_stall=row['in_stall'], out_stall=row['out_stall'], exact=row['exact'],
                                          difference=row['difference']))
        tot = totals(rows)
        if im in counts:
            c = counts[im]['L3']
            tot['count_w4_results_2'] = c
            tot['cycles_minus_in_stall_minus_count'] = tot['cycles_minus_in_stall'] - c
            if 'exact' in tot:
                tot['predicted_fill_drain'] = tot['exact'] - c
        res['runs'][name] = dict(layout=LAYOUT, image=im, export_dir=rep['export_dir'],
                                 prediction_read_from=None if exact is None else f'predictions/{LAYOUT}/{im}/layers',
                                 layers=rows, total=tot,
                                 layers_matched=sum(r['match'] is True for r in rows),
                                 layers_predicted=sum(r['exact'] is not None for r in rows))
    pred2 = cb2.load_prediction(pred2_path)
    q2, q2_invalid = against_q2(q2_runs, pred2)
    res['against_protocol_2_runs'] = q2
    res['protocol_2_runs_invalid'] = q2_invalid
    q2_setup = setup_of(q2_runs)
    bit = lambda s: ((s or {}).get('files') or {}).get('system_wrapper.bit', {}).get('sha256')   # noqa: E731
    res['protocol_2_setup'] = dict(
        file=rel(q2_runs/SETUP), present=q2_setup is not None,
        same_bitstream=None if not (setup and q2_setup) else bit(setup) == bit(q2_setup),
        same_driver=None if not (setup and q2_setup) else setup.get('code') == q2_setup.get('code'),
        prediction_2=dict(file=rel(pred2_path), present=pred2 is not None,
                          **({} if pred2 is None else cb2.text_digest(pred2_path))))
    sav = {}
    for im in IMAGES:
        r = res['runs'].get(run_name(im))
        if not r:
            continue
        for lay, other in q2.get(im, {}).items():
            row = savings(r, other)
            if im in counts:
                o = counts[im]['L0' if lay == 'original' else 'L2']
                row.update(count_w4=o - counts[im]['L3'], count_w4_pct=pct(o, counts[im]['L3']))
            sav.setdefault(im, {})[lay] = row
    res['l3_savings'] = sav
    res['l3_savings_pooled'] = dict(all_images=pooled(res, IMAGES), images_06_08=pooled(res, IMAGES[1:]))
    res['results_2_counts_w4'] = dict(file=rel(results_2), network=RESULTS_2_LABEL,
                                      note='per-window count summed over conv1-conv10, fill and drain left out',
                                      images=counts)
    pred_rows = [r for run in res['runs'].values() for r in run['layers'] if r['exact'] is not None]
    hidden = [r for r in pred_rows if r['name'] != 'conv1']
    res['summary'] = dict(
        runs_planned=len(known), runs_valid=len(res['runs']), runs_invalid=len(res['invalid_runs']),
        runs_missing=len(res['missing_runs']), layers_compared=len(pred_rows),
        layers_exact=sum(r['match'] for r in pred_rows), conv2_10_compared=len(hidden),
        conv2_10_exact=sum(r['match'] for r in hidden), conv1_compared=len(pred_rows) - len(hidden),
        conv1_exact=sum(r['match'] for r in pred_rows if r['name'] == 'conv1'), misses=len(res['misses']),
        runs_unpredicted=len(res['unpredicted']),
        protocol_2_runs_compared=sum(len(v) for v in q2.values()), protocol_2_runs_invalid=len(q2_invalid))
    s = res['summary']
    if pred is None:
        verdict = f'NO PREDICTION FILE ({rel(pred_path)}): measured numbers only'
    elif not s['layers_compared']:
        verdict = 'NOTHING COMPARED'
    elif s['misses']:
        verdict = f'{s["misses"]} MISS(ES): {s["layers_exact"]}/{s["layers_compared"]} layers exact'
    else:
        verdict = f'ALL EXACT: {s["layers_exact"]}/{s["layers_compared"]} layers'
    if s['layers_compared']:
        verdict += (f' (conv2..conv10 {s["conv2_10_exact"]}/{s["conv2_10_compared"]}; conv1, the measured constant, '
                    f'{s["conv1_exact"]}/{s["conv1_compared"]})')
    if pred is not None and not pr['same_as_pinned']:
        verdict += ('; NO setup.json: the prediction was not pinned before the runs' if not pinned else
                    '; THE PREDICTION FILE IS NOT THE ONE PINNED BEFORE THE RUNS')
    if s['runs_valid'] < s['runs_planned']:
        verdict += f'; INCOMPLETE: {s["runs_valid"]} of {s["runs_planned"]} runs valid'
    if s['runs_invalid']:
        verdict += f' ({s["runs_invalid"]} invalid)'
    if s['runs_unpredicted']:
        verdict += f'; {s["runs_unpredicted"]} run(s) without a prediction'
    ps = res['protocol_2_setup']
    if ps['same_bitstream'] is False or ps['same_driver'] is False:
        verdict += '; THE PROTOCOL_2 RUNS COMPARED WITH WERE MADE WITH ANOTHER ' + (
            'BITSTREAM' if ps['same_bitstream'] is False else 'DRIVER')
    res['verdict'] = verdict
    res['failed_attempts'] = sorted(p.name for p in attempts.iterdir()) if attempts.is_dir() else []
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', type=Path, default=RUNS)
    ap.add_argument('--prediction', type=Path, default=PREDICTION)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--attempts', type=Path, default=ATTEMPTS, help='where --run-state keeps an unfinished run')
    ap.add_argument('--q2-runs', type=Path, default=Q2_RUNS, help='the PROTOCOL_2 runs (Original, Skew) to compare with')
    ap.add_argument('--prediction-2', type=Path, default=PREDICTION_2, help='their prediction')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--run-state', type=Path, metavar='DIR', help='before a run: exit 10 if done, else clear DIR')
    g.add_argument('--check-run', type=Path, metavar='DIR', help='after a run: exit 10 if it passes')
    g.add_argument('--canary', type=Path, metavar='DIR', help='a finished run against its prediction: exit 10 if exact')
    ap.add_argument('--image', choices=IMAGES)
    args = ap.parse_args()
    if args.run_state or args.check_run or args.canary:
        if not args.image:
            raise SystemExit('--run-state, --check-run and --canary need --image')
        if args.canary:
            return canary(args.canary.resolve(), args.image, args.prediction.resolve())
        return run_state((args.run_state or args.check_run).resolve(), args.image, bool(args.run_state),
                         args.attempts.resolve())
    res = compare(args.runs.resolve(), args.prediction.resolve(), args.attempts.resolve(), args.q2_runs.resolve(),
                  args.prediction_2.resolve())
    args.out.write_bytes(json.dumps(res, indent=1).encode('utf-8') + b'\n')   # LF on every platform
    for name, r in res['runs'].items():
        t = r['total']
        print(f'{name:<7} cycles {t["cycles"]:>11,}  in_stall {t["in_stall"]:>6,}  exact '
              f'{t.get("exact", "-"):>11}  layers exact {r["layers_matched"]}/{r["layers_predicted"]}'
              + (f'  count {t["count_w4_results_2"]:,}' if 'count_w4_results_2' in t else ''))
    for im, rows in res['l3_savings'].items():
        for lay, v in rows.items():
            print(f'{im} L3 saving vs {lay:<8}: {v["cycles"]:>9,} cycles ({v["cycles_pct"]:.3f}%)'
                  + (f', predicted {v["predicted"]:,} ({v["predicted_pct"]:.3f}%)' if 'predicted' in v else '')
                  + (f', count {v["count_w4"]:,} ({v["count_w4_pct"]:.3f}%)' if 'count_w4' in v else ''))
    for k, rows in res['l3_savings_pooled'].items():
        for lay, v in rows.items():
            print(f'pooled {k} ({len(v["images"])} images) L3 saving vs {lay}: {v["cycles"]:,} cycles ({v["cycles_pct"]:.3f}%)')
    for name, p in res['invalid_runs'].items():
        print(f'INVALID {name}: {"; ".join(p)}')
    for name, p in res['protocol_2_runs_invalid'].items():
        print(f'INVALID PROTOCOL_2 run {name} (not compared with): {"; ".join(p)}')
    for m in res['misses']:
        print(f'MISS {m["run"]} {m["layer"]}: cycles {m["cycles"]} - in_stall {m["in_stall"]} - exact {m["exact"]}'
              f' = {m["difference"]} (out_stall {m["out_stall"]})')
    for u in res['unpredicted']:
        print(f'UNPREDICTED {u["run"]}: {u["why"]}')
    print(f'VERDICT: {res["verdict"]}')
    print(f'wrote {rel(args.out)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
