"""Export a CONTIGUOUS grid of windows so the output can be shown as a feature map.

The probe in data/*.wpr holds 64 windows per image taken from scattered positions
(consecutive windows share no taps -- checked), so its outputs cannot be arranged
into a picture. This script takes one image and walks a contiguous HxW patch of
features.3 window positions instead, in row-major order, which is what a feature
map figure needs.

It reuses build/board/config.bin unchanged: the weights do not depend on which
windows are chosen, so only input.bin and gold.bin are rewritten. That makes the
weights the board holds the ones to compute gold with, so they are read back out
of the probe (verified byte-identical to config.bin) rather than re-derived from
torch -- the first version re-derived them and every output disagreed.

Two things the first version also got wrong, both now checked rather than assumed:

  * The reference is ReLU(bias + dot), not the bare dot product. A gold file with
    a negative value in it is wrong by construction.
  * Taps run spatially first and channel last, index (ky*3 + kx)*64 + cin. The
    weight autocorrelation says so (lag 1 across channels is 0.02, lag 64 and
    192 across space are 0.28 and 0.39), and find_tap_order() below pins down
    which of the six axis orders it is by matching torch's weights against the
    probe's.

  python scripts/export_featuremap.py --image images/evaluation/전투기.jpg --size 32

Then run scripts/run_board_xsdb.tcl -- it reads the geometry back out of
featuremap.json, so there is nothing to edit -- and keep the results.bin it
writes. fig8 reads that file.

The repository ships no images; --list prints the names and hashes of the ones
the probe was built from. Any photograph works here.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legacy_run_checks import read_probe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT/'build'/'board'
PROBE = ROOT/'data'/'evaluation.wpr'
K, COUT, CIN = 576, 128, 64


def round_half_even(a):
    """numpy's rint is ties-to-even, which is what metadata.json records."""
    return np.rint(a)


def oracle(xs, w, bias):
    """The reference the board is checked against: ReLU over an INT32 accumulator.

    legacy_run_checks.export_vectors computes exactly this, and it is what the
    gold in data/*.wpr holds.
    """
    y = xs.astype(np.int64) @ w.astype(np.int64).T + bias.astype(np.int64)
    y = np.maximum(0, y)
    assert y.max() <= 2**31 - 1, 'accumulator overflows INT32'
    return y.astype(np.int32)


