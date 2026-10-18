"""Exhaustive full-image output equality stress for the existing frozen QAT export.

Compare original vs frozen bank-permuted exported model on Set12 and BSD68,
for AWGN σ 15,25,50 and RNG seeds 0,1,2, without re-optimizing anything.
Uses the CUDA inference pipeline and per-layer sampled independent INT32 oracle.

This is GPU/CPU equivalence only, NEVER physical FPGA board validation.
Results resume image-by-image, with manifest SHA256 consistency protection.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A,load_set,psnr,test_noise
from run_denoise import load_layers
from q1_reviewer_bank import create_runner

MODEL="dn_d10_c32_us_fx_qat"
COLS=("dataset","sigma","seed","image","mismatched_pixels","PSNR_original","PSNR_reordered","PSNR_delta")


def sha_export(directory):
    digest=hashlib.sha256()
    for p in sorted(directory.glob("conv*_config.bin")):
        digest.update(p.name.encode());digest.update(p.read_bytes())
    digest.update((directory/"manifest.json").read_bytes())
    return digest.hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sets",default="BSD68,Set12")
    ap.add_argument("--sigmas",default="15,25,50")
    ap.add_argument("--seeds",default="0,1,2")
    ap.add_argument("--device",choices=("auto","cpu","cuda"),default="auto")
    ap.add_argument("--max-images",type=int,default=0,help="debug only")
    ap.add_argument("--original",type=Path,
                    default=ROOT/"denoise"/"export"/MODEL)
    ap.add_argument("--candidate",type=Path,
                    default=ROOT/"build"/"q1_reviewer_export"/MODEL)
    ap.add_argument("--out",type=Path,
                    default=ROOT/"build"/"q1_gpu_bitexact_stress")
    args=ap.parse_args()
    sets=[s.strip() for s in args.sets.split(",") if s.strip()]
    sigmas=[int(s) for s in args.sigmas.split(",") if s.strip()]
    seeds=[int(s) for s in args.seeds.split(",") if s.strip()]
    if not sets or any(s not in {"BSD68","Set12"} for s in sets):
        ap.error("Only BSD68/Set12")
    if not sigmas or min(sigmas)<=0 or not seeds or min(seeds)<0:
        ap.error("Invalid sigma/seed")
    if args.max_images<0:ap.error("Negative max-images")
    ma,la=load_layers(args.original)
    mb,lb=load_layers(args.candidate)
    if ma["model"]!=MODEL or mb["model"]!=MODEL or len(la)!=10 or len(lb)!=10:
        raise ValueError("Original/reordered 10-layer QAT model does not match expected architecture")
    frozen=json.loads((args.candidate/"permutation_manifest.json").read_text(encoding="utf-8"))
    if len(frozen.get("orders",{}))!=8:
        raise ValueError("Expected immutable eight-layer channel mapping")
    import torch
    device=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if device=="cuda" and not torch.cuda.is_available():ap.error("CUDA unavailable")
    base_run=create_runner(la,device)
    perm_run=create_runner(lb,device)
    config=dict(model=MODEL,sets=sets,sigmas=sigmas,seeds=seeds,
                max_images=args.max_images,
                original_sha256=sha_export(args.original),
                candidate_sha256=sha_export(args.candidate))
    args.out.mkdir(parents=True,exist_ok=True)
    cf=args.out/"experiment_config.json"
    if cf.exists() and json.loads(cf.read_text(encoding="utf-8"))!=config:
        ap.error("Different configuration from old results; choose a different --out")
    cf.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
    output=args.out/"per_image.csv"
    completed=set()
    if output.exists():
        with output.open("r",newline="",encoding="utf-8") as f:
            completed={(r["dataset"],int(r["sigma"]),int(r["seed"]),r["image"])
                       for r in csv.DictReader(f)}
    refs=json.loads((args.original/"int_eval.json").read_text(encoding="utf-8"))
    for ds in sets:
        images=load_set(ds)
        for sigma in sigmas:
            for seed in seeds:
                for ind,(name,clean,noisy) in enumerate(test_noise(images,sigma,seed=seed)):
                    if args.max_images and ind>=args.max_images:break
                    key=(ds,sigma,seed,name)
                    if key in completed:continue
                    q=np.rint(noisy*QMAX_A).astype(np.uint8)
                    with torch.no_grad():
                        _,a=base_run(q)
                        _,b=perm_run(q)
                    if a.dtype!=np.uint8 or a.shape!=b.shape or a.dtype!=b.dtype:
                        raise AssertionError(f"{key}: shape/dtype mismatch")
                    mismatches=int(np.count_nonzero(a!=b))
                    pa=float(psnr(clean,a.astype(np.float32)/255))
                    pb=float(psnr(clean,b.astype(np.float32)/255))
                    if sigma==25 and seed==0:
                        known=refs[ds]["per_image"][name]
                        if abs(pa-known)>1e-5:
                            raise AssertionError(f"{key}: original model drift from reference PSNR")
                    if mismatches or abs(pa-pb)>1e-10:
                        raise AssertionError(f"{key}: output changed {mismatches} pixels, PSNR Δ={pb-pa}")
                    row=dict(dataset=ds,sigma=sigma,seed=seed,image=name,
                             mismatched_pixels=mismatches,PSNR_original=round(pa,9),
                             PSNR_reordered=round(pb,9),PSNR_delta=round(pb-pa,12))
                    with output.open("a",newline="",encoding="utf-8") as f:
                        writer=csv.DictWriter(f,fieldnames=COLS)
                        if f.tell()==0:writer.writeheader()
                        writer.writerow(row)
                    print(f"{ds} σ{sigma} seed{seed} {name}: bit-exact 0 diff; "
                          f"PSNR={pa:.5f} dB",flush=True)
    rows=list(csv.DictReader(output.open("r",newline="",encoding="utf-8")))
    count_by_set={name:len(load_set(name)) for name in sets}
    expected=sum((min(n,args.max_images) if args.max_images else n)
                 for n in count_by_set.values())*len(sigmas)*len(seeds)
    summary=dict(status="PASS_ALL_CHECKED" if all(int(r["mismatched_pixels"])==0 for r in rows) else "FAIL",
                 images_conditions_checked=len(rows),images_conditions_expected=expected,
                 experiment_complete=len(rows)==expected,
                 total_mismatched_pixels=sum(int(r["mismatched_pixels"]) for r in rows),
                 config=config,
                 warnings=[
                     "Exactness is only final 8-bit image output equality in two CPU/GPU computation graphs.",
                     "Each layer has a sampled independent INT32 oracle, not every internal accumulator.",
                     "Physical FPGA hardware, bitstream and DDR traffic were not tested.",
                     "The CNN is σ25-trained, even where σ15 and σ50 were evaluated."
                 ])
    (args.out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(f"RESULT: {summary['images_conditions_checked']}/{expected} image-condition cases; "
          f"mismatches={summary['total_mismatched_pixels']}; complete={summary['experiment_complete']}",
          flush=True)
    print("Summary:",(args.out/"summary.json").resolve())


if __name__=="__main__":
    main()
