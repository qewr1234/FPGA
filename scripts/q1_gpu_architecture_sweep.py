"""GPU-only transfer study across different EXISTING QAT denoising CNNs.

Networks:
  dn_d10_c64_us_es_qat   (64-channel plain ReLU)
  dn_d10_c32_us_mo_fx_qat (32-channel feature maps, maxout 64-output nodes)

Same quantized inference as existing model. Genuine 4-bank sparse W4 *core
coefficient* proxy, never FPGA hardware timing. Calibrate on Set12 01+02
at sigma25 seed0, evaluate BSD68 with multiple σ / seed configurations.

Maxout permutations act after the maxout node (32 feature maps), so this is
a virtual cost study ONLY: no modified maxout weights are exported.
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

from common import QMAX_A, load_set, pad_mult, psnr, shuffle2, test_noise, to_image, unshuffle2
from run_denoise import load_layers
from run_cifar import im2col,oracle,requant
from q1_reviewer_bank import cycles
from q1_gpu_deadline_suite import balanced_random, optimize

NETWORKS=("dn_d10_c64_us_es_qat","dn_d10_c32_us_mo_fx_qat")
METHODS=("identity","density_sort","greedy","anneal","multistart_greedy")


def runner_for(layers,device):
    import torch
    import torch.nn.functional as F
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    kernels=[]
    for l in layers:
        ci=l["K"]//(l["kh"]*l["kw"])
        W=(torch.from_numpy(l["wq"].astype(np.float32)
            .reshape(l["COUT"],l["kh"],l["kw"],ci))
            .permute(0,3,1,2).contiguous().to(device))
        b=torch.from_numpy(l["bq"].astype(np.float32)).to(device)
        kernels.append((W,b))

    def run(qin,oracle_check=False):
        hh,ww=qin.shape
        base=unshuffle2(pad_mult(qin,2)).astype(np.uint8)
        maps={"image":torch.as_tensor(base,dtype=torch.uint8,device=device)}
        counts={}
        result=None
        for i,L in enumerate(layers):
            q=torch.cat([maps[parent] for parent in L["inputs"]],dim=0)
            ci,h,w=q.shape
            kh,kw=int(L["kh"]),int(L["kw"])
            pad=(kh//2)*int(L["dilation"])
            name=L["name"]
            if name in {f"conv{j}" for j in range(2,10)}:
                if (kh,kw,int(L["stride"]),int(L["dilation"]))!=(3,3,1,1):
                    raise ValueError("Unrecognized convolution geometry")
                if ci%4:raise ValueError("Bank scheduling requires four-divisible input map")
                v=F.conv2d((q!=0).float()[None],
                           torch.ones((ci,1,3,3),device=device),groups=ci,padding=1)[0]
                counts[name]=v.permute(1,2,0).reshape(-1,ci).to(torch.uint8).cpu().numpy()
            W,b=kernels[i]
            acc=F.conv2d(q[None].float(),W,b,padding=pad,
                         stride=int(L["stride"]),dilation=int(L["dilation"])).clamp_min_(0)[0]
            _,oh,ow=acc.shape
            y=np.rint(acc.permute(1,2,0).reshape(-1,L["COUT"]).cpu().numpy()).astype(np.int32)
            if oracle_check:
                qnumpy=q.cpu().numpy()
                x=im2col(qnumpy[None],kh=kh,kw=kw,pad=pad,
                         dilation=int(L["dilation"]),stride=int(L["stride"]))
                expected=oracle(x[:32],L["wq"],L["bq"])
                if not np.array_equal(expected,y[:32]):
                    raise AssertionError(f"{name}: GPU int accumulation differs from CPU oracle")
            if i<len(layers)-1:
                post=requant(y,np.asarray(L["requant"])).reshape(oh,ow,L["COUT"]).transpose(2,0,1)
                if L["post"]=="maxout":
                    split=L["COUT"]//2
                    post=np.maximum(post[:split],post[split:])
                elif L["post"]!="none":
                    raise ValueError("Unsupported post-operation for architecture screen")
                maps[name]=torch.as_tensor(np.ascontiguousarray(post),dtype=torch.uint8,device=device)
            else:
                acc_map=y.reshape(oh,ow,L["COUT"]).transpose(2,0,1)
                result=shuffle2(to_image(acc_map,base,L["to_pixel"],False),hh,ww)
        return counts,result

    return run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",choices=NETWORKS,required=True)
    p.add_argument("--sigmas",default="15,25,50")
    p.add_argument("--seeds",default="0,1")
    p.add_argument("--device",choices=("auto","cuda","cpu"),default="auto")
    p.add_argument("--greedy-steps",type=int,default=400)
    p.add_argument("--anneal-steps",type=int,default=1000)
    p.add_argument("--restarts",type=int,default=4)
    p.add_argument("--calib-windows",type=int,default=1536)
    p.add_argument("--max-images",type=int,default=0,help="debug only; nonzero truncates BSD68")
    p.add_argument("--out",type=Path,default=ROOT/"build"/"q1_gpu_architectures")
    args=p.parse_args()
    if any(i<1 for i in [args.greedy_steps,args.anneal_steps,args.restarts,args.calib_windows]):
        p.error("optimization settings must be >=1")
    sigmas=[int(x) for x in args.sigmas.split(",") if x.strip()]
    seeds=[int(x) for x in args.seeds.split(",") if x.strip()]
    if not sigmas or not seeds or min(sigmas)<=0 or min(seeds)<0:p.error("bad sigma/seed")
    if len(set(sigmas))!=len(sigmas) or len(set(seeds))!=len(seeds):
        p.error("duplicates in sigma/seed lists")
    args.out=args.out/args.model
    args.out.mkdir(parents=True,exist_ok=True)
    src=ROOT/"denoise"/"export"/args.model
    manifest,layers=load_layers(src)
    if not manifest.get("graph") or not manifest.get("qat") or not manifest.get("unshuffle"):
        raise ValueError("Requires unshuffled graph-QAT model")
    import torch
    dev=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if dev=="cuda" and not torch.cuda.is_available():p.error("CUDA unavailable")
    run=runner_for(layers,dev)
    config=dict(model=args.model,sigmas=sigmas,seeds=seeds,
                greedy_steps=args.greedy_steps,anneal_steps=args.anneal_steps,
                restarts=args.restarts,calib_windows=args.calib_windows,
                max_images=args.max_images,source_manifest_sha256=hashlib.sha256(
                    (src/"manifest.json").read_bytes()).hexdigest())
    cfg_file=args.out/"config.json"
    if cfg_file.exists() and json.loads(cfg_file.read_text(encoding="utf-8"))!=config:
        p.error("Existing output has different settings; choose a different --out")
    cfg_file.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")

    trained_file=args.out/"fixed_methods.json"
    if trained_file.exists():
        sets=json.loads(trained_file.read_text(encoding="utf-8"))
        methods={m:{layer:np.asarray(g,dtype=np.int64) for layer,g in maps.items()}
                 for m,maps in sets.items()}
        print("Reuse previous calibrated methods without retuning.",flush=True)
    else:
        train=[]
        for name,clean,noisy in test_noise(load_set("Set12"),25,seed=0):
            if name not in ("01.png","02.png"): continue
            q=np.rint(noisy*QMAX_A).astype(np.uint8)
            with torch.no_grad():
                tables,out=run(q,oracle_check=True)
            expected=json.loads((src/"int_eval.json").read_text(encoding="utf-8"))["Set12"]["per_image"][name]
            pval=psnr(clean,out.astype(np.float32)/255)
            if abs(pval-expected)>1e-5:
                raise AssertionError(f"{args.model} {name}: GPU oracle output PSNR differs from original integer evaluation")
            train.append(tables)
            print(f"{args.model} calibration {name} PSNR={pval:.5f} verified",flush=True)
        methods={m:{} for m in METHODS}
        for i,L in enumerate(layers):
            name=L["name"]
            if name not in train[0]:continue
            rs=np.random.default_rng(44+i)
            data=np.concatenate([t[name][rs.choice(len(t[name]),min(args.calib_windows,len(t[name])),replace=False)]
                                 for t in train],axis=0)
            ci=data.shape[1]
            g0=np.arange(ci,dtype=np.int64)%4
            ids=np.argsort(-data.mean(axis=0),kind="stable")
            gden=np.empty(ci,dtype=np.int64);gden[ids]=np.arange(ci)%4
            greedy,gv=optimize(data,L["COUT"],L["K"],100+i,args.greedy_steps)
            anneal,av=optimize(data,L["COUT"],L["K"],200+i,args.anneal_steps,anneal=True)
            multi=greedy.copy()
            mv=gv
            for j in range(args.restarts):
                gp,val=optimize(data,L["COUT"],L["K"],300+i*100+j,
                                args.greedy_steps,
                                start=balanced_random(ci,900+i*100+j))
                if val<mv:
                    multi,mv=gp,val
            for k,g in (("identity",g0),("density_sort",gden),("greedy",greedy),
                        ("anneal",anneal),("multistart_greedy",multi)):
                methods[k][name]=g.copy()
            print(f"{name}: channels={ci} greedy={gv:.2f} anneal={av:.2f} multi={mv:.2f}",
                  flush=True)
        trained_file.write_text(json.dumps(
            {m:{layer:g.tolist() for layer,g in maps.items()} for m,maps in methods.items()},
            indent=2)+"\n",encoding="utf-8")

    data=load_set("BSD68")
    rows_file=args.out/"per_image.csv"
    keys=set()
    if rows_file.exists():
        with rows_file.open("r",newline="",encoding="utf-8") as f:
            keys={(int(x["sigma"]),int(x["seed"]),x["image"])
                  for x in csv.DictReader(f)}
    fields=["model","sigma","seed","image","psnr_db","baseline_cycles"]+[
        f"{m}_cycles" for m in METHODS if m!="identity"]
    for sigma in sigmas:
        for seed in seeds:
            for image_idx,(name,clean,noisy) in enumerate(test_noise(data,sigma,seed=seed)):
                if args.max_images and image_idx>=args.max_images:break
                if (sigma,seed,name) in keys:continue
                q=np.rint(noisy*QMAX_A).astype(np.uint8)
                with torch.no_grad():
                    tables,out=run(q,oracle_check=(image_idx==0 and sigma==25 and seed==0))
                quality=float(psnr(clean,out.astype(np.float32)/255))
                if sigma==25 and seed==0:
                    ref=json.loads((src/"int_eval.json").read_text(encoding="utf-8"))["BSD68"]["per_image"][name]
                    if abs(quality-ref)>1e-5:
                        raise AssertionError(f"{name}: exact sigma25/seed0 integer evaluation PSNR drift")
                cost={m:0 for m in METHODS}
                for L in layers:
                    if L["name"] not in tables:continue
                    dataL=tables[L["name"]]
                    for m,group in methods.items():
                        cost[m]+=int(cycles(dataL,L["COUT"],L["K"],group[L["name"]]).sum())
                rr=dict(model=args.model,sigma=sigma,seed=seed,image=name,
                        psnr_db=round(quality,7),baseline_cycles=cost["identity"])
                rr.update({f"{m}_cycles":cost[m] for m in METHODS if m!="identity"})
                with rows_file.open("a",newline="",encoding="utf-8") as f:
                    wr=csv.DictWriter(f,fieldnames=fields)
                    if f.tell()==0:wr.writeheader()
                    wr.writerow(rr)
                print(f"{args.model} sigma={sigma} seed={seed} {name} "
                      f"multi={100*(1-cost['multistart_greedy']/cost['identity']):+.2f}%",
                      flush=True)
    rows=list(csv.DictReader(rows_file.open("r",newline="",encoding="utf-8")))
    expected_count=(args.max_images or len(data))*len(seeds)*len(sigmas)
    aggregate={}
    for m in METHODS[1:]:
        base=sum(float(r["baseline_cycles"]) for r in rows)
        cand=sum(float(r[f"{m}_cycles"]) for r in rows)
        aggregate[m]=dict(estimated_cycle_reduction_pct=round(100*(base-cand)/base,6),
                          sample_conditions=len(rows),
                          improved=sum(float(r[f"{m}_cycles"])<float(r["baseline_cycles"]) for r in rows))
    summary=dict(model=args.model,data_set="BSD68",num_image_condition_rows=len(rows),
                 expected_image_condition_rows=expected_count,
                 complete=len(rows)==expected_count,
                 methods=aggregate,
                 warnings=["These are core-cycle coefficients only; not FPGA or end-to-end speedup.",
                           "σ25-trained QAT used unchanged at σ15 and σ50.",
                           "Maxout strategy is a virtual activation-map permutation, not exported/bitexact-proven modified maxout weights.",
                           "Calibration only Set12 images 01/02; test BSD68. Historical CNN may have been tuned on BSD68.",
                           "Distinct CNN architectures are not directly comparable at fixed PSNR; compare within each model only."])
    (args.out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print("SUMMARY:",(args.out/"summary.json").resolve(),flush=True)
    print(json.dumps(aggregate,indent=2),flush=True)


if __name__=="__main__":
    main()
