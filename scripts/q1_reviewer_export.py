"""Export a bank-reordered QAT integer CNN; assert bit-exact FULL image outputs.

Input is a q1_reviewer_bank.py report. All output files go under build/.
The user must separately check FPGA RTL/board operation; this is CPU-only.
"""
import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A, load_set, test_noise
from run_denoise import denoise, load_layers

def export_network(export_src,report,dest):
    man,models=load_layers(export_src)
    if report["model"]!=man["model"]:
        raise AssertionError("Report and model disagree")
    if not man.get("graph") or any(l["post"]!="none" for l in models):
        raise AssertionError("Only direct ReLU QAT graph supported")
    by_name={l["name"]:l for l in models}
    orders={}
    for entry in report["layers"]:
        to=by_name[entry["layer"]]
        if len(to["inputs"])!=1:
            raise AssertionError("Only one-parent channel reorders are supported")
        upstream=to["inputs"][0]
        if upstream=="image":
            raise AssertionError("Do not reorder image channels")
        order=np.asarray(entry["original_channel_order"],dtype=np.int64)
        co=int(by_name[upstream]["COUT"])
        if len(order)!=co or sorted(order.tolist())!=list(range(co)):
            raise AssertionError(f"Bad channel permutation: {upstream}")
        if upstream in orders and not np.array_equal(orders[upstream],order):
            raise AssertionError(f"Conflicting consumers for {upstream}")
        orders[upstream]=order
    updated=copy.deepcopy(man)
    original_nodes={l["name"]:l for l in models}
    for node in updated["layers"]:
        name=node["name"]
        old=original_nodes[name]
        cin=int(old["K"])//(int(old["kh"])*int(old["kw"]))
        source_indexes=[]
        offset=0
        for parent in old["inputs"]:
            if parent=="image":
                channels=int(man["img_ch"])
                in_order=np.arange(channels)
            else:
                channels=int(by_name[parent]["COUT"])
                in_order=orders.get(parent,np.arange(channels))
            source_indexes.extend((in_order+offset).tolist())
            offset+=channels
        if offset!=cin:
            raise AssertionError(f"Input map depth mismatch {name}: {offset} vs {cin}")
        pout=orders.get(name,np.arange(int(old["COUT"])))
        if name==models[-1]["name"] and not np.array_equal(pout,np.arange(len(pout))):
            raise AssertionError("Cannot permute fixed output image channels")
        # Quantizer's tap order is (ky,kx,input-channel), NOT PyTorch's C,ky,kx.
        w=(old["wq"].reshape(int(old["COUT"]),int(old["kh"])*int(old["kw"]),cin)
           [pout][:,:,source_indexes]).reshape(int(old["COUT"]),int(old["K"]))
        bias=old["bq"][pout]
        words=np.concatenate([w.astype("<i4").reshape(-1),bias.astype("<i4")])
        (dest/node["config"]).write_bytes(words.tobytes())
        for key in ("requant","w_scale"):
            if key in node:
                vals=np.asarray(node[key])
                if vals.ndim==1 and len(vals)==len(pout):
                    node[key]=vals[pout].tolist()
        if "a_scale_out" in node and isinstance(node["a_scale_out"],list):
            vals=np.asarray(node["a_scale_out"])
            if len(vals)==len(pout):node["a_scale_out"]=vals[pout].tolist()
    (dest/"manifest.json").write_text(json.dumps(updated,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    shutil.copy2(export_src/"int_eval.json",dest/"int_eval.json")
    (dest/"permutation_manifest.json").write_text(
        json.dumps({"derived_from":str(export_src),"orders":{k:v.tolist() for k,v in orders.items()},
                    "status":"CPU exported, NOT validated on FPGA"},indent=2)+"\n",encoding="utf-8")
    return orders

def verify(original,changed,tests,model):
    ma,la=load_layers(original)
    mb,lb=load_layers(changed)
    args=SimpleNamespace(emulate=True,out=changed)
    rows=[]
    for name,clean,noisy in tests:
        q=np.rint(noisy*QMAX_A).astype(np.uint8)
        old,_=denoise(q,ma,la,args,Path(name).stem)
        new,_=denoise(q,mb,lb,args,Path(name).stem)
        mismatches=int(np.count_nonzero(old!=new))
        rows.append({"image":name,"mismatches":mismatches})
        print(f"{name}: FULL-IMAGE original vs reordered mismatch={mismatches}",flush=True)
        if mismatches:raise AssertionError(f"FAIL: {name}: {mismatches} pixel mismatches")
    (changed/"bitexact_report.json").write_text(
        json.dumps({"model":model,"status":"PASS_CPU_FULL_IMAGE_ONLY",
                    "images":rows,"hardware_verified":False},indent=2)+"\n",encoding="utf-8")
    return rows

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",default="dn_d10_c32_us_fx_qat")
    ap.add_argument("--report",type=Path,default=ROOT/"build"/"q1_reviewer_bank"/"report.json")
    ap.add_argument("--images",default="01.png,05.png")
    ap.add_argument("--set",default="Set12",choices=("Set12","BSD68"))
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_reviewer_export")
    args=ap.parse_args()
    report=json.loads(args.report.read_text(encoding="utf-8"))
    src=ROOT/"denoise"/"export"/args.model
    dst=args.out/args.model
    dst.mkdir(parents=True,exist_ok=True)
    orders=export_network(src,report,dst)
    selected=set(x.strip() for x in args.images.split(",") if x.strip())
    if not selected:ap.error("No images")
    man=json.loads((src/"manifest.json").read_text(encoding="utf-8"))
    tests=[r for r in test_noise(load_set(args.set),man["sigma"],seed=0) if r[0] in selected]
    if {r[0] for r in tests}!=selected:
        ap.error("Missing images: "+str(selected-{r[0] for r in tests}))
    verify(src,dst,tests,args.model)
    print(f"PASS: {len(tests)} full-image INT8 outputs unchanged.")
    print(f"Reordered {len(orders)} activation maps; exported: {dst.resolve()}")
    print("CAUTION: NO physical FPGA/DDR/RTL test or timing validation has been performed.")

if __name__=="__main__":
    main()
