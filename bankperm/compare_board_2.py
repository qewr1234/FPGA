"""The PROTOCOL_2 board runs against their exact prediction.

    python bankperm/compare_board_2.py              # writes bankperm/board_measured_2.json, prints the verdict
    python bankperm/compare_board_2.py --run-state DIR --layout skew --image 05.png   # RUN_W4_LAYOUTS.cmd, before a run
    python bankperm/compare_board_2.py --check-run DIR --layout skew --image 05.png   # RUN_W4_LAYOUTS.cmd, after it
    python bankperm/compare_board_2.py --canary DIR --layout original --image 05.png  # RUN_W4_LAYOUTS.cmd, the canary

Reads denoise/board_runs/q1_layouts2/<layout>_<image stem>/report.json (scripts/
run_denoise.py on the W=4 bitstream, RUN_W4_LAYOUTS.cmd) for the layouts original,
frozen, multistart, skew and Set12 05.png, 06.png, 07.png, 08.png, whichever are
there, and bankperm/board_prediction_2.json (the exact per-layer cycles committed
before the runs, PROTOCOL_2.md). Every run is first checked: a board run (not
emulated), this model, Set12, W=4, sparse mode, one board run per layer, no
mismatches, core ID 0x4d410303 and 50 MHz on every layer, the export of its
layout, and the skewed layers (and only they) marked taps_reordered. A run that
fails a check is listed and left out of the comparison.

Per run and layer: CYCLES, IN_STALL, OUT_STALL, the exact prediction, and match =
(CYCLES - IN_STALL == exact): this bitstream's IN_STALL does not count starvation
at window boundaries, so the exact match, not IN_STALL = 0, is the test. Then the
totals, the saving of each layout against the Original on the same image
(measured CYCLES, CYCLES - IN_STALL, and predicted), and every miss (with its
OUT_STALL). conv1's "prediction" is a measured constant (PROTOCOL_2.md), so the
matches of conv2..conv10 are counted apart as well.

The prediction of a run is read from exactly one place,
predictions[<layout>][<image>]["layers"] of the prediction file
(bankperm/predict_board_2.py), which must hold an int for each of conv1..conv10;
otherwise the run is listed as unpredicted, with the reason. The prediction file
is identified by its git blob id and SHA-256 with CRLF read as LF (the board PC's
checkout may rewrite its line ends), and compared with the one
prepare_layouts.py pinned in denoise/board_runs/q1_layouts2/setup.json before
the first run.

--run-state exits 10 if DIR holds a complete run that passes the checks (the run
is skipped); otherwise it moves DIR, if it exists, to
denoise/board_runs/q1_layouts2_attempts/<name>_attempt<N> (kept, not deleted) and
exits 0. --check-run exits 10 if the run passes, 1 if not. --canary compares a
run that passes the checks with its prediction, layer by layer: exit 10 if every
layer is exact, 11 if any misses (the layers are printed). Any other exit code
is an error.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL = 'dn_d10_c32_us_fx_qat'
LAYOUTS = ('original', 'frozen', 'multistart', 'skew')
IMAGES = ('05.png', '06.png', '07.png', '08.png')
LAYERS = tuple(f'conv{i}' for i in range(1, 11))
SKEWED = tuple(f'conv{i}' for i in range(2, 10))          # bankperm/export_layout.py on this model
CORE_ID = '0x4d410303'
FCLK_MHZ = 50.0
RUNS = ROOT/'denoise'/'board_runs'/'q1_layouts2'
ATTEMPTS = ROOT/'denoise'/'board_runs'/'q1_layouts2_attempts'
PREDICTION = HERE/'board_prediction_2.json'
OUT = HERE/'board_measured_2.json'
SETUP = 'setup.json'                       # in the runs folder: bankperm/prepare_layouts.py --bitstream ... --record
DONE = 10
MISSED = 11


def rel(p):
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def path_parts(s):
    """A path written on Windows or here, as its parts."""
    return [x for x in str(s).replace('\\', '/').split('/') if x]


def validate(rep, layout, image):
    """What is wrong with report.json `rep` as the run of `layout` on `image` (empty: nothing)."""
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
    parts = path_parts(rep.get('export_dir', ''))
    want = ['denoise', 'export', MODEL] if layout == 'original' else ['layout_exports', layout]
    need(parts[-len(want):] == want, f'export_dir {rep.get("export_dir")} is not the {layout} export (.../{"/".join(want)})')
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
        expect = layout == 'skew' and n in SKEWED
        need(reordered == expect, f'{n}: taps_reordered {reordered}, expected {expect}')
    return bad


def load_report(d):
    p = Path(d)/'report.json'
    if not p.is_file():
        return None, 'no report.json (the run did not finish)'
    try:
        return json.loads(p.read_text(encoding='utf-8')), None
    except ValueError as e:
        return None, f'report.json does not parse: {e}'


# ------------------------------------------------------------ prediction ---
def lf_bytes(path):
    """A text file's bytes with CRLF read as LF (what git stores for it)."""
    return Path(path).read_bytes().replace(b'\r\n', b'\n')


