"""Unpack the Frozen and Multi-start exports for the board runs, and check all three layout exports.

    python bankperm/prepare_layouts.py --out build/layout_exports      # unzip Frozen, Multi-start
    python bankperm/export_layout.py --layout skew --model dn_d10_c32_us_fx_qat --out build/layout_exports/skew
    python bankperm/prepare_layouts.py --verify build/layout_exports [--require-check]   # check all layouts
    python bankperm/prepare_layouts.py --bitstream BUILD --exports build/layout_exports \
                                       --record denoise/board_runs/q1_layouts2/setup.json   # pin, before the runs

Python's zipfile does the unpacking, so there is no PowerShell on the board PC.
Each GPT ZIP (research/q1_codesign/artifacts, the same two files bankperm/b32_board.py
reads) must have the SHA-256 pinned below; only the regular files of its
dn_d10_c32_us_fx_qat/ folder are written, flat, to <out>/frozen and
<out>/multistart, with a layout_manifest.json (the ZIP's hash, its
permutation_manifest.json orders, the hash of every file).

--verify checks, and exits 1 on any failure:
  every layout   each file has the hash its layout_manifest.json records, and
                 there is no file it does not list;
  frozen,        the ZIP's hash is the pinned one and every file is its ZIP
  multistart     member byte for byte (Frozen: also its SHA256SUMS.txt); folding
                 the original with the orders of the ZIP's permutation_manifest.json
                 (bankperm/fold.fold) gives every config.bin byte for byte and the
                 same manifest content: the export is the relabeling it says it is;
  skew           export_layout.write_layout run again on the original gives every
                 file byte for byte and the same tap orders (skew_count.skew_order);
  all, and the   where bankperm/skew_export_check.json (written on the analysis
  original       machine by bankperm/check_skew_export.py) records a file's hash,
                 the file here has it: the board PC runs the exports that were
                 checked. Binary files must match exactly; JSON and text files are
                 compared with CRLF read as LF, since a Windows checkout may
                 rewrite the line ends of the files git sees as text. With
                 --require-check (RUN_W4_LAYOUTS.cmd) that file must be there,
                 say all_ok, and record all four layouts, or --verify fails.

--bitstream BUILD --exports DIR --record FILE pins, before the first board run,
what the runs are made with, and on a rerun of RUN_W4_LAYOUTS.cmd refuses
anything that changed since, so one comparison never mixes two setups:
  bitstream    the SHA-256 of BUILD's system_wrapper.bit (and .xsa). It must be
               the bitstream of the earlier W=4 canary (bankperm/board_transcribed.json
               bitstream_sha256, the "existing W=4 bitstream" of PROTOCOL_2.md)
               unless --allow-other-bitstream is given; the record says which
  prediction   bankperm/board_prediction_2.json must be committed in HEAD and the
               file here must be that commit's (git), say all_checks_passed, and
               hold an integer prediction for every layer of all 16 runs; its git
               blob id and the commit that added it are recorded
  exports      every layer's config.bin of the four layouts (the original
               export and DIR/frozen, DIR/multistart, DIR/skew) must have the
               SHA-256 the prediction lists for it (runs.<layout>.<image>.layers[]
               .config_sha256), and the skew's tap orders the prediction's order;
               every export file's hash is recorded
  code         the hashes of scripts/run_denoise.py, scripts/run_cifar.py and
               scripts/run_board_xsdb.tcl (what builds and streams the windows)
If FILE is already there, every one of these must be what it records.
"""
import argparse
import datetime
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT/'denoise'), str(ROOT/'scripts')]

