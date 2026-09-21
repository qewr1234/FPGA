"""Export a CONTIGUOUS grid of windows so the output can be shown as a feature map.

The probe in data/*.wpr holds 64 windows per image taken from scattered positions
(consecutive windows share no taps -- checked), so its outputs cannot be arranged
into a picture. This script takes one image and walks a contiguous HxW patch of
features.3 window positions instead, in row-major order, which is what a feature
map figure needs.

It reuses build/board/config.bin unchanged: the weights and their scale do not
depend on which windows are chosen, so only input.bin and gold.bin are rewritten.
Run it where torch and the images are -- this container has neither, so it has
NOT been executed. Read the asserts: each one is a place where a wrong assumption
would otherwise pass silently.

  python scripts/export_featuremap.py --image images/evaluation/전투기.jpg --size 32

Then run scripts/run_board_xsdb.tcl -- it reads the geometry back out of
featuremap.json, so there is nothing to edit -- and keep the results.bin it
writes. fig8 reads that file.

The repository ships no images; --list prints the names and hashes of the ones
the probe was built from. Any photograph works here.
"""
import argparse
import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT/'build'/'board'
K, COUT, CIN = 576, 128, 64


def round_half_even(a):
    """numpy's rint is ties-to-even, which is what metadata.json records."""
    return np.rint(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', type=Path)
    ap.add_argument('--size', type=int, default=32,
                    help='side of the square window patch (size*size windows)')
    ap.add_argument('--top', type=int, default=0, help='patch origin row in the 112x112 map')
    ap.add_argument('--left', type=int, default=0, help='patch origin column')
    ap.add_argument('--out', type=Path, default=BOARD)
    ap.add_argument('--list', action='store_true',
                    help='print the images the probe was built from, and exit')
    args = ap.parse_args()

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

    conv = net.features[3]
    qw = round_half_even(conv.weight.detach().numpy()/w_scale).astype(np.int32)
    qw = np.clip(qw, -128, 127).reshape(COUT, K)
    qb = round_half_even(conv.bias.detach().numpy()/(a_scale*w_scale)).astype(np.int32)

    # features.3 is 3x3 with padding 1, so window (r,c) covers rows r-1..r+1.
    pad = np.zeros((CIN, H + 2, W + 2), dtype=np.uint8)
    pad[:, 1:H+1, 1:W+1] = q

    n = args.size*args.size
    xs = np.empty((n, K), dtype=np.uint8)
    i = 0
    for r in range(args.top, args.top + args.size):
        for c in range(args.left, args.left + args.size):
            xs[i] = pad[:, r:r+3, c:c+3].reshape(K)   # channel-major, matching qw
            i += 1
    assert i == n

    y = xs.astype(np.int32) @ qw.T + qb               # (n, COUT) int32
    assert y.shape == (n, COUT)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'input.bin').write_bytes(xs.reshape(-1).tobytes())
    (args.out/'gold.bin').write_bytes(y.astype('<i4').reshape(-1).tobytes())
    (args.out/'featuremap.json').write_text(json.dumps({
        'image': str(img_path.relative_to(ROOT) if img_path.is_relative_to(ROOT)
                     else img_path).replace('\\', '/'),
        'size': args.size,
        'top': args.top, 'left': args.left,
        'windows': n, 'COUT': COUT, 'K': K,
        'order': 'row-major over the patch; reshape gold to (size, size, COUT)',
        'set_in_tcl': {'WM_FRAMES': n, 'WM_MODE_SEQ': 1},
    }, indent=2), encoding='utf-8')

    print(f'{img_path.name}: {n} contiguous windows ({args.size}x{args.size}) '
          f'from the {H}x{W} map')
    print(f'  input.bin  {n*K} bytes')
    print(f'  gold.bin   {n*COUT*4} bytes')
    print(f'  config.bin left alone -- weights do not depend on the window choice')
    print(f'\nRun scripts/run_board_xsdb.tcl -- it picks up frames={n} mode_seq=1'
          f' from featuremap.json, so nothing needs editing -- then'
          f'\n  python paper/figures/fig8_visual_check.py')


if __name__ == '__main__':
    main()
