"""Screen lossless CNN channel permutations for the existing W=4 FPGA banked core.

Exploratory: estimates sparse COMPUTE CYCLES from real QAT activation maps.
Training images are only used to SELECT permutations; a disjoint image is used
to EVALUATE. Neither new RTL nor actual board speedup is claimed.

Run: python scripts/q1_reviewer_bank.py --calib 01.png --eval 05.png
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A, load_set, pad_mult, psnr, shuffle2, test_noise, to_image, unshuffle2
from run_cifar import im2col, oracle, requant
from run_denoise import load_layers

def encode_order(group):
    """new_channel_position -> original_channel_index; group is bank for each original channel."""
    banks=[list(np.flatnonzero(group==i)) for i in range(4)]
    if len(set(map(len,banks)))!=1:
        raise AssertionError("Unequal bank groups")
    return np.array([banks[i][j] for j in range(len(banks[0])) for i in range(4)],dtype=np.int64)

def cycles(counts, cout, k, group, w=4):
    """Exact per-window W=4 analytical core coefficient, omits per-layer fill/drain."""
    banks=np.stack([counts[:,group==i].sum(1,dtype=np.int32) for i in range(4)],axis=1)
    issue=((cout+15)//16)*np.maximum(1,banks.max(1))
    load=(k+w-1)//w+1
    return np.maximum(np.maximum(issue,load),cout).astype(np.int32)

def fit_group(counts, cout, k, seed, steps):
    """Swap original channels between fixed-capacity banks; objective is mean sparse core cycles."""
    nch=counts.shape[1]
    if nch%4: raise ValueError("4-bank grouping needs channel count multiple of 4")
    rng=np.random.default_rng(seed)
    group=np.arange(nch,dtype=np.int32)%4
    best=float(np.mean(cycles(counts,cout,k,group)))
    for _ in range(steps):
        p=int(rng.integers(0,nch))
        choices=np.flatnonzero(group!=group[p])
        q=int(choices[int(rng.integers(0,len(choices)))])
        group[p],group[q]=group[q],group[p]
        trial=float(np.mean(cycles(counts,cout,k,group)))
        if trial+1e-10<best:
            best=trial
        else:
            group[p],group[q]=group[q],group[p]
    return group,best

def selftest(layers):
    """The actual int export's two-layer conv2 -> conv3 remains bit exact after channel relabel."""
    rng=np.random.default_rng(23)
    a,b=layers[1],layers[2]
    assert b["inputs"]==[a["name"]] and a["post"]=="none"
    ci=a["K"]//9
    q=rng.integers(0,128,(ci,9,11),dtype=np.uint8)
    x=im2col(q[None])
    first=oracle(x,a["wq"],a["bq"])
    ah=requant(first,np.asarray(a["requant"])).reshape(9,11,a["COUT"]).transpose(2,0,1)
    original=oracle(im2col(ah[None]),b["wq"],b["bq"])
    order=rng.permutation(ah.shape[0])
    # Fold channel permutation in producer's output and the consumer's tap weights;
    # no run-time reorder stage is needed when original producer is re-exported.
    reordered_a=ah[order]
    rearranged_w=(b["wq"].reshape(b["COUT"],3,3,ah.shape[0])[:,:,:,order]
                   .reshape(b["COUT"],b["K"]))
    new=oracle(im2col(reordered_a[None]),rearranged_w,b["bq"])
    if not np.array_equal(original,new):
        raise AssertionError("Channel permutation changed INT32 convolution outputs")
    # The matching preceding producer channel permutation must also reorder
    # its weights, biases and independent per-channel quantization scales.
    first_new=oracle(x,a["wq"][order],a["bq"][order])
    ah_new=requant(first_new,np.asarray(a["requant"])[order])
    if not np.array_equal(ah_new,requant(first,np.asarray(a["requant"]))[:,order]):
        raise AssertionError("Producer's per-channel requant scaling was not permuted correctly")
    print("PASS: real conv2->conv3 INT8 export, 0 output mismatches after channel permutation",flush=True)