MODEL = 'dn_d10_c32_us_fx_qat'
ORIGINAL = ROOT/'denoise'/'export'/MODEL
ART = ROOT/'research'/'q1_codesign'/'artifacts'
ZIPS = {
    'frozen': (ART/'q1_bank_reordered_export_20261018.zip',
               'a660c020d52d811593f97e9defd918f24039ed9ad02d8e361c4f36199d6c0022'),
    'multistart': (ART/'q1_multistart_verified_export_20261018.zip',
                   '6e8ea3b8485fdc7633248cd27b56d52246b24f99ab3243605dba46dc3b4b7023'),
}
CHECK = HERE/'skew_export_check.json'
TEXT = {'.json', '.txt', '.md'}
TRANSCRIBED = HERE/'board_transcribed.json'     # bitstream_sha256: the earlier W=4 canary's .bit
CODE = ('scripts/run_denoise.py', 'scripts/run_cifar.py', 'scripts/run_board_xsdb.tcl')
LAYOUT_NAMES = ('original', 'frozen', 'multistart', 'skew')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha256(Path(path).read_bytes())


def lf_sha(path):
    """The hash a text file has with CRLF read as LF; binary files as they are."""
    data = Path(path).read_bytes()
    return sha256(data.replace(b'\r\n', b'\n') if Path(path).suffix in TEXT else data)


def rel(p):
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def members(zpath):
    """{file name: bytes} of the MODEL/ folder of a GPT export ZIP (regular files directly in it)."""
    out = {}
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            parts = m.filename.split('/')
            if m.is_dir() or len(parts) != 2 or parts[0] != MODEL or parts[1] in ('', '.', '..') or '\\' in parts[1]:
                continue
            out[parts[1]] = z.read(m)
    return out


def unpack(name, out):
    zpath, pinned = ZIPS[name]
    got = file_sha(zpath)
    if got != pinned:
        raise SystemExit(f'{rel(zpath)} has SHA-256 {got}, not the pinned {pinned}. '
                         f'This is not the export the board runs were planned for.')
    files = members(zpath)
    dest = out/name
    dest.mkdir(parents=True, exist_ok=True)
    extra = sorted(p.name for p in dest.iterdir() if p.name not in files and p.name != 'layout_manifest.json')
    if extra:
        raise SystemExit(f'{dest} holds files that are not in {zpath.name}: {extra}. '
                         f'Delete the folder and run again.')
    for n, data in files.items():
        (dest/n).write_bytes(data)
    pm = json.loads(files['permutation_manifest.json'])
    lm = dict(layout=name, model=MODEL, written_by='bankperm/prepare_layouts.py', source_zip=rel(zpath),
              zip_sha256=got, orders=pm['orders'], zip_status=pm.get('status'),
              files={n: sha256(files[n]) for n in sorted(files)})
    (dest/'layout_manifest.json').write_bytes(json.dumps(lm, indent=1).encode('utf-8') + b'\n')
    print(f'{name:<11} {len(files)} files from {zpath.name} -> {rel(dest)}')


def check_manifest_hashes(d, problems):
    lm_path = d/'layout_manifest.json'
    if not lm_path.is_file():
        problems.append(f'{rel(d)}: no layout_manifest.json')
        return None
    lm = json.loads(lm_path.read_text(encoding='utf-8'))
    for n, h in lm['files'].items():
        if not (d/n).is_file():
            problems.append(f'{rel(d)}: {n} is missing')
        elif file_sha(d/n) != h:
            problems.append(f'{rel(d)}: {n} does not have the hash its layout_manifest.json records')
    extra = sorted(p.name for p in d.iterdir() if p.name not in lm['files'] and p.name != 'layout_manifest.json')
    if extra:
        problems.append(f'{rel(d)}: files not in its layout_manifest.json: {extra}')
    return lm


def check_zip_layout(name, d, problems):
    import fold                                    # bankperm/fold.py: the relabeling, folded
    zpath, pinned = ZIPS[name]
    if file_sha(zpath) != pinned:
        problems.append(f'{rel(zpath)}: SHA-256 is not the pinned one')
    files = members(zpath)
    for n, data in files.items():
        if not (d/n).is_file() or (d/n).read_bytes() != data:
            problems.append(f'{rel(d)}: {n} is not the ZIP member byte for byte')
    if 'SHA256SUMS.txt' in files:
        for line in files['SHA256SUMS.txt'].decode().splitlines():
            if line.strip():
                h, n = line.split()
                if sha256(files[n]) != h:
                    problems.append(f'{zpath.name}: {n} does not match SHA256SUMS.txt')
    orders = json.loads(files['permutation_manifest.json'])['orders']
    with tempfile.TemporaryDirectory() as tmp:
        ref = Path(tmp)/name
        fold.fold(ORIGINAL.resolve(), orders, ref)
        man = json.loads(files['manifest.json'])
        for L in man['layers']:
            if (ref/L['config']).read_bytes() != files[L['config']]:
                problems.append(f'{name}: {L["config"]} is not the original folded with its permutation_manifest.json')
        if json.loads((ref/'manifest.json').read_text(encoding='utf-8')) != man:
            problems.append(f'{name}: manifest.json content is not the original folded with its orders')
    return len(orders)


