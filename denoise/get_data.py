"""Download the standard denoising images into denoise/data/.

    python denoise/get_data.py

Train400 (400 BSD images, 180x180), Set12 and BSD68, grayscale PNG, from the
DnCNN repository (github.com/cszn/DnCNN) at a pinned commit so the data never
changes underneath a result. About 16 MB, standard library only. Files that
are already there are not downloaded again.
"""
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMIT = 'e93b27812d3ff523a3a79d19e5e50d233d7a8d0a'
BASE = f'https://raw.githubusercontent.com/cszn/DnCNN/{COMMIT}/'
SETS = {
    'Train400': ('TrainingCodes/DnCNN_TrainingCodes_v1.0/data/Train400',
                 [f'test_{i:03d}.png' for i in range(1, 401)]),
    'Set12':    ('testsets/Set12', [f'{i:02d}.png' for i in range(1, 13)]),
    'BSD68':    ('testsets/BSD68', [f'test{i:03d}.png' for i in range(1, 69)]),
}


def main():
    for name, (remote, files) in SETS.items():
        dest = HERE/'data'/name
        dest.mkdir(parents=True, exist_ok=True)
        got = 0
        for f in files:
            out = dest/f
            if out.exists() and out.stat().st_size > 0:
                continue
            try:
                with urllib.request.urlopen(BASE + remote + '/' + f, timeout=60) as r:
                    out.write_bytes(r.read())
                got += 1
            except Exception as e:
                sys.exit(f'failed to download {remote}/{f}: {e}')
        print(f'{name:<9} {len(files):>3} images in {dest}  ({got} downloaded)')


if __name__ == '__main__':
    main()
