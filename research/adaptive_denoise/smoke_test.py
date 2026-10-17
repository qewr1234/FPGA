"""Model-free CPU checks; requires project dependencies, not datasets/checkpoints."""
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"denoise"))
from train_denoise import Denoiser
from screen import (adaptive_image, blend_mask, expanded_box, gaussian3,
                    halo_for, infer, score_tiles, tiles_for)


def run():
    torch.set_num_threads(2)
    torch.manual_seed(7)
    rng = np.random.default_rng(3)
    for unshuffle, combine in [(False, "none"), (True, "maxout")]:
        net = Denoiser(depth=4, channels=4, skip=True,
                       unshuffle=unshuffle, combine=combine).eval()
        for h, w in [(36, 40), (39, 43), (64, 65)]:
            a = rng.random((h, w), dtype=np.float32)
            boxes = tiles_for(h, w, 32)
            full = infer(net, a, torch.device("cpu"))
            fast = gaussian3(a)
            selected = set(range(len(boxes)))
            cropped, ratio = adaptive_image(net, a, fast, boxes, selected,
                                            torch.device("cpu"), halo_for(net), 0, 32)
            max_error = float(np.max(np.abs(cropped-full)))
            if max_error >= 2e-4:
                raise AssertionError((unshuffle, combine, (h, w), max_error))
            assert ratio >= 1.
            for gate in ("texture","residual","random"):
                assert np.isfinite(score_tiles(a, boxes, gate, rng)).all()
            for b in boxes:
                ya,yb,xa,xb = expanded_box(b,h,w,halo_for(net),unshuffle)
                assert ya <= b[0] < b[1] <= yb and xa <= b[2] < b[3] <= xb
            assert blend_mask(boxes[0],0,{(boxes[0][0],boxes[0][2])},
                              32,h,w,8).shape == (boxes[0][1]-boxes[0][0],
                                                   boxes[0][3]-boxes[0][2])
        print(f"PASS: unshuffle={unshuffle}; combine={combine}")
    print("PASS: all CPU smoke checks. GPU and physical FPGA remain untested.")


if __name__ == "__main__":
    run()