def check_skew(d, lm, problems):
    import export_layout                           # its tap orders are skew_count.skew_order
    with tempfile.TemporaryDirectory() as tmp:
        ref = Path(tmp)/'skew'
        ref_lm = export_layout.write_layout(ORIGINAL, ref, 'skew')
        for p in sorted(ref.iterdir()):
            if p.name == 'layout_manifest.json':
                continue
            if not (d/p.name).is_file() or (d/p.name).read_bytes() != p.read_bytes():
                problems.append(f'{rel(d)}: {p.name} differs from export_layout.py run again on the original')
    if lm is not None and lm.get('tap_orders') != ref_lm['tap_orders']:
        problems.append(f'{rel(d)}: the tap orders of its layout_manifest.json differ from a fresh export')
    return len(ref_lm['tap_orders'])


def check_recorded(label, d, recorded, problems):
    """Files whose hash bankperm/skew_export_check.json records must have it here."""
    n = 0
    for name, h in recorded.items():
        p = d/name
        if not p.is_file():
            problems.append(f'{rel(d)}: {name} is missing (recorded in {CHECK.name})')
            continue
        n += 1
        if lf_sha(p) != h:
            problems.append(f'{label}: {name} is not the file {CHECK.name} recorded')
    return n


def verify(base, require_check=False):
    problems, rows = [], []
    recorded = {}
    if CHECK.is_file():
        chk = json.loads(CHECK.read_text(encoding='utf-8'))
        recorded = chk.get('export_files_lf_sha256', {})
        if require_check:
            if chk.get('all_ok') is not True:
                problems.append(f'{rel(CHECK)} does not say all_ok: the host checks did not all pass')
            missing = [n for n in LAYOUT_NAMES if n not in recorded]
            if missing:
                problems.append(f'{rel(CHECK)} records no file hashes for {missing}')
    elif require_check:
        problems.append(f'{rel(CHECK)} is not here: the exports cannot be checked against the analysis machine')
    else:
        print(f'note: {rel(CHECK)} is not here, so the exports are checked here but not against the analysis machine')
    if 'original' in recorded:
        rows.append(('original', rel(ORIGINAL), f'{check_recorded("original", ORIGINAL, recorded["original"], problems)} '
                     f'files as recorded'))
    for name in ('frozen', 'multistart', 'skew'):
        d = base/name
        if not d.is_dir():
            problems.append(f'{rel(d)} is not there')
            continue
        lm = check_manifest_hashes(d, problems)
        if name == 'skew':
            what = f'{check_skew(d, lm, problems)} layers skewed, same as a fresh export'
        else:
            what = f'ZIP members; {check_zip_layout(name, d, problems)} orders fold to the same export'
        if name in recorded:
            what += f'; {check_recorded(name, d, recorded[name], problems)} files as recorded'
        rows.append((name, rel(d), what))
    for name, d, what in rows:
        print(f'{name:<11} {d:<40} {what}')
    if problems:
        print('\nFAILED:')
        for p in problems:
            print('  ' + p)
        return 1
    print('all layout exports check out')
    return 0


def code_sha(path):
    """SHA-256 of a source file with CRLF read as LF (a Windows checkout may rewrite its line ends)."""
    return sha256(Path(path).read_bytes().replace(b'\r\n', b'\n'))


def earlier_bitstream():
    return json.loads(TRANSCRIBED.read_text(encoding='utf-8'))['bitstream_sha256']['value']


