"""Write the binary blobs the Zedboard application streams through window_mac_axis.

Four little-endian uint32 files, laid out to match sw/window_mac_test.c:

  config.bin   COUT*K weight words (one weight per word, low byte) then COUT bias
               words -- exactly the order the wrapper's configuration walker expects
  input.bin    NWIN * K/4 words, four activations per word, byte aligned
  gold.bin     NWIN * COUT words, the integer oracle, window then channel order
  layout.json  sizes, addresses, expected cycle counts and checksums

Load them over JTAG before running the application:

  dow -data config.bin 0x10000000
  dow -data input.bin  0x10100000
  dow -data gold.bin   0x10300000

The activation stream repeats each frame when mode_seq=2 (dense then sparse), so
input.bin already contains the exact byte sequence the DMA sends -- the PS does one
MM2S transfer of the whole file and nothing reorders on the fly.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from legacy_run_checks import read_probe, sha  # noqa: E402

ADDR = dict(config=0x10000000, input=0x10100000, result=0x10200000, gold=0x10300000)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', default='evaluation', choices=['evaluation', 'calibration'])
    ap.add_argument('--frames', type=int, default=0,
                    help='frames to take from the split (0 = all 512)')
    ap.add_argument('--mode-seq', type=int, default=2, choices=[0, 1, 2],
                    help='0 all dense, 1 all sparse, 2 alternate (matches the bench)')
    ap.add_argument('--out', type=Path, default=ROOT/'build'/'board')
    args = ap.parse_args()

    path = ROOT/'data'/(args.split+'.wpr')
    x, w, b, ids, y = read_probe(path)
    if args.frames:
        x, y, ids = x[:args.frames], y[:args.frames], ids[:args.frames]
    k, cout, n = len(w[0]), len(w), len(x)
    if k % 4:
        raise SystemExit(f'K={k} is not a multiple of 4; the wrapper packs four per beat')

    windows = [(f, m) for f in range(n) for m in (0, 1)] if args.mode_seq == 2 \
        else [(f, args.mode_seq) for f in range(n)]

    oracle = [[max(0, bias+sum(a*wt for a, wt in zip(row, weights)))
               for bias, weights in zip(b, w)] for row in x]
    if y is not None and oracle != y:
        raise SystemExit('WPROBE gold disagrees with the Python integer oracle')

    args.out.mkdir(parents=True, exist_ok=True)

    # config.bin -- weights channel-major then tap, then biases
    cfg = bytearray()
    for ci in range(cout):
        for t in range(k):
            cfg += struct.pack('<I', w[ci][t] & 0xFF)
    for ci in range(cout):
        cfg += struct.pack('<i', b[ci])
    (args.out/'config.bin').write_bytes(cfg)

    # input.bin -- four activations per word, in window order
    act = bytearray()
    for frame, _mode in windows:
        row = x[frame]
        for t in range(0, k, 4):
            act += struct.pack('<I', row[t] | (row[t+1] << 8) | (row[t+2] << 16) | (row[t+3] << 24))
    (args.out/'input.bin').write_bytes(act)

    # gold.bin -- window order then channel order
    gold = bytearray()
    for frame, _mode in windows:
        for ci in range(cout):
            gold += struct.pack('<I', oracle[frame][ci])
    (args.out/'gold.bin').write_bytes(gold)

    layout = dict(
        split=args.split, source_sha256=sha(path), K=k, COUT=cout, frames=n,
        windows=len(windows), mode_seq=args.mode_seq,
        config_words=cout*k+cout, input_words=len(windows)*k//4, gold_words=len(windows)*cout,
        addresses={name: hex(a) for name, a in ADDR.items()},
        sizes_bytes=dict(config=len(cfg), input=len(act), gold=len(gold),
                         result=len(windows)*cout*4),
        sha256={f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(args.out.glob('*.bin'))},
        note='CYCLES is only comparable with RESULTS_KO.md when IN_STALL and OUT_STALL read 0.')
    (args.out/'layout.json').write_text(json.dumps(layout, indent=2)+'\n', encoding='utf-8')

    print(f'{args.split}: {n} frames -> {len(windows)} windows, K={k}, COUT={cout}')
    for name in ('config', 'input', 'gold'):
        f = args.out/(name+'.bin')
        print(f'  {f.name:<12} {f.stat().st_size:>9} bytes  load at {layout["addresses"][name]}')
    print(f'  results land at {layout["addresses"]["result"]} '
          f'({layout["sizes_bytes"]["result"]} bytes)')
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
