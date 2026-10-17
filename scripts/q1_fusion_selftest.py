"""CPU oracle equivalence checks for a proposed two-layer tiled CNN flow.

Checks all INT32 B outputs, not merely PSNR. No FPGA and no Vivado needed.
"""
from pathlib import Path
import json
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from q1_fusion_cost import evaluate_pair
from run_cifar import im2col, oracle, requant


def baseline(q, w1, b1, scale, w2, b2):
    c,h,w=q.shape
    mid=w1.shape[0]
    a=oracle(im2col(q[None],pad=1),w1,b1)
    a=requant(a,scale).reshape(h,w,mid).transpose(2,0,1)
    cout=w2.shape[0]
    z=oracle(im2col(a[None],pad=1),w2,b2)
    return z.reshape(h,w,cout)


def tiled(q,w1,b1,scale,w2,b2,side):
    cin,h,w=q.shape
    mid,cout=w1.shape[0],w2.shape[0]
    padded=np.pad(q,((0,0),(1,1),(1,1)),mode="constant")
    out=np.empty((h,w,cout),dtype=np.int32)
    for y0 in range(0,h,side):
        y1=min(y0+side,h)
        for x0 in range(0,w,side):
            x1=min(x0+side,w)
            ya,yb=max(0,y0-1),min(h,y1+1)
            xa,xb=max(0,x0-1),min(w,x1+1)
            # q has one *global* zero-padding border, not one per tile.
            # First-layer result is computed only within the real map.
            qpatch=padded[:,ya:yb+2,xa:xb+2]
            aa=oracle(im2col(qpatch[None],pad=0),w1,b1)
            aa=requant(aa,scale).reshape(yb-ya,xb-xa,mid).transpose(2,0,1)
            # B sees zero padding outside the global first-layer feature map.
            local=np.zeros((mid,y1-y0+2,x1-x0+2),dtype=np.uint8)
            dy=ya-(y0-1);dx=xa-(x0-1)
            local[:,dy:dy+yb-ya,dx:dx+xb-xa]=aa
            bb=oracle(im2col(local[None],pad=0),w2,b2)
            out[y0:y1,x0:x1]=bb.reshape(y1-y0,x1-x0,cout)
    return out


def run_check(q,w1,b1,scale,w2,b2,what):
    expected=baseline(q,w1,b1,scale,w2,b2)
    for side in (4,7,11,16):
        actual=tiled(q,w1,b1,scale,w2,b2,side)
        if not np.array_equal(expected,actual):
            y,x,c=np.argwhere(expected!=actual)[0]
            raise AssertionError(
                f"{what}: tile {side}, mismatch at y={y} x={x} c={c}: "
                f"{expected[y,x,c]} vs {actual[y,x,c]}")
    print(f"PASS: {what}; 4 tile sizes; full INT32 bit-exact")


def load_export_layer(folder,name):
    man=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    l=next(x for x in man["layers"] if x["name"]==name)
    blob=np.frombuffer((folder/l["config"]).read_bytes(),dtype="<i4")
    c,k=int(l["COUT"]),int(l["K"])
    if blob.size!=c*k+c:
        raise ValueError(f"{name}: config words {blob.size} != {c*k+c}")
    w=blob[:c*k].reshape(c,k).astype(np.int8)
    b=blob[c*k:].astype(np.int32)
    return l,w,b


def main():
    rng=np.random.default_rng(123)
    h,w=13,17
    q=rng.integers(0,128,(2,h,w),dtype=np.uint8)
    a=rng.integers(-3,4,(3,18),dtype=np.int8)
    b=rng.integers(-3,4,(4,27),dtype=np.int8)
    ab=rng.integers(-100,100,(3,),dtype=np.int32)
    bb=rng.integers(-100,100,(4,),dtype=np.int32)
    run_check(q,a,ab,np.array([0.12,0.31,0.24]),b,bb,"synthetic edge and channel cases")

    folder=ROOT/"denoise"/"export"/"dn_d10_c32_us_fx_qat"
    l1,wa,ba=load_export_layer(folder,"conv2")
    l2,wb,bc=load_export_layer(folder,"conv3")
    if l2["inputs"]!=["conv2"] or l1["post"]!="none":
        raise AssertionError("Export no longer matches assumed conv2->conv3 graph")
    qr=rng.integers(0,128,(wa.shape[1]//9,11,15),dtype=np.uint8)
    run_check(qr,wa,ba,np.asarray(l1["requant"]),wb,bc,
              "REAL QAT INT8 conv2+conv3 weights and channel scales")
    r=evaluate_pair(l1,l2,128,128,32,71.,16,140,1.25,1)
    assert r["proposed_macs"] >= r["baseline_macs"]
    assert r["baseline_external_bytes"] > r["proposed_external_bytes"]
    assert r["extra_bram36_equiv"]>0
    print("PASS: analytical accounting invariants")
    print("NOT TESTED: synth, hardware, PS7, DMA, actual latency, BRAM, power.")


if __name__=="__main__":
    main()
