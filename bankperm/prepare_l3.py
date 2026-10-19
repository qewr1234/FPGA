"""Check the L3 export on the board PC and pin the setup of the L3 board runs (RUN_W4_L3.cmd).

    python bankperm/export_layout.py --layout skew --model dn_d10_c32_us_fx_qat --orders bankperm/perms_2.json --out build/layout_exports/l3
    python bankperm/prepare_l3.py --verify build/layout_exports/l3 [--require-check]
    python bankperm/prepare_l3.py --bitstream BUILD --export build/layout_exports/l3 \
                                  --record denoise/board_runs/q1_layouts3/setup.json [--allow-other-bitstream]

The L3 board runs of bankperm/PROTOCOL_2_ADDENDUM.md: L3 (skew + relabeling) of
B-32 ReLU + QAT s1 exactly as in bankperm/perms_2.json, exported with
bankperm/export_layout.py --orders, which reads perms_2.json as it is (the
"networks" entry of the model, its "orders"). This is a separate script from
bankperm/prepare_layouts.py so that nothing RUN_W4_LAYOUTS.cmd runs or pins
changes; it reuses that script's functions without changing them.

--verify DIR checks, and exits 1 on any failure:
  manifest     every file has the hash DIR/layout_manifest.json records, and there is no
               file it does not list; the layout is skew+relabeling of this model with the
               orders of bankperm/perms_2.json and the skew order on conv2..conv9 only
  fresh        export_layout.write_layout run again here on the original export with the
               same orders gives every file byte for byte (layout_manifest.json included)
  analysis     where bankperm/l3_export_check.json (written on the analysis machine by
  machine      bankperm/check_l3_export.py) records a file's hash, the file here has it,
               for the L3 export and the original, and the L3 export has no file it does
               not record: the board PC runs the export that was checked. Text files are
               compared with CRLF read as LF; permutation_manifest.json (fold.py's record
               of the orders, not read by the driver) also with its path separators read
               as "/", since fold.py writes "derived_from" with the platform's. Also
               perms_2.json and the driver files (scripts/run_denoise.py, run_cifar.py,
               run_board_xsdb.tcl) must be those the check ran with. With --require-check
               (RUN_W4_L3.cmd) that file must be there and say all_ok.

--bitstream BUILD --export DIR --record FILE pins, before the first L3 board run,
what the runs are made with, and on a rerun refuses anything that changed since:
  bitstream    the SHA-256 of BUILD's system_wrapper.bit (and .xsa). It must be the
               earlier W=4 canary's (bankperm/board_transcribed.json bitstream_sha256) and,
               if denoise/board_runs/q1_layouts2/setup.json is there, the one the PROTOCOL_2
               runs were pinned with, unless --allow-other-bitstream is given; the record
               says which
  prediction   bankperm/board_prediction_3.json must be committed in HEAD and the file here
               that commit's (git), say all_checks_passed, and hold an integer prediction
               for every layer of the four runs (bankperm/compare_board_3.py prediction_of);
               its git blob id and the commit that added it are recorded
  check        bankperm/l3_export_check.json must be committed and unchanged (git) and say
               all_ok
  export       every layer's config.bin of DIR must have the SHA-256 the prediction lists
               for it (runs.l3.<image>.layers[].config_sha256), and its tap orders the skew
               order on conv2..conv9; every export file's hash is recorded
  code         the hashes of scripts/run_denoise.py, run_cifar.py and run_board_xsdb.tcl,
               which must also be those of the q1_layouts2 setup.json when it is there
If FILE is already there, every one of these must be what it records.
"""
import argparse
import datetime
import hashlib
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]
import compare_board_2  # noqa: E402 (git and digest helpers, used unchanged)
import prepare_layouts  # noqa: E402 (hash, bitstream and manifest helpers, used unchanged)

MODEL = 'dn_d10_c32_us_fx_qat'
ORIGINAL = ROOT/'denoise'/'export'/MODEL
PERMS_2 = HERE/'perms_2.json'
CHECK = HERE/'l3_export_check.json'
LAYOUT = 'l3'
IMAGES = ('05.png', '06.png', '07.png', '08.png')
SKEWED = tuple(f'conv{i}' for i in range(2, 10))
CODE = prepare_layouts.CODE
Q2_SETUP = ROOT/'denoise'/'board_runs'/'q1_layouts2'/'setup.json'
PORTABLE = 'permutation_manifest.json'
PORTABLE_RULE = ('sha256 of the file with CRLF read as LF (text files); for permutation_manifest.json also with every '
                 'JSON-escaped backslash (the two bytes \\\\) read as "/" (fold.py writes derived_from with the '
                 'platform path separator)')


