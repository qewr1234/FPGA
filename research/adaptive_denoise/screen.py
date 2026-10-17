"""Screen tile-selective float CNN denoising against Gaussian and random selection.

This is an algorithm feasibility study, NOT a FPGA cycle/power benchmark.
Run with: python research/adaptive_denoise/screen.py --device cuda
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "denoise"))
from common import load_set, psnr, test_noise
from train_denoise import Denoiser


def parse_budgets(s):
    try:
        values = sorted(set(float(t) for t in s.split(",") if t.strip()))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not values or any(not 0 <= v <= 1 for v in values):
        raise argparse.ArgumentTypeError("budgets must be comma separated floats in [0,1]")
    return values


def tiles_for(h, w, size):
    return [(y, min(y+size, h), x, min(x+size, w))
            for y in range(0, h, size) for x in range(0, w, size)]


def gaussian3(x):
    """Separable 3x3 [1,2,1]/4 with edge replication."""
    a = np.pad(x.astype(np.float32), ((1, 1), (1, 1)), mode="edge")
    v = (a[:-2] + 2*a[1:-1] + a[2:]) * np.float32(0.25)
    return ((v[:, :-2] + 2*v[:, 1:-1] + v[:, 2:]) * np.float32(0.25)).astype(np.float32)


def score_tiles(noisy, boxes, method, rng):
    if method == "random":
        return rng.random(len(boxes))
    if method == "residual":
        diff = np.abs(noisy - gaussian3(noisy))
        return np.array([float(diff[y0:y1, x0:x1].mean())
                         for y0, y1, x0, x1 in boxes], dtype=np.float64)
    if method == "texture":
        dx = np.abs(noisy[:, 1:] - noisy[:, :-1])
        dy = np.abs(noisy[1:] - noisy[:-1])
        result = []
        for y0, y1, x0, x1 in boxes:
            hx = dx[y0:y1, x0:max(x0, x1-1)]
            hy = dy[y0:max(y0, y1-1), x0:x1]
            result.append((float(hx.mean()) if hx.size else 0.0) +
                          (float(hy.mean()) if hy.size else 0.0))
        return np.array(result, dtype=np.float64)
    raise ValueError(method)


def load_model(checkpoint, device):
    try:
        ck = torch.load(checkpoint, map_location="cpu", weights_only=True)
    except TypeError:
        ck = torch.load(checkpoint, map_location="cpu")
    if not isinstance(ck, dict) or ck.get("arch", "chain") != "chain" or ck.get("folded", False):
        raise ValueError("Expected an original float chain Denoiser checkpoint, not QAT/folded")
    if "state" not in ck:
        raise ValueError("Checkpoint has no state dict")
    net = Denoiser(
        depth=int(ck["depth"]), channels=int(ck["channels"]),
        skip=bool(ck.get("skip", True)), residual=bool(ck.get("residual", False)),
        unshuffle=bool(ck.get("unshuffle", False)), dilation=ck.get("dilation"),
        combine=ck.get("combine", "maxout" if ck.get("maxout", False) else "none"))
    net.load_state_dict(ck["state"], strict=True)
    return net.to(device).eval()


def halo_for(net):
    return int(math.ceil(net.receptive_field()/2)) + (2 if net.unshuffle else 1)


def expanded_box(box, h, w, halo, unshuffle):
    y0, y1, x0, x1 = box
    ya, xa = max(0, y0-halo), max(0, x0-halo)
    yb, xb = min(h, y1+halo), min(w, x1+halo)
    if unshuffle:
        ya -= ya % 2
        xa -= xa % 2
        yb = min(h, yb + yb % 2)
        xb = min(w, xb + xb % 2)
    return ya, yb, xa, xb


@torch.inference_mode()
def infer(net, noisy, device):
    x = torch.from_numpy(np.ascontiguousarray(noisy, dtype=np.float32))[None, None].to(device)
    y = net(x).clamp(0, 1)[0, 0].float().cpu().numpy()
    if y.shape != noisy.shape:
        raise RuntimeError(f"Network changed image size: {noisy.shape} to {y.shape}")
    return y


def blend_mask(box, index, active, size, h, w, fade):
    y0, y1, x0, x1 = box
    yy = np.ones(y1-y0, np.float32)
    xx = np.ones(x1-x0, np.float32)
    if fade == 0:
        return yy[:, None]*xx[None, :]

    def ramp(a, start):
        n = min(fade, a.size)
        z = np.arange(1, n+1, dtype=np.float32)/(n+1)
        if start:
            a[:n] *= z
        else:
            a[-n:] *= z[::-1]

    if y0 > 0 and (y0-size, x0) not in active:
        ramp(yy, True)
    if y1 < h and (y1, x0) not in active:
        ramp(yy, False)
    if x0 > 0 and (y0, x0-size) not in active:
        ramp(xx, True)
    if x1 < w and (y0, x1) not in active:
        ramp(xx, False)
    return yy[:, None]*xx[None, :]


def adaptive_image(net, noisy, fast, boxes, selected, device, halo, fade, tile, cache=None):
    h, w = noisy.shape
    out = fast.copy()
    active = {(boxes[i][0], boxes[i][2]) for i in selected}
    work = 0
    for i in sorted(selected):
        b = boxes[i]
        y0, y1, x0, x1 = b
        ya, yb, xa, xb = expanded_box(b, h, w, halo, net.unshuffle)
        work += (yb-ya)*(xb-xa)
        if cache is not None and i in cache:
            patch = cache[i]
        else:
            pred = infer(net, noisy[ya:yb, xa:xb], device)
            patch = pred[y0-ya:y1-ya, x0-xa:x1-xa]
            if cache is not None:
                cache[i] = patch
        alpha = blend_mask(b, i, active, tile, h, w, fade)
        out[y0:y1, x0:x1] = alpha*patch + (1-alpha)*fast[y0:y1, x0:x1]
    return out, work/(h*w)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, default=ROOT/"denoise/dn_d10_c32_us_mo_fx.pt")
    ap.add_argument("--set", dest="dataset", choices=("Set12", "BSD68"), default="Set12")
    ap.add_argument("--sigma", type=float, default=25.)
    ap.add_argument("--tile", type=int, default=128)
    ap.add_argument("--fade", type=int, default=8)
    ap.add_argument("--budgets", type=parse_budgets, default=parse_budgets("0,0.25,0.5,0.75,1"))
    ap.add_argument("--gates", default="texture,residual,random")
    ap.add_argument("--max-images", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    ap.add_argument("--out", type=Path, default=HERE/"runs"/"screen_v1")
    args = ap.parse_args()
    if args.tile < 16 or args.tile % 2:
        ap.error("tile must be even and >=16")
    if args.fade < 0 or args.fade >= args.tile//2:
        ap.error("fade must be between 0 and tile/2 exclusive")
    if args.sigma <= 0:
        ap.error("sigma must be positive")
    gates = list(dict.fromkeys(x.strip() for x in args.gates.split(",") if x.strip()))
    if not gates or set(gates)-{"texture", "residual", "random"}:
        ap.error("gates must consist of texture,residual,random")
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available()
                          else "cpu" if args.device == "auto" else args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        ap.error("CUDA unavailable: check your PyTorch installation")
    torch.manual_seed(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.allow_tf32 = False

    net = load_model(args.checkpoint, device)
    halo = halo_for(net)
    images = load_set(args.dataset)
    if args.max_images:
        images = images[:args.max_images]
    data = test_noise(images, args.sigma, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.time()
    print(f"Device: {device}, Torch: {torch.__version__}, model: {args.checkpoint.name}, "
          f"images: {len(data)}, tile: {args.tile}, halo: {halo}", flush=True)

    for image_i, (name, clean, noisy) in enumerate(data):
        h, w = clean.shape
        fast = gaussian3(noisy)
        full = infer(net, noisy, device)
        boxes = tiles_for(h, w, args.tile)
        bases = dict(image=name, height=h, width=w, noisy_psnr=psnr(clean, noisy),
                     fast_psnr=psnr(clean, fast), full_psnr=psnr(clean, full))
        for gate in gates:
            rng = np.random.default_rng(args.seed + 100003*image_i +
                  101*{"texture":1,"residual":2,"random":3}[gate])
            score = score_tiles(noisy, boxes, gate, rng)
            order = sorted(range(len(boxes)), key=lambda i:(-score[i], i))
            cache = {}
            for budget in args.budgets:
                count = min(len(boxes), max(0, int(math.ceil(budget*len(boxes)-1e-12))))
                selected = set(order[:count])
                if count == 0:
                    pred, work = fast, 0.
                elif count == len(boxes):
                    pred, work = full, 1.
                else:
                    pred, work = adaptive_image(net, noisy, fast, boxes, selected,
                                               device, halo, args.fade, args.tile, cache)
                selected_area = sum((boxes[j][1]-boxes[j][0])*(boxes[j][3]-boxes[j][2])
                                    for j in selected)/(h*w)
                rows.append(dict(**bases, gate=gate, budget=budget, selected_tiles=count,
                                total_tiles=len(boxes), selected_area=selected_area,
                                cnn_work_ratio=work, adaptive_psnr=psnr(clean, pred)))
        print(f"{image_i+1}/{len(data)} {name}: Gaussian {bases['fast_psnr']:.3f} dB; "
              f"CNN {bases['full_psnr']:.3f} dB", flush=True)

    with (args.out/"per_image.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for gate in gates:
        for budget in args.budgets:
            sub = [row for row in rows if row["gate"] == gate and row["budget"] == budget]
            mean = lambda key: float(np.mean([r[key] for r in sub]))
            summary.append(dict(gate=gate, budget=budget, images=len(sub),
                mean_adaptive_psnr=round(mean("adaptive_psnr"),5),
                mean_full_psnr=round(mean("full_psnr"),5),
                mean_fast_psnr=round(mean("fast_psnr"),5),
                mean_loss_to_full_db=round(mean("full_psnr")-mean("adaptive_psnr"),5),
                mean_selected_area=round(mean("selected_area"),5),
                mean_cnn_work_ratio=round(mean("cnn_work_ratio"),5)))
    with (args.out/"summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    try:
        rev = subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT,
                                      text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        rev = None
    manifest = dict(argv=sys.argv, git_commit=rev, checkpoint_sha256=sha256(args.checkpoint),
        device=str(device), gpu=torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        torch=torch.__version__, numpy=np.__version__, cuda=torch.version.cuda,
        dataset=args.dataset, sigma=args.sigma, seed=args.seed, tile=args.tile, fade=args.fade,
        halo=halo, seconds=round(time.time()-t0,1),
        warning="GPU FP32 feasibility only: cnn_work_ratio is crop pixel count / image pixel count, "
                "NOT measured FPGA cycles, latency, or power.")
    (args.out/"manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    print("\nGATE       BUDGET   PSNR   LOSS_TO_FULL   CNN_WORK_RATIO")
    for r in summary:
        print(f"{r['gate']:<11}{r['budget']:.2f}      {r['mean_adaptive_psnr']:.3f} "
              f"  {r['mean_loss_to_full_db']:+.3f} dB        {r['mean_cnn_work_ratio']:.3f}x")
    print(f"Saved: {args.out.resolve()}")
    print("This is a GPU feasibility screen; it does not measure FPGA speed or power.")


if __name__ == "__main__":
    main()
