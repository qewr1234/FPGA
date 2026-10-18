"""Profile im2col preprocessing and theoretical DDR stream bytes without Vivado or FPGA.

Input maps after the first layer are SYNTHETIC; timings measure NumPy im2col
packing on this host, not actual PS runtime or FPGA DMA/PL throughput.
"""
import argparse
import csv
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_cifar import im2col


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="dn_d10_c32_us_fx_qat")
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--max-cols-mib", type=int, default=128)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "q1_host_profile")
    args = parser.parse_args()

    if args.height <= 0 or args.width <= 0 or args.repeats <= 0:
        parser.error("height, width, and repeats must be positive")
    manifest_path = ROOT / "denoise" / "export" / args.model / "manifest.json"
    if not manifest_path.exists():
        parser.error("No INT8 export manifest: " + str(manifest_path))
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not man.get("graph") or not man.get("layers"):
        parser.error("Only graph-format integer model exports are supported")

    h = args.height + (-args.height % int(man.get("pad_to", 2 if man.get("unshuffle") else 1)))
    w = args.width + (-args.width % int(man.get("pad_to", 2 if man.get("unshuffle") else 1)))
    shapes = {"image": (4, h // 2, w // 2) if man.get("unshuffle") else (1, h, w)}
    rng = np.random.default_rng(42)
    rows = []
    for layer in man["layers"]:
        names = layer["inputs"]
        items = [shapes[n] for n in names]
        if len(set((item[1], item[2]) for item in items)) != 1:
            raise RuntimeError(f"Spatial mismatch at {layer['name']}: {items}")
        c = sum(item[0] for item in items)
        _, ih, iw = items[0]
        kh, kw = int(layer["kh"]), int(layer["kw"])
        dilation, stride = int(layer["dilation"]), int(layer["stride"])
        pad = dilation*(kh//2) if kh%2 else 0
        oh = (ih + 2*pad - dilation*(kh-1) - 1)//stride + 1
        ow = (iw + 2*pad - dilation*(kw-1) - 1)//stride + 1
        if oh < 1 or ow < 1:
            raise RuntimeError(f"Invalid output shape: {layer['name']}")
        k = c * kh * kw
        if k != layer["K"]:
            raise RuntimeError(f"K mismatch at {layer['name']}: {k} != {layer['K']}")
        n = oh*ow
        stream_bytes = n*k
        stream_w4_bytes = n * ((k + 3)//4*4)
        read_bytes = c*ih*iw
        out_bytes = n*int(layer["COUT"])*4
        measured_ms = None
        if stream_bytes <= args.max_cols_mib*1024**2:
            q = rng.integers(0, 128, (1,c,ih,iw), dtype=np.uint8)
            samples = []
            for _ in range(args.repeats):
                t0 = time.perf_counter()
                cols = im2col(q, kh=kh, kw=kw, pad=pad,
                              dilation=dilation, stride=stride)
                elapsed_ms = (time.perf_counter()-t0)*1000
                if cols.shape != (n,k) or cols.dtype != np.uint8:
                    raise RuntimeError(f"im2col output mismatch: {layer['name']}: {cols.shape}")
                samples.append(elapsed_ms)
            measured_ms = round(statistics.median(samples), 3)
            del q, cols
        post = layer["post"]
        cc = int(layer["COUT"])
        if post in ("maxout","avg"):
            if cc % 2:
                raise RuntimeError(f"Odd paired output channels at {layer['name']}")
            outshape=(cc//2,oh,ow)
        elif post == "shuffle2":
            if cc%4: raise RuntimeError("shuffle2 needs channels multiple of four")
            outshape=(cc//4,2*oh,2*ow)
        else:
            outshape=(cc,oh,ow)
        shapes[layer["name"]] = outshape
        rows.append(dict(layer=layer["name"], input_channels=c,
            input_h=ih, input_w=iw, windows=n, K=k, COUT=cc,
            input_feature_bytes=read_bytes, packed_w4_bytes=stream_w4_bytes,
            return_accumulator_bytes=out_bytes,
            expansion_ratio=round(stream_w4_bytes / read_bytes, 3),
            median_im2col_ms=measured_ms, repetitions=args.repeats if measured_ms is not None else 0))
        print(f"{layer['name']:<8} windows={n:>6} K={k:>4} "
              f"input={read_bytes/1048576:.2f} MiB packed={stream_w4_bytes/1048576:.2f} MiB "
              f"expand={stream_w4_bytes/read_bytes:.1f}x "
              f"im2col={str(measured_ms)+' ms' if measured_ms is not None else 'skipped'}",
              flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out/"layers.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(model=args.model, image_height=args.height, image_width=args.width,
       repeats=args.repeats, platform=platform.platform(), python=sys.version,
       numpy=np.__version__, synthetic_inputs=True,
       pack_input_bytes=sum(r["packed_w4_bytes"] for r in rows),
       output_accumulator_bytes=sum(r["return_accumulator_bytes"] for r in rows),
       input_map_lower_bound_bytes=sum(r["input_feature_bytes"] for r in rows),
       total_median_im2col_ms=sum(r["median_im2col_ms"] or 0 for r in rows),
       warning="Synthetic activations for im2col timing only. Byte counts assume per-layer "
               "uncompressed W=4 input and INT32 output streams; they exclude commands, "
               "weights, caching and actual DDR traffic. These are NOT FPGA/PS/DMA timings. "
               "The input-map sum is an optimistic data reuse lower-bound proxy, NOT a "
               "demonstrated hardware implementation.")
    (args.out/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n",
                                          encoding="utf-8")
    print("\nTotal per-image packed input: %.2f MiB" %
          (summary["pack_input_bytes"]/1048576))
    print("Total per-image INT32 output: %.2f MiB" %
          (summary["output_accumulator_bytes"]/1048576))
    print("Total median host im2col time (sum of layers): %.3f ms" %
          summary["total_median_im2col_ms"])
    print("Result:", args.out.resolve())
    print("This is a host preprocessing microbenchmark, NOT FPGA acceleration evidence.")


if __name__ == "__main__":
    main()