def rel(p):
    return prepare_layouts.rel(p)


def code_sha(path):
    return prepare_layouts.code_sha(path)


def text_record(path):
    return compare_board_2.text_digest(path)


def portable_sha(path):
    """The hash a file has on any platform (see PORTABLE_RULE)."""
    path = Path(path)
    data = path.read_bytes()
    if path.suffix in prepare_layouts.TEXT:
        data = data.replace(b'\r\n', b'\n')
    if path.name == PORTABLE:
        data = data.replace(b'\\\\', b'/')
    return hashlib.sha256(data).hexdigest()


def l3_orders():
    import export_layout                           # the reader RUN_W4_L3.cmd's export uses
    return export_layout.read_orders(PERMS_2, MODEL)


def skew_288_32():
    from skew_count import skew_order
    return [int(v) for v in skew_order(288, 32)]


def tap_orders(d):
    man = json.loads((Path(d)/'manifest.json').read_text(encoding='utf-8'))
    return {L['name']: L['tap_order'] for L in man['layers'] if 'tap_order' in L}


def check_tap_orders(d, problems):
    taps = tap_orders(d)
    if sorted(taps) != sorted(SKEWED) or any(o != skew_288_32() for o in taps.values()):
        problems.append(f'{rel(d)}: the tap orders are not skew_count.skew_order(288, 32) on conv2..conv9 only '
                        f'(found them on {sorted(taps)})')


def load_check():
    return json.loads(CHECK.read_text(encoding='utf-8')) if CHECK.is_file() else None


def check_against_analysis(d, chk, problems):
    """The files here against the hashes bankperm/l3_export_check.json records. -> files compared."""
    rec = chk.get('export_files_portable_sha256') or {}
    n = 0
    for name, folder in (('original', ORIGINAL), ('l3', Path(d))):
        want = rec.get(name)
        if not want:
            problems.append(f'{rel(CHECK)} records no file hashes for {name}')
            continue
        have = sorted(p.name for p in folder.iterdir() if p.is_file() and p.name != 'layout_manifest.json')
        # The L3 export must hold exactly the checked files; in the original only the checked
        # ones matter (export_layout.py builds the L3 export from fold.py's files alone).
        extra = sorted(set(have) - set(want)) if name == 'l3' else []
        missing = sorted(set(want) - set(have))
        if extra or missing:
            problems.append(f'{rel(folder)}: files {extra} are not in {CHECK.name}, files {missing} are missing')
        for f in sorted(set(have) & set(want)):
            n += 1
            if portable_sha(folder/f) != want[f]:
                problems.append(f'{name}: {f} is not the file {CHECK.name} recorded')
    p2 = (chk.get('inputs') or {}).get('perms_2') or {}
    if text_record(PERMS_2)['lf_sha256'] != p2.get('lf_sha256'):
        problems.append(f'{rel(PERMS_2)} is not the file {CHECK.name} was made with')
    drv = chk.get('driver_code_lf_sha256') or {}
    for c in CODE:
        if code_sha(ROOT/c) != drv.get(c):
            problems.append(f'{c} is not the driver file {CHECK.name} checked the L3 export with')
    return n


def verify(d, require_check=False):
    import export_layout
    d = Path(d).resolve()
    problems = []
    if not d.is_dir():
        print(f'{rel(d)} is not there')
        return 1
    lm = prepare_layouts.check_manifest_hashes(d, problems)
    orders = l3_orders()
    if lm is not None:
        rl = lm.get('relabeling') or {}
        if lm.get('layout') != 'skew+relabeling' or lm.get('model') != MODEL:
            problems.append(f'{rel(d)}: layout {lm.get("layout")} of {lm.get("model")}, not skew+relabeling of {MODEL}')
        if rl.get('source') != rel(PERMS_2) or rl.get('orders') != orders:
            problems.append(f'{rel(d)}: its relabeling is not the orders of {rel(PERMS_2)} for {MODEL}')
    check_tap_orders(d, problems)
    with tempfile.TemporaryDirectory() as tmp:
        ref = Path(tmp)/'l3'
        export_layout.write_layout(ORIGINAL, ref, 'skew', orders, PERMS_2)
        names = sorted(p.name for p in ref.iterdir())
        if names != sorted(p.name for p in d.iterdir()):
            problems.append(f'{rel(d)}: files {sorted(p.name for p in d.iterdir())}, a fresh export has {names}')
        for n in names:
            if (d/n).is_file() and (d/n).read_bytes() != (ref/n).read_bytes():
                problems.append(f'{rel(d)}: {n} differs from export_layout.py run again on the original')
    chk = load_check()
    compared = 0
    if chk is None:
        if require_check:
            problems.append(f'{rel(CHECK)} is not here: the export cannot be checked against the analysis machine')
        else:
            print(f'note: {rel(CHECK)} is not here, so the export is checked here but not against the analysis machine')
    else:
        if require_check and chk.get('all_ok') is not True:
            problems.append(f'{rel(CHECK)} does not say all_ok: the host checks of the L3 export did not all pass')
        compared = check_against_analysis(d, chk, problems)
    print(f'l3          {rel(d):<40} {len(tap_orders(d))} layers skewed, same as a fresh export'
          + (f'; {compared} files as {CHECK.name} records' if chk else ''))
    if problems:
        print('\nFAILED:')
        for p in problems:
            print('  ' + p)
        return 1
    print('the L3 export checks out')
    return 0