def find_tap_order(conv_w, w_scale, probe_w):
    """Return the (cin, ky, kx) axis order the probe's 576 taps are laid out in.

    Rather than trust a reading of someone else's exporter, quantize torch's
    weights every way the three axes can be flattened and keep the one that
    reproduces the probe's weight matrix. The right order matches exactly; the
    wrong ones agree at chance.
    """
    from itertools import permutations
    cout = probe_w.shape[0]
    q = np.clip(round_half_even(conv_w/w_scale), -128, 127).astype(np.int32)
    scores = {}
    for perm in permutations((1, 2, 3)):          # axes of (cout, cin, ky, kx)
        cand = q.transpose((0,) + perm).reshape(cout, -1)
        scores[perm] = float(np.mean(cand == probe_w))
    best = max(scores, key=scores.get)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if scores[best] < 1.0:
        lines = '\n'.join(f'    axes {p} -> {v:.4f}' for p, v in ranked)
        raise SystemExit(
            'no tap order reproduces the probe weights exactly.\n'
            f'  agreement by axis order (1=cin, 2=ky, 3=kx):\n{lines}\n'
            '  If the best score is near 1 the ordering is right and the weight\n'
            '  quantization differs; if all scores are near 0.01 the layer or the\n'
            '  scale is wrong.')
    assert ranked[1][1] < 0.5, f'two orders match: {ranked[:2]}'
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', type=Path)
    ap.add_argument('--size', type=int, default=32,
                    help='side of the square window patch (size*size windows)')
    ap.add_argument('--top', type=int, default=0, help='patch origin row in the 112x112 map')
    ap.add_argument('--left', type=int, default=0, help='patch origin column')
    ap.add_argument('--out', type=Path, default=BOARD)
    ap.add_argument('--mode', type=int, default=0, choices=[0, 1, 2],
                    help='0 all dense (default), 1 all sparse, 2 alternate per window')
    ap.add_argument('--list', action='store_true',
                    help='print the images the probe was built from, and exit')
    ap.add_argument('--selftest', action='store_true',
                    help='check oracle() against the probe, and exit (no torch needed)')
    ap.add_argument('--verify', action='store_true',
                    help='check build/board against itself, and exit (no torch needed)')
    args = ap.parse_args()

    if args.verify:
        # The three files the board is given must agree with each other: whatever
        # is in input.bin, multiplied by whatever is in config.bin, must be what
        # is in gold.bin. The board matched this exact relation to the byte on the
        # original export, so a disagreement here is ours and a disagreement only
        # on hardware is not.
        import hashlib
        cfg = np.fromfile(BOARD/'config.bin', dtype='<i4')
        w = (((cfg[:COUT*K] & 0xff) ^ 0x80) - 0x80).reshape(COUT, K).astype(np.int32)
        bias = cfg[COUT*K:].astype(np.int32)
        inp = np.fromfile(BOARD/'input.bin', dtype=np.uint8)
        gold = np.fromfile(BOARD/'gold.bin', dtype='<i4')
        n = inp.size//K
        print(f'windows in input.bin : {n}')
        print(f'gold words           : {gold.size} (expected {n*COUT})')
        for f in ('config.bin', 'input.bin', 'gold.bin'):
            h = hashlib.sha256((BOARD/f).read_bytes()).hexdigest()
            print(f'  {f:11s} sha256 {h[:32]}')
        _, pw, pb, _, _ = read_probe(PROBE)
        print(f'config.bin == the probe weights: '
              f'{np.array_equal(w, np.array(pw, dtype=np.int32))}, '
              f'bias {np.array_equal(bias, np.array(pb, dtype=np.int32))}')
        if gold.size != n*COUT:
            raise SystemExit('gold.bin does not match input.bin in size')
        got = oracle(inp.reshape(n, K), w, bias).reshape(-1)
        bad = int((got != gold).sum())
        print(f'\nReLU(input @ config + bias) vs gold.bin: {bad} mismatches '
              f'in {gold.size}')
        if bad:
            i = int(np.argmax(got != gold))
            print(f'  first at word {i} (window {i//COUT} channel {i%COUT}): '
                  f'recomputed {got[i]}, file says {gold[i]}')
        raise SystemExit(0 if bad == 0 else 1)

    if args.selftest:
        x, w, b, _, y = read_probe(PROBE)
        got = oracle(np.array(x, dtype=np.uint8),
                     np.array(w, dtype=np.int32), np.array(b, dtype=np.int32))
        want = np.array(y, dtype=np.int32)
        assert got.shape == want.shape, (got.shape, want.shape)
        bad = int((got != want).sum())
        cfg = np.fromfile(BOARD/'config.bin', dtype='<i4') if (BOARD/'config.bin').exists() else None
        print(f'oracle vs probe gold: {bad} mismatches in {want.size} outputs')
        if cfg is not None:
            cw = (((cfg[:COUT*K] & 0xff) ^ 0x80) - 0x80).reshape(COUT, K)
            print(f'config.bin weights == probe weights: '
                  f'{np.array_equal(cw, np.array(w, dtype=np.int32))}')
            print(f'config.bin bias    == probe bias   : '
                  f'{np.array_equal(cfg[COUT*K:], np.array(b, dtype=np.int32))}')
        raise SystemExit(0 if bad == 0 else 1)

    meta_path = ROOT/'data'/'metadata.json'
    if args.list:
        # --list is the one mode that needs no image, so it is checked first.
        man = json.loads(meta_path.read_text(encoding='utf-8'))['manifest']
        for name, rec in sorted(man.items()):
            print(f"{rec['split']:12s} {name}  sha256 {rec['file_sha256'][:16]}...")
        return

    # The repository carries no images -- only their names and hashes in
    # metadata.json -- so say where the file was looked for instead of letting
    # PIL report a bare relative path. Any photograph works here: the figure
    # shows that hardware and software agree, not that this run reproduces the
    # original probe.
    if args.image is None:
        raise SystemExit('--image is required (or use --list)')
    img_path = args.image if args.image.is_absolute() else ROOT/args.image
    if not img_path.exists():
        raise SystemExit(
            f'no image at {img_path}\n'
            f'  The repository does not ship the images; metadata.json keeps only\n'
            f'  their names and hashes (run with --list to see them).\n'
            f'  Put any photograph there, or pass --image with its full path.')

    import torch
    from torchvision.models import vgg11, VGG11_Weights

    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    a_scale = meta['activation_scale']
    w_scale = meta['weight_scale']
    assert meta['layer'] == 'features.3' and meta['taps'] == K, meta['layer']

    weights = VGG11_Weights.IMAGENET1K_V1
    net = vgg11(weights=weights).eval()
    from PIL import Image
    x = weights.transforms()(Image.open(img_path).convert('RGB')).unsqueeze(0)

    with torch.no_grad():
        act = net.features[:3](x)[0].numpy()          # (64, 112, 112), pre-conv
    assert act.shape[0] == CIN, act.shape
    H, W = act.shape[1:]
    assert args.top + args.size <= H and args.left + args.size <= W, \
        f'patch {args.size} at ({args.top},{args.left}) does not fit in {H}x{W}'

    # Quantize activations the way metadata.json describes: scale, ties-to-even,
    # clip to 0..127. ReLU already made them non-negative, so there is no low clip
    # to get wrong.
    q = np.clip(round_half_even(act/a_scale), 0, 127).astype(np.uint8)

    # The board keeps config.bin from the original export, so the weights to
    # compute gold with are the ones already on it. read_probe returns exactly
    # what config.bin holds -- checked byte for byte -- so take them from there
    # and use torch's copy only to work out which way the taps are laid out.
    _, pw, pb, _, _ = read_probe(PROBE)
    pw = np.array(pw, dtype=np.int32)
    pb = np.array(pb, dtype=np.int32)
    assert pw.shape == (COUT, K) and pb.shape == (COUT,), (pw.shape, pb.shape)

    conv = net.features[3]
    perm = find_tap_order(conv.weight.detach().numpy(), w_scale, pw)
    print(f'tap order  : axes {perm} of (cin, ky, kx) -- matches config.bin exactly')

    # features.3 is 3x3 with padding 1, so window (r,c) covers rows r-1..r+1.
    pad = np.zeros((CIN, H + 2, W + 2), dtype=np.uint8)
    pad[:, 1:H+1, 1:W+1] = q

    # perm indexes into (cout, cin, ky, kx); drop the cout axis to index a window.
    wperm = tuple(a - 1 for a in perm)
    n = args.size*args.size
    xs = np.empty((n, K), dtype=np.uint8)
    i = 0
    for r in range(args.top, args.top + args.size):
        for c in range(args.left, args.left + args.size):
            xs[i] = pad[:, r:r+3, c:c+3].transpose(wperm).reshape(K)
            i += 1
    assert i == n

    # mode 2 runs every window twice, dense then sparse, so the stream has to
    # carry each one twice as well. The outputs are the same either way -- the
    # whole point of the core -- so this only changes what gets timed.
    if args.mode == 2:
        xs = np.repeat(xs, 2, axis=0)
        n *= 2

    y = oracle(xs, pw, pb)
    assert y.shape == (n, COUT) and y.min() >= 0

    nz = (xs != 0).sum(axis=1)
    print(f'nonzero taps per window: mean {nz.mean():.1f}/{K} '
          f'({nz.mean()/K:.3f}), min {nz.min()}, max {nz.max()}, '
          f'{int((nz == 0).sum())} empty')

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'input.bin').write_bytes(xs.reshape(-1).tobytes())
    (args.out/'gold.bin').write_bytes(y.astype('<i4').reshape(-1).tobytes())
    # The board script takes its geometry from layout.json, whichever exporter
    # wrote it, so write the same keys export_board_data.py does.
    (args.out/'layout.json').write_text(json.dumps({
        'split': 'featuremap', 'K': K, 'COUT': COUT,
        'frames': n//2 if args.mode == 2 else n,
        'mode_seq': args.mode, 'windows': n,
        'input_words': n*K//4, 'gold_words': n*COUT,
        'addresses': {'config': '0x10000000', 'input': '0x10100000',
                      'result': '0x10200000', 'gold': '0x10300000'},
    }, indent=2), encoding='utf-8')
    (args.out/'featuremap.json').write_text(json.dumps({
        'image': str(img_path.relative_to(ROOT) if img_path.is_relative_to(ROOT)
                     else img_path).replace('\\', '/'),
        'size': args.size,
        'top': args.top, 'left': args.left,
        'windows': n, 'COUT': COUT, 'K': K,
        'order': 'row-major over the patch; reshape gold to (size, size, COUT)',
        'mode': args.mode,
        'set_in_tcl': {'WM_FRAMES': n//2 if args.mode == 2 else n,
                       'WM_MODE_SEQ': args.mode},
    }, indent=2), encoding='utf-8')

    print(f'{img_path.name}: {n} contiguous windows ({args.size}x{args.size}) '
          f'from the {H}x{W} map')
    print(f'  input.bin  {n*K} bytes')
    print(f'  gold.bin   {n*COUT*4} bytes')
    print(f'  config.bin left alone -- weights do not depend on the window choice')
    frames = n//2 if args.mode == 2 else n
    print(f'\nRun scripts/run_board_xsdb.tcl -- it picks up frames={frames} '
          f'mode_seq={args.mode}'
          f' from featuremap.json, so nothing needs editing -- then'
          f'\n  python paper/figures/fig8_visual_check.py')


if __name__ == '__main__':
    main()