def git_blob_id(data):
    """The id git gives a blob with these bytes (git hash-object)."""
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def text_digest(path):
    data = lf_bytes(path)
    return dict(git_blob=git_blob_id(data), lf_sha256=hashlib.sha256(data).hexdigest())


def load_prediction(path=None):
    p = Path(path or PREDICTION)
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None


def prediction_of(pred, layout, image):
    """{layer: exact} of one run, from predictions[layout][image]["layers"] only. -> (dict, None) or (None, why)."""
    where = f'predictions/{layout}/{image}/layers'
    try:
        node = pred['predictions'][layout][image]['layers']
    except (KeyError, TypeError):
        return None, f'no {where} in the prediction file'
    if not isinstance(node, dict) or sorted(node) != sorted(LAYERS):
        return None, f'{where} does not hold exactly {LAYERS[0]}..{LAYERS[-1]}'
    bad = [k for k in LAYERS if not isinstance(node[k], int) or isinstance(node[k], bool)]
    if bad:
        return None, f'{where}: not an integer on {bad}'
    return {k: node[k] for k in LAYERS}, None


def git(*args):
    r = subprocess.run(['git', '-C', str(ROOT)] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def prediction_git_state(path=None):
    """Is the prediction file committed in HEAD, and is the file here that commit's? -> (record, problems)."""
    path = Path(path or PREDICTION).resolve()
    name = rel(path)
    problems = []
    rec = dict(file=name, **text_digest(path)) if path.is_file() else dict(file=name)
    if not path.is_file():
        return rec, [f'{name} is not here']
    try:
        rc, head, err = git('rev-parse', 'HEAD')
    except OSError as e:
        return rec, [f'git could not be run ({e}): it is needed to check that {name} is committed']
    if rc:
        return rec, [f'git rev-parse HEAD failed: {err}']
    rec['head'] = head
    rc, blob, err = git('rev-parse', f'HEAD:{name}')
    if rc:
        return rec, [f'{name} is not committed (not in HEAD {head[:12]}): commit and push it before the board runs']
    rec['committed_blob'] = blob
    if blob != rec['git_blob']:
        problems.append(f'{name} here differs from its committed version (HEAD {head[:12]}, blob {blob[:12]})')
    rc, _, err = git('diff', '--quiet', 'HEAD', '--', name)
    if rc:
        problems.append(f'git diff: {name} has changes that are not committed')
    rc, out, _ = git('log', '-1', '--format=%H %cI', '--', name)
    if not rc and out:
        rec['committed_in'], rec['committed_at'] = out.split(' ', 1)
        rc, out, _ = git('branch', '-r', '--contains', rec['committed_in'])
        rec['commit_on_a_remote_branch'] = bool(out) if not rc else None
    return rec, problems


# --------------------------------------------------------------- compare ---
def pct(a, b):
    return round(100*(a - b)/a, 6) if a else None


def run_rows(rep, exact):
    """Per layer of a checked report: the counters, the prediction (exact[name] or None) and the match."""
    rows = []
    for L in rep['images'][0]['layers']:
        n, e = L['name'], exact.get(L['name'])
        c, s = L['cycles'], L['in_stall']
        rows.append(dict(name=n, cycles=c, in_stall=s, out_stall=L['out_stall'], cycles_minus_in_stall=c - s,
                         exact=e, difference=None if e is None else c - s - e, match=None if e is None else c - s == e))
    return rows


def canary(d, layout, image, pred_path=None):
    """A finished run against its prediction, layer by layer, before the other runs start."""
    rep, why = load_report(d)
    problems = [why] if why else validate(rep, layout, image)
    if problems:
        print(f'{layout} {image}: the run in {rel(d)} does not pass the checks:')
        for p in problems:
            print('  ' + p)
        return 1
    pred = load_prediction(pred_path)
    exact, why = prediction_of(pred, layout, image) if pred is not None else (None, f'no {rel(pred_path or PREDICTION)}')
    if exact is None:
        print(f'{layout} {image}: no prediction to compare with ({why})')
        return 1
    rows = run_rows(rep, exact)
    for r in rows:
        print(f'  {r["name"]:<7} cycles {r["cycles"]:>9,}  in_stall {r["in_stall"]:>4}  out_stall {r["out_stall"]:>4}  '
              f'predicted {r["exact"]:>9,}  difference {r["difference"]:>+6}  {"exact" if r["match"] else "MISS"}')
    bad = [r['name'] for r in rows if not r['match']]
    if bad:
        print(f'{layout} {image}: CYCLES - IN_STALL is not the prediction on {", ".join(bad)}')
        return MISSED
    print(f'{layout} {image}: every layer exact (CYCLES - IN_STALL == prediction)')
    return DONE


def compare(runs_dir, pred_path, attempts=ATTEMPTS):
    pred = load_prediction(pred_path)
    setup_path = runs_dir/SETUP                     # RUN_W4_LAYOUTS.cmd, prepare_layouts.py --bitstream --record
    setup = json.loads(setup_path.read_text(encoding='utf-8')) if setup_path.is_file() else None
    pinned = (setup or {}).get('prediction') or {}
    pr = dict(file=rel(pred_path), present=pred is not None)
    if pred is not None:
        pr.update(text_digest(pred_path), written_utc=pred.get('written_utc'),
                  all_checks_passed=pred.get('all_checks_passed'))
        pr['pinned_before_the_runs'] = pinned.get('git_blob')
        pr['same_as_pinned'] = None if not pinned else pinned.get('git_blob') == pr['git_blob']
        pr['committed_in'] = pinned.get('committed_in')
        pr['committed_at'] = pinned.get('committed_at')
    res = dict(what='PROTOCOL_2 board runs (W=4 bitstream) against the exact per-layer prediction',
               model=MODEL, core_id=CORE_ID, fclk_mhz=FCLK_MHZ, runs_dir=rel(runs_dir),
               match_rule='CYCLES - IN_STALL == exact', prediction=pr,
               runs={}, invalid_runs={}, missing_runs=[], ignored=[], misses=[], unpredicted=[])
    known = {f'{lay}_{im[:-4]}': (lay, im) for lay in LAYOUTS for im in IMAGES}
    if runs_dir.is_dir():
        res['ignored'] = sorted(p.name for p in runs_dir.iterdir() if p.name not in known and p.name != SETUP)
    res['setup'] = setup
    for name, (lay, im) in known.items():
        d = runs_dir/name
        if not d.is_dir():
            res['missing_runs'].append(name)
            continue
        rep, why = load_report(d)
        problems = [why] if why else validate(rep, lay, im)
        if problems:
            res['invalid_runs'][name] = problems
            continue
        exact, why = prediction_of(pred, lay, im) if pred is not None else (None, 'no prediction file')
        if exact is None:
            res['unpredicted'].append(dict(run=name, why=why))
        rows = run_rows(rep, exact or {})
        for row in rows:
            if row['exact'] is not None and not row['match']:
                res['misses'].append(dict(run=name, layout=lay, image=im, layer=row['name'], cycles=row['cycles'],
                                          in_stall=row['in_stall'], out_stall=row['out_stall'], exact=row['exact'],
                                          difference=row['difference']))
        tot = dict(cycles=sum(r['cycles'] for r in rows), in_stall=sum(r['in_stall'] for r in rows),
                   out_stall=sum(r['out_stall'] for r in rows))
        tot['cycles_minus_in_stall'] = tot['cycles'] - tot['in_stall']
        if all(r['exact'] is not None for r in rows):
            tot['exact'] = sum(r['exact'] for r in rows)
            tot['difference'] = tot['cycles_minus_in_stall'] - tot['exact']
        res['runs'][name] = dict(layout=lay, image=im, export_dir=rep['export_dir'],
                                 prediction_read_from=None if exact is None else f'predictions/{lay}/{im}/layers',
                                 layers=rows, total=tot,
                                 layers_matched=sum(r['match'] is True for r in rows),
                                 layers_predicted=sum(r['exact'] is not None for r in rows))
    sav = {}
    for im in IMAGES:
        o = res['runs'].get(f'original_{im[:-4]}')
        if not o:
            continue
        for lay in LAYOUTS[1:]:
            r = res['runs'].get(f'{lay}_{im[:-4]}')
            if not r:
                continue
            a, b = o['total'], r['total']
            row = dict(cycles=a['cycles'] - b['cycles'], cycles_pct=pct(a['cycles'], b['cycles']),
                       cycles_minus_in_stall=a['cycles_minus_in_stall'] - b['cycles_minus_in_stall'],
                       cycles_minus_in_stall_pct=pct(a['cycles_minus_in_stall'], b['cycles_minus_in_stall']))
            if 'exact' in a and 'exact' in b:
                row.update(predicted=a['exact'] - b['exact'], predicted_pct=pct(a['exact'], b['exact']))
            sav.setdefault(im, {})[lay] = row
    res['savings_vs_original'] = sav
    pred_rows = [r for run in res['runs'].values() for r in run['layers'] if r['exact'] is not None]
    hidden = [r for r in pred_rows if r['name'] != 'conv1']
    res['summary'] = dict(
        runs_planned=len(known), runs_valid=len(res['runs']), runs_invalid=len(res['invalid_runs']),
        runs_missing=len(res['missing_runs']), layers_compared=len(pred_rows),
        layers_exact=sum(r['match'] for r in pred_rows), conv2_10_compared=len(hidden),
        conv2_10_exact=sum(r['match'] for r in hidden), conv1_compared=len(pred_rows) - len(hidden),
        conv1_exact=sum(r['match'] for r in pred_rows if r['name'] == 'conv1'), misses=len(res['misses']),
        runs_unpredicted=len(res['unpredicted']))
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
    res['verdict'] = verdict
    res['failed_attempts'] = sorted(p.name for p in attempts.iterdir()) if attempts.is_dir() else []
    return res


def run_state(d, layout, image, move, attempts=ATTEMPTS):
    rep, why = load_report(d)
    problems = [why] if why else validate(rep, layout, image)
    if not problems:
        print(f'{layout} {image}: complete run in {rel(d)}, checks pass')
        return DONE
    if not move:
        print(f'{layout} {image}: the run in {rel(d)} does not pass:')
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
        print(f'{layout} {image}: {rel(d)} held an unfinished or failing run ({problems[0]}); kept as {rel(dest)}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', type=Path, default=RUNS)
    ap.add_argument('--prediction', type=Path, default=PREDICTION)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--attempts', type=Path, default=ATTEMPTS, help='where --run-state keeps an unfinished run')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--run-state', type=Path, metavar='DIR', help='before a run: exit 10 if done, else clear DIR')
    g.add_argument('--check-run', type=Path, metavar='DIR', help='after a run: exit 10 if it passes')
    g.add_argument('--canary', type=Path, metavar='DIR', help='a finished run against its prediction: exit 10 if exact')
    ap.add_argument('--layout', choices=LAYOUTS)
    ap.add_argument('--image', choices=IMAGES)
    args = ap.parse_args()
    if args.run_state or args.check_run or args.canary:
        if not (args.layout and args.image):
            raise SystemExit('--run-state, --check-run and --canary need --layout and --image')
        if args.canary:
            return canary(args.canary.resolve(), args.layout, args.image, args.prediction.resolve())
        return run_state((args.run_state or args.check_run).resolve(), args.layout, args.image, bool(args.run_state),
                         args.attempts.resolve())
    res = compare(args.runs.resolve(), args.prediction.resolve(), args.attempts.resolve())
    args.out.write_bytes(json.dumps(res, indent=1).encode('utf-8') + b'\n')   # LF on every platform
    for name, r in res['runs'].items():
        t = r['total']
        print(f'{name:<14} cycles {t["cycles"]:>11,}  in_stall {t["in_stall"]:>6,}  exact '
              f'{t.get("exact", "-"):>11}  layers exact {r["layers_matched"]}/{r["layers_predicted"]}')
    for im, rows in res['savings_vs_original'].items():
        for lay, v in rows.items():
            print(f'{im} {lay:<11} saving vs original: {v["cycles"]:>9,} cycles ({v["cycles_pct"]:.3f}%)'
                  + (f', predicted {v["predicted"]:,} ({v["predicted_pct"]:.3f}%)' if 'predicted' in v else ''))
    for name, p in res['invalid_runs'].items():
        print(f'INVALID {name}: {"; ".join(p)}')
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