def create_runner(layers,device):
    import torch
    import torch.nn.functional as F
    torch.backends.cuda.matmul.allow_tf32=False
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.allow_tf32=False
    filters=[]
    for l in layers:
        cin=l["K"]//(l["kh"]*l["kw"])
        weights=(torch.from_numpy(l["wq"].astype(np.float32).reshape(l["COUT"],l["kh"],l["kw"],cin))
                 .permute(0,3,1,2).contiguous().to(device))
        bias=torch.from_numpy(l["bq"].astype(np.float32)).to(device)
        scales=(torch.as_tensor(l["requant"],dtype=torch.float64,device=device)
                if "requant" in l else None)
        filters.append((weights,bias,scales))
    def evaluate(qin):
        h,w=qin.shape
        base=unshuffle2(pad_mult(qin,2)).astype(np.uint8)
        maps={"image":torch.as_tensor(base,device=device,dtype=torch.uint8)}
        count_dict={}
        out=None
        for li,l in enumerate(layers):
            q=torch.cat([maps[k] for k in l["inputs"]],dim=0)
            cin,ih,iw=q.shape
            kw,kh=int(l["kw"]),int(l["kh"])
            pad=(kh//2)*int(l["dilation"])
            _,oh,ow=q.shape[0],(ih+2*pad-int(l["dilation"])*(kh-1)-1)//int(l["stride"])+1,(iw+2*pad-int(l["dilation"])*(kw-1)-1)//int(l["stride"])+1
            if cin%4==0 and kw==3 and kh==3 and int(l["stride"])==1 and int(l["dilation"])==1 and l["COUT"]==32 and l["K"]==288 and len(l["inputs"])==1:
                count=(F.conv2d((q!=0).float()[None],torch.ones((cin,1,3,3),device=device),
                                padding=1,groups=cin)[0]
                       .permute(1,2,0).reshape(-1,cin).to(torch.uint8).cpu().numpy())
                count_dict[l["name"]]=count
            weights,bias,scales=filters[li]
            acc=F.conv2d(q[None].float(),weights,bias,padding=pad,
                         stride=int(l["stride"]),dilation=int(l["dilation"])).clamp_min_(0)[0]
            acc_np=np.rint(acc.permute(1,2,0).reshape(-1,l["COUT"]).cpu().numpy()).astype(np.int32)
            # Compare a small exact integer oracle subset on every layer.
            q_np=q.cpu().numpy()
            window=im2col(q_np[None],kh=kh,kw=kw,pad=pad,
                          dilation=int(l["dilation"]),stride=int(l["stride"]))
            ref=oracle(window[:min(64,window.shape[0])],l["wq"],l["bq"])
            if not np.array_equal(ref,acc_np[:len(ref)]):
                raise AssertionError(f"{l['name']}: PyTorch conv differs from integer oracle")
            if li<len(layers)-1:
                quant=requant(acc_np,np.asarray(l["requant"]))
                r=quant.reshape(oh,ow,l["COUT"]).transpose(2,0,1)
                if l["post"]!="none":
                    raise ValueError("This exploratory script only supports ReLU chain")
                maps[l["name"]]=torch.as_tensor(r,device=device,dtype=torch.uint8)
            else:
                amap=acc_np.reshape(oh,ow,l["COUT"]).transpose(2,0,1)
                out=shuffle2(to_image(amap,base,l["to_pixel"],False),h,w)
        return count_dict,out
    return evaluate

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",default="dn_d10_c32_us_fx_qat")
    ap.add_argument("--set",default="Set12",choices=["Set12","BSD68"])
    ap.add_argument("--calib",default="01.png",help="comma-separated calibration image names")
    ap.add_argument("--eval",default="05.png",help="comma-separated disjoint evaluation image names")
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--steps",type=int,default=400,help="greedy bank swaps per layer")
    ap.add_argument("--sample",type=int,default=2048,help="random training windows per layer")
    ap.add_argument("--device",choices=["auto","cuda","cpu"],default="auto")
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_reviewer_bank")
    args=ap.parse_args()
    if args.steps<0 or args.sample<64:
        ap.error("steps>=0 and sample>=64 required")
    calib=set(x.strip() for x in args.calib.split(",") if x.strip())
    test=set(x.strip() for x in args.eval.split(",") if x.strip())
    if not calib or not test or calib & test:
        ap.error("--calib and --eval must be nonempty and disjoint")
    manifest=ROOT/"denoise"/"export"/args.model
    man,layers=load_layers(manifest)
    if not man.get("graph") or not man.get("unshuffle") and man.get("pad_to")!=2:
        ap.error("Only pixel-unshuffled QAT graph is supported")
    if any(l["post"]!="none" for l in layers):
        ap.error("Only plain ReLU QAT graph is supported, no maxout or pooling")
    selftest(layers)
    import torch
    device=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if device=="cuda" and not torch.cuda.is_available():
        ap.error("CUDA requested but not available")
    print(f"Device: {device}; model: {args.model}",flush=True)
    run=create_runner(layers,device)
    tests=test_noise(load_set(args.set),man["sigma"],seed=0)
    selected=[(name,clean,noisy) for name,clean,noisy in tests if name in (calib|test)]
    missing=(calib|test)-{a[0] for a in selected}
    if missing:ap.error("Missing images: "+str(sorted(missing)))
    count_cal,count_test={},{}
    qa={}
    for name,clean,noisy in selected:
        q=np.rint(noisy*QMAX_A).astype(np.uint8)
        counts,out=run(q)
        p=psnr(clean,out.astype(np.float32)/255.0)
        original=json.loads((manifest/"int_eval.json").read_text(encoding="utf-8"))
        expected=original[args.set]["per_image"][name]
        if abs(p-expected)>1e-5:
            raise AssertionError(f"{name}: full-image QAT PSNR mismatch, {p} vs {expected}")
        qa[name]=p
        target=count_cal if name in calib else count_test
        for key,val in counts.items():
            target.setdefault(key,[]).append(val)
        print(f"  {name}: PSNR={p:.6f} dB MATCH, subset-oracle checks passed",flush=True)
    rows=[]
    rng=np.random.default_rng(args.seed)
    for layer in layers:
        name=layer["name"]
        if name not in count_cal:continue
        train=np.concatenate(count_cal[name],axis=0)
        valid=np.concatenate(count_test[name],axis=0)
        subset=train[rng.choice(len(train),size=min(args.sample,len(train)),replace=False)]
        group,optimized=fit_group(subset,layer["COUT"],layer["K"],args.seed+len(rows),args.steps)
        identity=np.arange(len(group))%4
        basetrain=float(cycles(subset,layer["COUT"],layer["K"],identity).mean())
        ev_base=cycles(valid,layer["COUT"],layer["K"],identity)
        ev_prop=cycles(valid,layer["COUT"],layer["K"],group)
        row=dict(layer=name,identity_cal_mean=round(basetrain,6),
                 optimized_cal_mean=round(optimized,6),
                 eval_identity_cycles=int(ev_base.sum()),
                 eval_optimized_cycles=int(ev_prop.sum()),
                 eval_saved_cycles=int(ev_base.sum()-ev_prop.sum()),
                 eval_relative_pct=round(100*(ev_base.sum()-ev_prop.sum())/ev_base.sum(),5),
                 eval_windows=len(valid),
                 original_channel_order=encode_order(group).tolist(),
                 group_of_original_channel=group.tolist())
        rows.append(row)
        print(f"  {name:7s} CAL {basetrain:.3f} -> {optimized:.3f}  EVAL "
              f"{ev_base.mean():.3f} -> {ev_prop.mean():.3f} cycles/window, "
              f"delta {row['eval_relative_pct']:+.3f}%",flush=True)
    summary=dict(
        claim="EXPLORATORY virtual channel reorder; no exported model, RTL or hardware modified",
        model=args.model,data_set=args.set,calib_images=sorted(calib),
        evaluation_images=sorted(test),train_seed=args.seed,steps=args.steps,
        sample=args.sample,device=device,output_psnr=qa,bank_width=4,
        eval_total_saved_cycles=int(sum(r["eval_saved_cycles"] for r in rows)),
        caveats=[
            "Evaluation is based on 3x3 input activation nonzero bank counts.",
            "Only window compute coefficients are predicted. DMA, channel order exports, "
            "fill/drain, control and bitstream are NOT measured or modified.",
            "Full network output is verified versus existing integer evaluation PSNR; "
            "actual parameter-reordered full network NOT exported/verified yet.",
            "A two-layer actual-QAT integer oracle permutation test runs first.",
            "Set12 images are historically used in this project; a real paper needs "
            "Train400-only calibration, untouched independent test set and multiple noise levels.",
            "No speedup/novelty is claimed unless held-out FPGA measurements beat random "
            "permutation, count-only and existing sparse-balancing baselines."
        ],layers=rows)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"report.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",
                                        encoding="utf-8")
    print("Total estimated sparse core cycles saved over evaluated layers: "+
          str(summary["eval_total_saved_cycles"]))
    print("REPORT: "+str((args.out/"report.json").resolve()))
    print("NO FPGA SPEEDUP OR NOVELTY CLAIM IS WARRANTED FROM THIS REPORT.")

if __name__=="__main__":
    main()
