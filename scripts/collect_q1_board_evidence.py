"""Copy the raw reports of the W=4 layout board runs from build/ into the repository.

    python scripts/collect_q1_board_evidence.py            # on the board PC, from the repo root
    python scripts/collect_q1_board_evidence.py --dry-run  # list what would be copied

The W=4 canary (scripts/q1_existing_w4_canary.py) and the three-layout triplet
(scripts/q1_fpga_triplet.py) wrote their results under build/, which git
ignores:

    build/q1_existing_w4_canary/<run>/canary.json, original/report.json
    build/q1_bank_fpga_triplet/<run>/triplet_summary.json(.md),
        rep_NN/{original,frozen,multistart}/report.json, rep_NN/*_vs_*.json

This copies every JSON, Markdown and log/text file of those runs (the reports
carry per-layer CYCLES, IN_STALL, OUT_STALL, core ID and the oracle check) to
denoise/board_runs/q1_layouts/<same relative path>, and records, without copying,
the size and SHA-256 of everything else (PNG, NPZ, the _io board-file folders)
and of the bitstream named in triplet_summary.json. MANIFEST.json lists both.
Nothing in build/ is changed or deleted.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ('q1_existing_w4_canary', 'q1_bank_fpga_triplet')
COPY = {'.json', '.md', '.log', '.txt'}
MAX_COPY = 2 << 20          # a text file larger than 2 MB is hashed, not copied


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', type=Path, default=ROOT/'build')
    ap.add_argument('--dest', type=Path, default=ROOT/'denoise'/'board_runs'/'q1_layouts')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    copied, hashed, bits = [], [], []
    for run in RUNS:
        base = args.build/run
        if not base.is_dir():
            print(f'not found: {base}')
            continue
        for f in sorted(p for p in base.rglob('*') if p.is_file()):
            rel = f.relative_to(args.build)
            if f.suffix.lower() in COPY and f.stat().st_size <= MAX_COPY:
                copied.append(str(rel).replace('\\', '/'))
                if not args.dry_run:
                    out = args.dest/rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, out)
            else:
                hashed.append(dict(path=str(rel).replace('\\', '/'), bytes=f.stat().st_size, sha256=sha256(f)))
        for summary in base.rglob('triplet_summary.json'):
            build = json.loads(summary.read_text(encoding='utf-8')).get('build_path')
            bit = Path(build)/'system_wrapper.bit' if build else None
            if bit is not None and bit.is_file():
                bits.append(dict(summary=str(summary.relative_to(args.build)).replace('\\', '/'),
                                 bitstream=bit.name, build_dir=Path(build).name, sha256=sha256(bit)))
    if not copied:
        sys.exit('no board reports found under ' + str(args.build) + ' (run this on the PC that ran the board)')
    manifest = dict(what='raw reports of the W=4 canary and three-layout board runs, copied from build/ '
                         'by scripts/collect_q1_board_evidence.py; other files hashed only',
                    copied=copied, hashed_only=hashed, bitstreams=bits)
    print(f'{len(copied)} files to copy, {len(hashed)} hashed only, {len(bits)} bitstream hash(es)')
    for c in copied:
        print('  copy', c)
    if args.dry_run:
        return
    args.dest.mkdir(parents=True, exist_ok=True)
    (args.dest/'MANIFEST.json').write_text(json.dumps(manifest, indent=1)+'\n', encoding='utf-8')
    print('wrote', args.dest/'MANIFEST.json')


if __name__ == '__main__':
    main()
