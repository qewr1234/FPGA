#!/usr/bin/env python3
"""Reconstruct frozen lossless QAT bank-permutation model from git-tracked original.

No PyTorch/NumPy/network needed. The original network remains untouched.
Creates research/q1_codesign/artifacts/q1_bank_reordered_export_20261018.zip.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "dn_d10_c32_us_fx_qat"
SRC = ROOT / "denoise" / "export" / MODEL
PERMS = ROOT / "research" / "q1_codesign" / "bank_export_perm.json"
DEST = ROOT / "research" / "q1_codesign" / "artifacts" / "q1_bank_reordered_export_20261018.zip"


def main():
    frozen = json.loads(PERMS.read_text(encoding="utf-8"))
    if frozen["model"] != MODEL:
        raise ValueError("Wrong permutation model")
    orders = frozen["orders"]
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    if manifest["model"] != MODEL or not manifest.get("graph"):
        raise ValueError("Wrong original manifest")
    layers = manifest["layers"]
    by_name = {l["name"]: l for l in layers}
    if set(orders) != {f"conv{i}" for i in range(1, 9)}:
        raise ValueError("Expected exactly the eight frozen output permutations")
    for name, perm in orders.items():
        co = int(by_name[name]["COUT"])
        if len(perm) != co or sorted(perm) != list(range(co)):
            raise ValueError(f"Invalid output permutation of {name}")

    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / MODEL
        out.mkdir()
        for layer in layers:
            name = layer["name"]
            co, k = int(layer["COUT"]), int(layer["K"])
            kh, kw = int(layer["kh"]), int(layer["kw"])
            cin = k // (kh * kw)
            inp_order = []
            offset = 0
            for parent in layer["inputs"]:
                pch = int(manifest["img_ch"]) if parent == "image" else int(by_name[parent]["COUT"])
                porder = orders.get(parent, list(range(pch)))
                inp_order.extend(offset + index for index in porder)
                offset += pch
            if len(inp_order) != cin:
                raise ValueError(f"{name}: input depth mismatch")

            out_order = orders.get(name, list(range(co)))
            blob = (SRC / layer["config"]).read_bytes()
            expected_len = (co * k + co) * 4
            if len(blob) != expected_len:
                raise ValueError(f"{name}: config bytes {len(blob)} != {expected_len}")
            words = struct.unpack(f"<{co * k + co}i", blob)
            orig_w, orig_b = words[:co*k], words[co*k:]
            if any(not (-128 <= v <= 127) for v in orig_w):
                raise ValueError(f"{name}: original weight outside INT8 range")
            new_w = [
                orig_w[oc*k + p*cin + ic]
                for oc in out_order
                for p in range(kh*kw)
                for ic in inp_order
            ]
            new_b = [orig_b[oc] for oc in out_order]
            (out / layer["config"]).write_bytes(
                struct.pack(f"<{len(new_w) + len(new_b)}i", *(new_w + new_b))
            )
            for key in ("requant", "w_scale", "a_scale_out"):
                vals = layer.get(key)
                if isinstance(vals, list) and len(vals) == co:
                    layer[key] = [vals[i] for i in out_order]

        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        shutil.copy2(SRC / "int_eval.json", out / "int_eval.json")
        (out / "permutation_manifest.json").write_text(
            json.dumps(
                {
                    "derived_from": f"denoise/export/{MODEL}",
                    "orders": orders,
                    "status": "CPU bitexact 68 BSD68 images; FPGA not measured",
                },
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        readme = (
            "Lossless 8-stage activation-bank channel permutation for the exported INT8 QAT CNN.\n"
            "Model: dn_d10_c32_us_fx_qat. Original model is unchanged.\n"
            "Place the dn_d10_c32_us_fx_qat folder at:\n"
            "  C:\\fpga\\FPGA\\build\\q1_reviewer_export\\dn_d10_c32_us_fx_qat\\\n"
            "CPU equivalence: BSD68 68/68 output images identical; 0 mismatching pixels.\n"
            "W4 sparse core cycle savings are MODEL PREDICTIONS, not FPGA speedups.\n"
            "Smart ZYNQ SL PS/DDR/MIO require hardware-specific validation before programming.\n"
        )
        (Path(scratch) / "README_FIRST.txt").write_text(readme, encoding="utf-8")
        sums = []
        for path in sorted(out.iterdir()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sums.append(f"{digest}  {path.name}")
        (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

        DEST.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(DEST, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(Path(scratch) / "README_FIRST.txt", "README_FIRST.txt")
            for path in sorted(out.iterdir()):
                z.write(path, f"{MODEL}/{path.name}")
    print(f"Wrote {DEST} ({DEST.stat().st_size:,} bytes)")
    print("ZIP SHA256:", hashlib.sha256(DEST.read_bytes()).hexdigest())
    print("No FPGA timing or physical board claims are made.")


if __name__ == "__main__":
    main()