def bitstream_files(build):
    files = {}
    for n in ('system_wrapper.bit', 'system_wrapper.xsa'):
        p = build/n
        if p.is_file():
            files[n] = dict(bytes=p.stat().st_size, sha256=file_sha(p))
    if 'system_wrapper.bit' not in files:
        raise SystemExit(f'{build} has no system_wrapper.bit')
    return files


def export_dirs(exports):
    return {n: ORIGINAL if n == 'original' else exports/n for n in LAYOUT_NAMES}


def check_exports_against_prediction(pred, exports, problems):
    """Every layer's config.bin of every layout must be the one the prediction was made with."""
    from skew_count import skew_order
    n = 0
    for name, d in export_dirs(exports).items():
        if not (d/'manifest.json').is_file():
            problems.append(f'{rel(d)}: no manifest.json')
            continue
        man = json.loads((d/'manifest.json').read_text(encoding='utf-8'))
        for image, run in sorted(pred.get('runs', {}).get(name, {}).items()):
            want = run.get('layers') or []
            if [L.get('name') for L in want] != [L['name'] for L in man['layers']]:
                problems.append(f'{name} {image}: the layers of the prediction are not those of {rel(d)}')
                continue
            for node, L in zip(man['layers'], want):
                n += 1
                if not (d/node['config']).is_file() or file_sha(d/node['config']) != L.get('config_sha256'):
                    problems.append(f'{name} {image} {node["name"]}: {rel(d/node["config"])} is not the config.bin '
                                    f'the prediction was made with')
        if len(pred.get('runs', {}).get(name, {})) != 4:
            problems.append(f'the prediction has {len(pred.get("runs", {}).get(name, {}))} runs of {name}, not 4')
        taps = {L['name']: L['tap_order'] for L in man['layers'] if 'tap_order' in L}
        if name == 'skew':
            want = [int(v) for v in skew_order(288, 32)]
            if sorted(taps) != sorted(f'conv{i}' for i in range(2, 10)) or any(o != want for o in taps.values()):
                problems.append(f'{rel(d)}: the tap orders are not the skew order of the prediction on conv2..conv9')
            if pred.get('layouts', {}).get('skew', {}).get('order_288_32') != want:
                problems.append('the skew order of the prediction is not skew_count.skew_order(288, 32)')
        elif taps:
            problems.append(f'{rel(d)}: {name} has tap orders on {sorted(taps)}')
    return n


