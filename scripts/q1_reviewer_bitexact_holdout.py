"""Frozen-reorder full-image INT8-equivalence audit on BSD68 using GPU.

Reuses the original and reordered integer manifests and their real int8
weights. Every image must have exactly identical final uint8 pixels.
Additionally, each convolution's first 64 windows are checked against the
independent pure-integer matrix oracle by create_runner.

No training, no calibration, no retuning; no Vivado, RTL or FPGA used.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))

from common import QMAX_A, load_set, psnr, test_noise
from run_denoise import load_layers
from q1_reviewer_bank import create_runner


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",default="dn_d10_c32_us_fx_qat")
    ap.add_argument("--set",default="BSD68",choices=["BSD68","Set12"])
    ap.add_argument("--orig",type=Path,default=None)
    ap.add_argument("--reordered",type=Path,default=None)
    ap.add_argument("--device",choices=["auto","cuda","cpu"],default="auto")
    ap.add_argument("--out",type=Path,
                    default=ROOT/"build"/"q1_reviewer_bitexact_holdout")
    args=ap.parse_args()
    orig=args.orig or ROOT/"denoise"/"export"/args.model
    reordered=args.reordered or ROOT/"build"/"q1_reviewer_export"/args.model
    if not (orig/"manifest.json").is_file() or not (reordered/"manifest.json").is_file():
        ap.error("Missing original or reordered manifest. First run RUN_GPU_Q1_REVIEW.cmd")
    ma,la=load_layers(orig)
    mb,lb=load_layers(reordered)
    if ma["model"]!=mb["model"] or ma["model"]!=args.model:
        ap.error("Model name mismatch")
    if len(la)!=len(lb):
        ap.error("Layer count mismatch")
    for a,b in zip(la,lb):
        if (a["name"],a["K"],a["COUT"])!=(b["name"],b["K"],b["COUT"]):
            ap.error("Layer shape or name mismatch")
    perm=json.loads((reordered/"permutation_manifest.json").read_text(encoding="utf-8"))
    if len(perm["orders"])!=8:
        ap.error("Unexpected number of channel reorders")
    import torch
    device=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if device=="cuda" and not torch.cuda.is_available():
        ap.error("CUDA not available")
    print(f"Device: {device}; network: {args.model}; evaluation set: {args.set}",flush=True)
    run_a=create_runner(la,device)
    run_b=create_runner(lb,device)
    samples=test_noise(load_set(args.set),ma["sigma"],seed=0)
    expected=68 if args.set=="BSD68" else 12
    if len(samples)!=expected:
        raise AssertionError(f"Expected {expected} images, got {len(samples)}")
    expected_psnr=json.loads((orig/"int_eval.json").read_text(encoding="utf-8"))[args.set]["per_image"]
    rows=[]
    for name,clean,noisy in samples:
        x=np.rint(noisy*QMAX_A).astype(np.uint8)
        _,a=run_a(x)
        _,b=run_b(x)
        if a.shape!=b.shape or a.dtype!=np.uint8 or b.dtype!=np.uint8:
            raise AssertionError(f"{name}: image dtype/shape disagreement")
        miss=int(np.count_nonzero(a!=b))
        pa=float(psnr(clean,a.astype(np.float32)/255))
        pb=float(psnr(clean,b.astype(np.float32)/255))
        ref=float(expected_psnr[name])
        row=dict(image=name,mismatch_pixels=miss,original_psnr_db=round(pa,9),
                 reordered_psnr_db=round(pb,9),
                 psnr_delta_db=round(pb-pa,9),original_eval_psnr_diff_db=round(pa-ref,9))
        rows.append(row)
        if miss or abs(pa-ref)>1e-5:
            raise AssertionError(f"{name}: FAIL pixels={miss} "
                                 f"source PSNR mismatch={pa-ref:.9f} dB")
        print(f"{name}: PASS output mismatch=0; PSNR={pa:.6f} dB",flush=True)
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/"per_image.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    summary=dict(
        status="PASS_GPU_INT8_EXPORT_FULL_IMAGES",
        model=args.model,data_set=args.set,noise_seed=0,sigma=ma["sigma"],
        images_checked=len(rows),pixel_mismatches=sum(r["mismatch_pixels"] for r in rows),
        max_abs_psnr_delta_db=max(abs(r["psnr_delta_db"]) for r in rows),
        source_path=str(orig),reordered_path=str(reordered),
        per_image_file="per_image.csv",
        cpu_integer_oracle_window_subset_per_layer=64,
        warnings=[
            "Full-image equality and sampled convolution INT32 checks were performed "
            "through PyTorch convolution with exact integer-oracle spot checks.",
            "This is NOT a full pure-integer oracle for every intermediate pixel. "
            "The existing CPU emulator independently confirmed two images earlier.",
            "No physical FPGA, DMA or end-to-end performance was measured.",
            "PSNR parity comes from identical uint8 outputs; this is not image-quality "
            "improvement, and says nothing about novelty."
        ])
    (args.out/"report.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",
                                         encoding="utf-8")
    print(f"\nPASS: {len(rows)} images, total mismatched output pixels=0")
    print("Saved:",(args.out/"report.json").resolve())
    print("Not FPGA hardware validation.")


if __name__=="__main__":
    main()
