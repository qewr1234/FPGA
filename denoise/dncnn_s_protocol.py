"""The public DnCNN-S (sigma 25) weights under the paper's input protocol.

    python denoise/dncnn_s_protocol.py <path to cszn/DnCNN .../models/DnCNN_sigma25/model.pth>

The paper's networks are trained and tested on noisy images clipped to [0, 1]
and quantized to 7 bits (the core's input port), so the literature figures of
DnCNN-S (30.44 / 29.23 dB, unclipped float noise) are not the same test. This
script evaluates the official PyTorch DnCNN-S checkpoint (cszn/DnCNN,
TrainingCodes/dncnn_pytorch, 556k parameters, trained on unclipped noise) on
the same seed-0 noise draws the paper uses, once unclipped and once under the
paper's protocol, so the table can carry one CNN baseline measured on the
same input. Result: dncnn_s_protocol.json beside this file (about 5 minutes
on 4 cores).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import load_set, psnr, quantize_input, test_noise  # noqa: E402

SIGMA = 25.0


class DnCNN(nn.Module):
    """cszn's class, needed because the checkpoint pickles the whole module under __main__.DnCNN."""

    def __init__(self, depth=17, n_channels=64, image_channels=1, use_bnorm=True, kernel_size=3):
        super().__init__()
        layers = [nn.Conv2d(image_channels, n_channels, 3, padding=1, bias=True), nn.ReLU(inplace=True)]
        for _ in range(depth - 2):
            layers += [nn.Conv2d(n_channels, n_channels, 3, padding=1, bias=False),
                       nn.BatchNorm2d(n_channels, eps=0.0001, momentum=0.95), nn.ReLU(inplace=True)]
        layers.append(nn.Conv2d(n_channels, image_channels, 3, padding=1, bias=False))
        self.dncnn = nn.Sequential(*layers)

    def forward(self, x):
        return x - self.dncnn(x)


def load(weights):
    import __main__
    __main__.DnCNN = DnCNN
    obj = torch.load(weights, map_location='cpu', weights_only=False)
    model = obj if isinstance(obj, nn.Module) else DnCNN()
    if not isinstance(obj, nn.Module):
        model.load_state_dict(obj)
    return model.eval()


def noisy_pairs(images, sigma, seed=0):
    """(name, clean, unclipped float noisy, paper-protocol noisy); the latter checked against common.test_noise."""
    rng = np.random.default_rng(seed)
    out = []
    for n, c in images:
        raw = c + rng.standard_normal(c.shape).astype(np.float32) * (sigma / 255.0)
        out.append((n, c, raw, quantize_input(raw)))
    for (n, _, _, q), (n2, _, q2) in zip(out, test_noise(images, sigma, seed=seed)):
        assert n == n2 and np.array_equal(q, q2), f'noise mismatch on {n}'
    return out


def main():
    weights = Path(sys.argv[1])
    torch.set_num_threads(4)
    model = load(weights)
    nparams = sum(p.numel() for p in model.parameters())

    @torch.no_grad()
    def run(x):
        t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))[None, None]
        return model(t)[0, 0].numpy()

    out = dict(model='DnCNN-S sigma25 (cszn/DnCNN TrainingCodes/dncnn_pytorch)', weights=str(weights),
               params=int(nparams), sigma=SIGMA, seed=0, sets={})
    out_path = HERE / 'dncnn_s_protocol.json'
    for set_name in ('Set12', 'BSD68'):
        data = noisy_pairs(load_set(set_name), SIGMA)
        res = {}
        for key, pick in (('unclipped', lambda raw, q7: raw), ('clip7', lambda raw, q7: q7)):
            t0 = time.time()
            per = {n: float(psnr(c, run(pick(raw, q7)))) for n, c, raw, q7 in data}
            res[key] = dict(mean=float(np.mean(list(per.values()))), per_image=per, seconds=round(time.time() - t0, 1))
            print(f'{set_name:<6} {key:<10} {res[key]["mean"]:7.3f} dB ({time.time() - t0:.0f} s)', flush=True)
        out['sets'][set_name] = res
        out_path.write_text(json.dumps(out, indent=2))
    print('wrote', out_path)


if __name__ == '__main__':
    main()
