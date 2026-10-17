"""Fair optimization-budget experiment for paper rebuttal (GPU PC).

Existing 32ch ReLU INT8 QAT network. Fit ALL strategies only on exactly the same
Set12 calibration activations; evaluate on BSD68 without ever changing its labels
or using BSD68 to select a candidate.

Fairness: budgets count objective evaluations, including each restart initialization.
Greedy: B-1 swaps + 1 init; anneal: B-1 swaps + 1 init.
Multi-start: R starts, total B-R swap candidates, split deterministically.

Each method has an identical total number of cost-function evaluations. Noise
draws (sigma 15/25/50, seeds 0/1/2) are NOT independent clean images.
The physical FPGA is never programmed; reported gains are CORE PROXIES only.

Resumable; does not modify the previous 612-condition experiment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A, load_set, test_noise
from run_denoise import load_layers
from q1_reviewer_bank import create_runner, cycles
from q1_gpu_deadline_suite import balanced_random, optimize

MODEL="dn_d10_c32_us_fx_qat"
METHODS=("greedy","anneal","multistart")
FIELDS=("image","sigma","noise_seed","method","budget","optimizer_seed",
        "baseline_cycles","method_cycles","saved_pct")
FIXED_IDENTITY=("identity",)
FIXED_FROZEN=("frozen_01",)


def ints(text):
    out=[int(x.strip()) for x in text.split(",") if x.strip()]
    if not out or len(set(out))!=len(out): raise ValueError("Empty or repeated list")
    return out


def network_digest(model_dir):
    h=hashlib.sha256()
    h.update((model_dir/"manifest.json").read_bytes())
    for n in range(1,11):
        h.update((model_dir/f"conv{n}_config.bin").read_bytes())
    return h.hexdigest()


def key(method,budget,seed):
    return f"{method}_B{budget}_O{seed}"


def search(table,cout,k,method,budget,restarts,random_seed):
    if budget<=restarts:raise ValueError("Budget must exceed the number of restarts")
    t0=time.perf_counter()
    if method in ("greedy","anneal"):
        # Exactly B evaluations = one initial group + B-1 proposals.
        group,score=optimize(
            table,cout,k,random_seed,budget-1,anneal=(method=="anneal")
        )
        count=budget
    elif method=="multistart":
        # Exactly R initial evaluations + (B-R) proposals distributed across R runs.
        proposals=budget-restarts
        per=[proposals//restarts]*restarts
        for j in range(proposals%restarts): per[j]+=1
        group=None
        score=float("inf")
        count=0
        for start,steps in enumerate(per):
            initial=(np.arange(table.shape[1],dtype=np.int64)%4
                     if start==0 else balanced_random(table.shape[1],random_seed+5000+start))
            candidate,value=optimize(
                table,cout,k,random_seed+start*157,steps,start=initial)
            count+=steps+1
            if value<score:
                group,score=candidate,value
    else:raise ValueError("Unsupported method")
    assert count==budget
    return group,score,count,time.perf_counter()-t0


def load_fixed(report):
    data=json.loads(report.read_text(encoding="utf-8"))
    if data.get("model")!=MODEL:raise ValueError("Wrong frozen model")
    layers={}
    for entry in data["layers"]:
        layer=entry["layer"]
        group=np.asarray(entry["group_of_original_channel"],dtype=np.int64)
        if len(group)!=32 or sorted(group.tolist())!=sorted([0,1,2,3]*8):
            raise ValueError(f"Invalid frozen grouping: {layer}")
        layers[layer]=group
    if set(layers)!={f"conv{i}" for i in range(2,10)}:
        raise ValueError("Frozen permutation must have exactly Conv2..Conv9")
    return layers


def calibrate(args,layers,runner,frozen):
    import torch
    file=args.out/"search_groups.json"
    if file.exists():
        obj=json.loads(file.read_text(encoding="utf-8"))
        if obj["config"]!=args.config:
            raise ValueError("Saved candidate search has different config; use new --out")
        return {k:{layer:np.asarray(v,dtype=np.int64) for layer,v in d.items()}
                for k,d in obj["groups"].items()}
    target={"01.png","02.png","03.png"}
    calib={}
    for noise_seed in (0,1):
        for name,clean,noisy in test_noise(load_set("Set12"),25,seed=noise_seed):
            if name not in target: continue
            q=np.rint(noisy*QMAX_A).astype(np.uint8)
            with torch.no_grad(): counts,_=runner(q)
            for lname,arr in counts.items():
                rng=np.random.default_rng(101*noise_seed+int(lname[4:]))
                n=min(args.calib_windows,len(arr))
                ix=rng.choice(len(arr),size=n,replace=False)
                calib.setdefault(lname,[]).append(arr[ix])
            print(f"calibration source: {name}, AWGN seed={noise_seed}",flush=True)
    groups={"identity":{},"frozen_01":{}}
    logs=[]
    for l in layers:
        name=l["name"]
        if name not in frozen:continue
        data=np.concatenate(calib[name],axis=0)
        groups["identity"][name]=np.arange(data.shape[1],dtype=np.int64)%4
        groups["frozen_01"][name]=frozen[name]
        for budget in args.budgets:
            for optseed in args.optimizer_seeds:
                for method in METHODS:
                    label=key(method,budget,optseed)
                    group,val,evals,seconds=search(
                        data,l["COUT"],l["K"],method,budget,args.restarts,
                        optseed+100*int(name[4:]))
                    groups.setdefault(label,{})[name]=group
                    logs.append(dict(layer=name,method=method,budget=budget,
                                     optimizer_seed=optseed,cost_evaluations=evals,
                                     calibration_windows=len(data),
                                     chosen_cost=round(val,8),
                                     search_seconds=round(seconds,5)))
                    print(f"{name} {label}: proxy={val:.3f} "
                          f"evals={evals} search={seconds:.2f}s",flush=True)
    if len(groups)!=2+len(METHODS)*len(args.budgets)*len(args.optimizer_seeds):
        raise AssertionError("Missing optimizer candidate")
    with (args.out/"search_effort.csv").open("w",newline="",encoding="utf-8") as f:
        wr=csv.DictWriter(f,fieldnames=list(logs[0]))
        wr.writeheader();wr.writerows(logs)
    file.write_text(json.dumps(dict(
        config=args.config,
        groups={label:{lname:g.tolist() for lname,g in d.items()}
                for label,d in groups.items()},
    ),indent=2)+"\n",encoding="utf-8")
    return groups


def completed_images(path,expected_keys):
    if not path.is_file():return set()
    counter=defaultdict(set)
    with path.open("r",newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            im=(int(row["sigma"]),int(row["noise_seed"]),row["image"])
            label=row["method"]
            if label in counter[im]:raise AssertionError(f"Duplicate {im} {label}")
            counter[im].add(label)
    for image,labels in counter.items():
        if labels!=expected_keys:
            raise AssertionError(f"Interrupted partial CSV image group: {image}. "
                                 "Do not append; restore the incomplete last group first.")
    return set(counter)


def evaluate(args,layers,runner,groups):
    import torch
    outfile=args.out/"per_image.csv"
    done=completed_images(outfile,set(groups))
    data=load_set("BSD68")
    if len(data)!=68:raise AssertionError(f"Expected 68 BSD68 images, got {len(data)}")
    for sigma in (15,25,50):
        for noise_seed in (0,1,2):
            for index,(name,clean,noisy) in enumerate(test_noise(data,sigma,seed=noise_seed)):
                if args.max_images and index>=args.max_images:break
                if (sigma,noise_seed,name) in done:continue
                q=np.rint(noisy*QMAX_A).astype(np.uint8)
                with torch.no_grad(): counts,_=runner(q)
                scores={label:0 for label in groups}
                for l in layers:
                    lname=l["name"]
                    if lname not in counts:continue
                    for label,gper in groups.items():
                        scores[label]+=int(cycles(
                            counts[lname],l["COUT"],l["K"],gper[lname]).sum())
                baseline=scores["identity"]
                if baseline<=0:raise AssertionError("Missing eligible layer contributions")
                records=[]
                for label,cost in scores.items():
                    if label in ("identity","frozen_01"):
                        method=label;budget=0;opt_seed=0
                    else:
                        method,bstr,ostr=label.split("_B")[0],label.split("_B")[1].split("_O")[0],label.split("_O")[1]
                        budget=int(bstr);opt_seed=int(ostr)
                    records.append(dict(image=name,sigma=sigma,noise_seed=noise_seed,
                                        method=label,budget=budget,optimizer_seed=opt_seed,
                                        baseline_cycles=baseline,method_cycles=cost,
                                        saved_pct=round(100*(baseline-cost)/baseline,8)))
                with outfile.open("a",newline="",encoding="utf-8") as f:
                    wr=csv.DictWriter(f,fieldnames=FIELDS)
                    if f.tell()==0:wr.writeheader()
                    wr.writerows(records)
                print(f"evaluated {name} σ{sigma} noise_seed={noise_seed}: "
                      f"{len(records)} algorithm layouts",flush=True)


def summarize(args):
    path=args.out/"per_image.csv"
    if not path.is_file():return
    by_label=defaultdict(list)
    by_image=defaultdict(dict)
    with path.open("r",newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label=row["method"]
            by_label[label].append(row)
            by_image[(row["image"],int(row["sigma"]),int(row["noise_seed"]))][label]=row
    expected_images=(args.max_images or 68)*9
    expected_methods=2+len(args.budgets)*len(args.optimizer_seeds)*len(METHODS)
    is_complete=len(by_image)==expected_images and all(len(r)==expected_methods for r in by_image.values())
    rows=[]
    for label,recs in sorted(by_label.items()):
        ref=sum(float(r["baseline_cycles"]) for r in recs)
        cost=sum(float(r["method_cycles"]) for r in recs)
        rows.append(dict(method=label,conditions=len(recs),
                         pooled_saved_pct=round(100*(ref-cost)/ref,6)))
    with (args.out/"method_summary.csv").open("w",newline="",encoding="utf-8") as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0]))
        wr.writeheader();wr.writerows(rows)
    paired=[]
    for budget in args.budgets:
        for seed in args.optimizer_seeds:
            for opponent in ("greedy","anneal"):
                a=key("multistart",budget,seed);b=key(opponent,budget,seed)
                source=defaultdict(lambda:np.zeros(3,dtype=np.float64))
                for (image,sigma,noise_seed),recs in by_image.items():
                    if a not in recs or b not in recs:continue
                    rr=source[image]
                    rr[0]+=float(recs[a]["baseline_cycles"])
                    rr[1]+=float(recs[a]["method_cycles"])
                    rr[2]+=float(recs[b]["method_cycles"])
                if not source:continue
                arr=np.stack([source[k] for k in sorted(source)])
                total=arr.sum(axis=0)
                diff=100*(total[2]-total[1])/total[0]
                rng=np.random.default_rng(20261018+budget+seed+(10 if opponent=="anneal" else 0))
                choice=rng.integers(0,len(arr),size=(2000,len(arr)))
                tmp=arr[choice].sum(axis=1)
                vals=100*(tmp[:,2]-tmp[:,1])/tmp[:,0]
                lo,hi=np.quantile(vals,[.025,.975])
                paired.append(dict(budget=budget,optimizer_seed=seed,
                                   compared_to=opponent,
                                   multistart_advantage_pp=round(float(diff),6),
                                   bootstrap_low_pp=round(float(lo),6),
                                   bootstrap_high_pp=round(float(hi),6),
                                   image_clusters=len(arr)))
    if paired:
        with (args.out/"fair_paired.csv").open("w",newline="",encoding="utf-8") as f:
            wr=csv.DictWriter(f,fieldnames=list(paired[0]))
            wr.writeheader();wr.writerows(paired)
    report=dict(
        complete=is_complete,
        expected_image_conditions=expected_images,
        actual_image_conditions=len(by_image),
        budget_is_total_cost_evaluations_including_initialization=True,
        calibration="Set12 01/02/03, sigma25 seeds 0 and 1, identical for all methods",
        evaluation="BSD68 sigma 15/25/50 noise seeds 0/1/2",
        optimisation_budgets=args.budgets,
        optimisation_seeds=args.optimizer_seeds,
        method_summary=rows,
        paired_differences=paired,
        limitations=[
            "Image clusters are correlated across the 9 noise conditions.",
            "Optimizer seeds replicate selection randomness, not independent datasets.",
            "No GPU evaluation images or test labels were used in selecting permutations.",
            "Fixed Frozen has DIFFERENT calibration data, so is for context only.",
            "Objective-evaluation counts are equal, but host CPU time can differ.",
            "All savings are W4 sparse Conv2-9 analytical core coefficients, not FPGA timing.",
            "Search on Set12 does not eliminate historical CNN architecture tuning on BSD68."
        ])
    (args.out/"summary.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("FAIR BUDGET REPORT:",args.out/"summary.json",
          "COMPLETED",is_complete,flush=True)


def selftest():
    rng=np.random.default_rng(42)
    x=rng.integers(0,10,(60,32),dtype=np.uint8)
    for budget in (51,100,400):
        for method in METHODS:
            g,val,n,t=search(x,32,288,method,budget,5,123)
            assert n==budget,(method,n,budget)
            assert sorted(np.bincount(g,minlength=4).tolist())==[8]*4
            assert np.isfinite(val)
    a,_,_,_=search(x,32,288,"multistart",100,5,123)
    b,_,_,_=search(x,32,288,"multistart",100,5,123)
    assert np.array_equal(a,b),"Non-deterministic optimizer"
    print("PASS: exactly budgeted objective evaluations, balanced groups, repeatable optimizer")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budgets",default="400,800,2000",
                    help="objective evaluations INCLUDING starting-state cost")
    ap.add_argument("--optimizer-seeds",default="42,101,202,303,404")
    ap.add_argument("--restarts",type=int,default=5)
    ap.add_argument("--calib-windows",type=int,default=1024)
    ap.add_argument("--max-images",type=int,default=0,help="debug only")
    ap.add_argument("--device",choices=["auto","cuda","cpu"],default="auto")
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_gpu_fair_budget")
    ap.add_argument("--frozen",type=Path,default=ROOT/"build"/"q1_reviewer_bank"/"report.json")
    ap.add_argument("--selftest",action="store_true")
    args=ap.parse_args()
    if args.selftest:selftest();return
    args.budgets=ints(args.budgets)
    args.optimizer_seeds=ints(args.optimizer_seeds)
    if min(args.budgets)<=args.restarts or args.restarts<2:
        ap.error("Budget must exceed # of restarts >=2")
    if args.calib_windows<64 or args.max_images<0:
        ap.error("Bad calib-window count / max-images")
    src=ROOT/"denoise"/"export"/MODEL
    args.config=dict(model=MODEL,budgets=args.budgets,
                     optimizer_seeds=args.optimizer_seeds,restarts=args.restarts,
                     calib_windows=args.calib_windows,max_images=args.max_images,
                     model_digest=network_digest(src),
                     frozen_sha256=hashlib.sha256(args.frozen.read_bytes()).hexdigest())
    args.out.mkdir(parents=True,exist_ok=True)
    config_file=args.out/"run_config.json"
    if config_file.exists():
        if json.loads(config_file.read_text(encoding="utf-8"))!=args.config:
            ap.error("Different run configuration in existing output; use another --out")
    else:
        config_file.write_text(json.dumps(args.config,indent=2)+"\n",encoding="utf-8")
    import torch
    device=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if device=="cuda" and not torch.cuda.is_available():ap.error("CUDA unavailable")
    man,layers=load_layers(src)
    if len(layers)!=10 or not man.get("qat") or any(x["post"]!="none" for x in layers):
        raise ValueError("Unexpected QAT model geometry")
    runner=create_runner(layers,device)
    frozen=load_fixed(args.frozen)
    groups=calibrate(args,layers,runner,frozen)
    evaluate(args,layers,runner,groups)
    summarize(args)


if __name__=="__main__":
    main()
