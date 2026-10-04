"""Data, noise and metrics shared by the denoiser scripts.

The setting is the standard one for Gaussian denoising (DnCNN, Zhang et al.
2017, TIP): train on the 400 BSD images of 180x180 ("Train400"), test on Set12
and BSD68, additive white Gaussian noise of sigma 25 on the 0..255 scale.

Two things differ from the paper, both forced by the accelerator, and every
number this project reports -- the baselines included -- is measured in this
setting, never copied from the paper:

  * The noisy image is CLIPPED to the pixel range [0, 1]. The core's input port
    is unsigned, and a camera clips anyway. Clipping removes part of the noise,
    so a clipped noisy image already scores a little higher than the paper's.
  * The noisy image is then QUANTIZED to 7 bits (0..127), because that is the
    width of the input port. One 7-bit step is 2/255 of the range: its own
    error is about 53 dB PSNR, far below the 20 dB noise it rides on.

Images come from the DnCNN repository at a pinned commit (get_data.py).
"""
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE/'data'
QMAX_A = 127            # the core's input port: unsigned 7 bit


def load_gray(path):
    """8-bit grayscale image as float32 in [0, 1]."""
    im = Image.open(path)
    if im.mode != 'L':
        im = im.convert('L')
    return np.asarray(im, dtype=np.float32)/255.0


def load_set(name):
    d = DATA/name
    files = sorted(d.glob('*.png'))
    if not files:
        raise SystemExit(f'no images in {d}: run  python denoise/get_data.py  first')
    return [(f.name, load_gray(f)) for f in files]


def add_noise(clean, sigma, rng):
    """AWGN of sigma (on the 0..255 scale), then clip to [0, 1], then 7 bits.

    Returns the noisy image as the float it represents (q/127) -- exactly what
    the integer pipeline feeds the core, divided by its scale.
    """
    noisy = clean + rng.standard_normal(clean.shape).astype(np.float32)*(sigma/255.0)
    return quantize_input(noisy)


def quantize_input(x):
    return np.rint(np.clip(x, 0.0, 1.0)*QMAX_A).astype(np.float32)/QMAX_A


def psnr(ref, img):
    """PSNR in dB of img against ref, both in [0, 1], img clipped to range."""
    mse = float(np.mean((np.clip(img, 0, 1) - ref)**2))
    return 10*np.log10(1.0/mse) if mse > 0 else float('inf')


def test_noise(images, sigma, seed=0):
    """The same noisy copies of a test set on every run, for every method."""
    rng = np.random.default_rng(seed)
    return [(n, c, add_noise(c, sigma, rng)) for n, c in images]