def record_bitstream(build, record, exports, allow_other=False):
    """Pin the bitstream, the prediction, the exports and the driver before the first run; recheck on a rerun."""
    import compare_board_2                         # the prediction, read the way the comparison reads it
    build, exports = Path(build).resolve(), Path(exports).resolve()
    problems = []
    files = bitstream_files(build)
    bit = files['system_wrapper.bit']['sha256']
    earlier = earlier_bitstream()

    pred_rec, p = compare_board_2.prediction_git_state()
    problems += p
    pred = compare_board_2.load_prediction()
    if pred is not None:
        if pred.get('all_checks_passed') is not True:
            problems.append(f'{pred_rec["file"]} does not say all_checks_passed')
        for lay in compare_board_2.LAYOUTS:
            for im in compare_board_2.IMAGES:
                _, why = compare_board_2.prediction_of(pred, lay, im)
                if why:
                    problems.append(why)
        configs = check_exports_against_prediction(pred, exports, problems)
    else:
        configs = 0
    rec = dict(
        what='what the PROTOCOL_2 board runs in this folder are made with, pinned before the first run '
             '(bankperm/prepare_layouts.py --bitstream); a rerun of RUN_W4_LAYOUTS.cmd refuses any change',
        build=build.name, files=files, earlier_canary_bitstream_sha256=earlier,
        matches_earlier_canary_bitstream=bit == earlier, other_bitstream_allowed=bool(allow_other and bit != earlier),
        prediction={k: pred_rec.get(k) for k in ('file', 'git_blob', 'lf_sha256', 'committed_in', 'committed_at',
                                                 'commit_on_a_remote_branch', 'head')},
        exports={n: dict(path=rel(d), files={q.name: lf_sha(q) for q in sorted(d.iterdir()) if q.is_file()})
                 for n, d in export_dirs(exports).items() if d.is_dir()},
        config_bins_equal_to_the_prediction=configs if not problems else None,
        code={n: code_sha(ROOT/n) for n in CODE})
    if record.is_file():
        old = json.loads(record.read_text(encoding='utf-8'))
        what = dict(files='bitstream', exports='layout export', code='driver (run_denoise.py, run_cifar.py, '
                    'run_board_xsdb.tcl)')
        changed = [what[k] for k in ('files', 'exports', 'code') if old.get(k) != rec[k]]
        if (old.get('prediction') or {}).get('git_blob') != rec['prediction']['git_blob']:
            changed.append('prediction')
        if changed:
            problems.append(f'{rel(record)} pins another {", ".join(changed)} than is here now (the earlier runs '
                            f'used {old.get("build")}, bitstream {old.get("files", {}).get("system_wrapper.bit", {}).get("sha256")}). '
                            f'All runs of one comparison must be made with one setup: move '
                            f'{rel(record.parent)} away to start over')
    elif bit != earlier and not allow_other:
        others = []
        for q in sorted(build.parent.glob('zed_v4_p16_t4_w4_*')):
            if (q/'system_wrapper.bit').is_file():
                h = file_sha(q/'system_wrapper.bit')
                others.append(q.name + ' ' + h[:12] + (' (the earlier canary bitstream)' if h == earlier else ''))
        problems.append(f'build/{build.name}/system_wrapper.bit has SHA-256 {bit}, not the {earlier} of the earlier '
                        f'W=4 canary (bankperm/board_transcribed.json), the existing bitstream PROTOCOL_2.md names. '
                        f'W=4 builds here: {"; ".join(others)}. Move the newer build folder out of build, or give '
                        f'allow-other-bitstream as the second argument of RUN_W4_LAYOUTS.cmd to use this one '
                        f'(the record will say so)')
    if problems:
        print('NOT PINNED:')
        for q in problems:
            print('  ' + q)
        return 1
    if record.is_file():
        print(f'setup as pinned in {rel(record)}: bitstream {build.name} {bit[:16]}..., prediction blob '
              f'{rec["prediction"]["git_blob"][:12]}, {len(rec["exports"])} exports, {len(rec["code"])} driver files')
        return 0
    rec['pinned_utc'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_bytes(json.dumps(rec, indent=1).encode('utf-8') + b'\n')
    which = 'the earlier canary bitstream' if bit == earlier else 'NOT the earlier canary bitstream, allowed'
    print(f'pinned -> {rel(record)}: bitstream {build.name} {bit[:16]}... ({which}), prediction '
          f'{rec["prediction"]["file"]} blob {rec["prediction"]["git_blob"][:12]} committed in '
          f'{(rec["prediction"]["committed_in"] or "?")[:12]}, {configs} config.bin as predicted')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--out', type=Path, help='unpack the Frozen and Multi-start ZIPs under this folder')
    g.add_argument('--verify', type=Path, help='check the frozen, multistart and skew exports under this folder')
    g.add_argument('--bitstream', type=Path, help='a build folder: pin it, the prediction and the exports in --record')
    ap.add_argument('--record', type=Path, help='with --bitstream: the JSON to write or check')
    ap.add_argument('--exports', type=Path, help='with --bitstream: the folder holding frozen, multistart, skew')
    ap.add_argument('--allow-other-bitstream', action='store_true',
                    help='with --bitstream: accept a bitstream that is not the earlier W=4 canary bitstream')
    ap.add_argument('--require-check', action='store_true',
                    help=f'with --verify: fail if {CHECK.name} is missing, not all_ok, or lacks a layout')
    args = ap.parse_args()
    if args.out:
        for name in ZIPS:
            unpack(name, args.out.resolve())
        return 0
    if args.bitstream:
        if not (args.record and args.exports):
            raise SystemExit('--bitstream needs --record and --exports')
        return record_bitstream(args.bitstream, args.record.resolve(), args.exports, args.allow_other_bitstream)
    return verify(args.verify.resolve(), args.require_check)


if __name__ == '__main__':
    sys.exit(main())