def check_export_against_prediction(pred, export, problems):
    """Every layer's config.bin of the L3 export must be the one the prediction was made with."""
    man = json.loads((export/'manifest.json').read_text(encoding='utf-8'))
    n = 0
    runs = (pred.get('runs') or {}).get(LAYOUT) or {}
    for image in IMAGES:
        want = (runs.get(image) or {}).get('layers') or []
        if [L.get('name') for L in want] != [L['name'] for L in man['layers']]:
            problems.append(f'{LAYOUT} {image}: runs/{LAYOUT}/{image}/layers of the prediction are not the layers of '
                            f'{rel(export)}')
            continue
        for node, L in zip(man['layers'], want):
            n += 1
            if not (export/node['config']).is_file() or prepare_layouts.file_sha(export/node['config']) != L.get('config_sha256'):
                problems.append(f'{LAYOUT} {image} {node["name"]}: {rel(export/node["config"])} is not the config.bin '
                                f'the prediction was made with')
    check_tap_orders(export, problems)
    return n


def git_record(path, problems):
    rec, p = compare_board_2.prediction_git_state(path)
    problems += p
    return rec


def record_setup(build, record, export, allow_other=False):
    """Pin the bitstream, the prediction, the export and the driver before the first L3 run; recheck on a rerun."""
    import compare_board_3                         # the prediction, read the way the comparison reads it
    build, export = Path(build).resolve(), Path(export).resolve()
    problems = []
    files = prepare_layouts.bitstream_files(build)
    bit = files['system_wrapper.bit']['sha256']
    earlier = prepare_layouts.earlier_bitstream()
    code = {n: code_sha(ROOT/n) for n in CODE}

    pred_rec = git_record(compare_board_3.PREDICTION, problems)
    pred = compare_board_3.load_prediction()
    configs = 0
    if pred is not None:
        if pred.get('all_checks_passed') is not True:
            problems.append(f'{pred_rec["file"]} does not say all_checks_passed')
        for im in IMAGES:
            _, why = compare_board_3.prediction_of(pred, im)
            if why:
                problems.append(why)
        configs = check_export_against_prediction(pred, export, problems)
    chk_rec = git_record(CHECK, problems)
    chk = load_check()
    if chk is not None and chk.get('all_ok') is not True:
        problems.append(f'{rel(CHECK)} does not say all_ok')

    q2 = json.loads(Q2_SETUP.read_text(encoding='utf-8')) if Q2_SETUP.is_file() else None
    q2_bit = ((q2 or {}).get('files') or {}).get('system_wrapper.bit', {}).get('sha256')
    q2_rec = None if q2 is None else dict(
        file=rel(Q2_SETUP), bitstream_sha256=q2_bit, same_bitstream=q2_bit == bit,
        code=q2.get('code'), same_driver=q2.get('code') == code)
    if q2 is not None and q2.get('code') != code:
        problems.append(f'the driver files differ from those {rel(Q2_SETUP)} pinned for the Original and Skew runs '
                        f'these runs are compared with')
    rec = dict(
        what='what the L3 board runs (bankperm/PROTOCOL_2_ADDENDUM.md) in this folder are made with, pinned before '
             'the first run (bankperm/prepare_l3.py --bitstream); a rerun of RUN_W4_L3.cmd refuses any change',
        build=build.name, files=files, earlier_canary_bitstream_sha256=earlier,
        matches_earlier_canary_bitstream=bit == earlier,
        other_bitstream_allowed=bool(allow_other and (bit != earlier or (q2_bit is not None and q2_bit != bit))),
        prediction={k: pred_rec.get(k) for k in ('file', 'git_blob', 'lf_sha256', 'committed_in', 'committed_at',
                                                 'commit_on_a_remote_branch', 'head')},
        export_check={k: chk_rec.get(k) for k in ('file', 'git_blob', 'lf_sha256', 'committed_in')},
        orders=dict(file=rel(PERMS_2), **text_record(PERMS_2)),
        export=dict(path=rel(export), files={q.name: prepare_layouts.lf_sha(q) for q in sorted(export.iterdir())
                                             if q.is_file()}),
        config_bins_equal_to_the_prediction=configs if not problems else None,
        code=code, q1_layouts2_setup=q2_rec)
    if record.is_file():
        old = json.loads(record.read_text(encoding='utf-8'))
        what = dict(files='bitstream', export='L3 export', code='driver (run_denoise.py, run_cifar.py, '
                    'run_board_xsdb.tcl)', orders='perms_2.json')
        changed = [what[k] for k in what if old.get(k) != rec[k]]
        for k, label in (('prediction', 'prediction'), ('export_check', 'l3_export_check.json')):
            if (old.get(k) or {}).get('git_blob') != rec[k]['git_blob']:
                changed.append(label)
        if changed:
            problems.append(f'{rel(record)} pins another {", ".join(changed)} than is here now (the earlier runs '
                            f'used {old.get("build")}, bitstream {old.get("files", {}).get("system_wrapper.bit", {}).get("sha256")}). '
                            f'All runs of one comparison must be made with one setup: move {rel(record.parent)} away to '
                            f'start over')
    elif not allow_other:
        if bit != earlier:
            others = []
            for q in sorted(build.parent.glob('zed_v4_p16_t4_w4_*')):
                if (q/'system_wrapper.bit').is_file():
                    h = prepare_layouts.file_sha(q/'system_wrapper.bit')
                    others.append(q.name + ' ' + h[:12] + (' (the earlier canary bitstream)' if h == earlier else ''))
            problems.append(f'build/{build.name}/system_wrapper.bit has SHA-256 {bit}, not the {earlier} of the earlier '
                            f'W=4 canary (bankperm/board_transcribed.json), the bitstream PROTOCOL_2_ADDENDUM.md names. '
                            f'W=4 builds here: {"; ".join(others)}. Move the newer build folder out of build, or give '
                            f'allow-other-bitstream as the second argument of RUN_W4_L3.cmd to use this one '
                            f'(the record will say so)')
        if q2_bit is not None and q2_bit != bit:
            problems.append(f'{rel(Q2_SETUP)} pinned bitstream {q2_bit} for the Original and Skew runs, not this '
                            f'{bit}: the comparison would mix two bitstreams. Give allow-other-bitstream to run anyway '
                            f'(the record will say so)')
    if problems:
        print('NOT PINNED:')
        for q in problems:
            print('  ' + q)
        return 1
    if record.is_file():
        print(f'setup as pinned in {rel(record)}: bitstream {build.name} {bit[:16]}..., prediction blob '
              f'{rec["prediction"]["git_blob"][:12]}, L3 export {len(rec["export"]["files"])} files, '
              f'{len(rec["code"])} driver files')
        return 0
    rec['pinned_utc'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_bytes(json.dumps(rec, indent=1).encode('utf-8') + b'\n')
    which = 'the earlier canary bitstream' if bit == earlier else 'NOT the earlier canary bitstream, allowed'
    if q2_rec is not None:
        which += ', ' + ('the q1_layouts2 bitstream' if q2_rec['same_bitstream'] else 'NOT the q1_layouts2 bitstream, allowed')
    print(f'pinned -> {rel(record)}: bitstream {build.name} {bit[:16]}... ({which}), prediction '
          f'{rec["prediction"]["file"]} blob {rec["prediction"]["git_blob"][:12]} committed in '
          f'{(rec["prediction"]["committed_in"] or "?")[:12]}, {configs} config.bin as predicted')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--verify', type=Path, help='check the L3 export in this folder')
    g.add_argument('--bitstream', type=Path, help='a build folder: pin it, the prediction and the export in --record')
    ap.add_argument('--record', type=Path, help='with --bitstream: the JSON to write or check')
    ap.add_argument('--export', type=Path, help='with --bitstream: the L3 export folder')
    ap.add_argument('--allow-other-bitstream', action='store_true',
                    help='with --bitstream: accept a bitstream that is not the earlier W=4 canary bitstream '
                         '(or not the one q1_layouts2/setup.json pinned)')
    ap.add_argument('--require-check', action='store_true',
                    help=f'with --verify: fail if {CHECK.name} is missing or not all_ok')
    args = ap.parse_args()
    if args.bitstream:
        if not (args.record and args.export):
            raise SystemExit('--bitstream needs --record and --export')
        return record_setup(args.bitstream, args.record.resolve(), args.export, args.allow_other_bitstream)
    return verify(args.verify, args.require_check)


if __name__ == '__main__':
    sys.exit(main())
