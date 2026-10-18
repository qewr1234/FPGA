"""Safe, read-only preflight for the Vivado 2026.1 FPGA denoising co-design project.

Produces build/q1_preflight/report.json. Does not synthesize or program the board.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_VIVADO = "2026.1"


def run(argv, timeout=25):
    try:
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                              errors="replace", timeout=timeout, check=False)
        return {"exit_code": done.returncode,
                "output": (done.stdout + "\n" + done.stderr).strip()[-5000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "output": str(exc)}


def find_xsdb():
    roots = [os.environ.get("XILINX_VIVADO", ""),
             r"C:\Vivado\2026.1\Vivado", r"C:\Xilinx\2026.1\Vivado",
             r"D:\Vivado\2026.1\Vivado", r"D:\Xilinx\2026.1\Vivado"]
    paths = [shutil.which("xsdb.bat"), shutil.which("xsdb")]
    paths += [str(Path(root) / "bin" / "xsdb.bat") for root in roots if root]
    return next((p for p in paths if p and Path(p).is_file()), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path,
                    default=ROOT / "build" / "q1_preflight" / "report.json")
    args = ap.parse_args()

    vivado = run(["vivado", "-version"]) if shutil.which("vivado") else {
        "exit_code": None, "output": "vivado is not on PATH"}
    matched = re.search(r"Vivado\s+v?(\d{4}\.\d+)", vivado["output"], re.I)
    version = matched.group(1) if matched else None
    xsdb = find_xsdb()
    model = ROOT / "denoise" / "dn_d10_c32_us_mo_fx.pt"
    exports = ROOT / "denoise" / "export"
    exported = sorted(p.parent.name for p in exports.glob("*/manifest.json"))
    builds = sorted((p for p in (ROOT / "build").glob("zed_v4_p16_t4_w4_*")
                     if (p / "system_wrapper.bit").is_file()),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    git = run(["git", "rev-parse", "HEAD"], timeout=10)
    checks = {
        "vivado_2026_1": version == REQUIRED_VIVADO and vivado["exit_code"] == 0,
        "xsdb_present": xsdb is not None,
        "model_present": model.is_file(),
        "set12_present": bool(list((ROOT / "denoise" / "data" / "Set12").glob("*.png"))),
        "integer_exports_present": bool(exported),
        "existing_w4_bitstream_present": bool(builds),
        "python_numpy_present": importlib.util.find_spec("numpy") is not None,
        "python_pillow_present": importlib.util.find_spec("PIL") is not None,
        "python_torch_present": importlib.util.find_spec("torch") is not None,
    }
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Read-only FPGA co-design preflight; no synthesis or programming",
        "computer": {"os": platform.platform(), "python": sys.version.split()[0]},
        "github_revision": git["output"] if git["exit_code"] == 0 else None,
        "vivado": {"detected_version": version, "required_version": REQUIRED_VIVADO,
                   "executable": shutil.which("vivado"), "result": vivado},
        "xsdb_executable": xsdb,
        "model": {"path": str(model.relative_to(ROOT)), "exists": model.is_file(),
                  "size_bytes": model.stat().st_size if model.is_file() else None},
        "denoise_export_models": exported[:100],
        "latest_local_w4_build": str(builds[0].relative_to(ROOT)) if builds else None,
        "checks": checks,
        "hardware_hold": "Verify Smart ZYNQ SL DDR/PS7 MIO/clock/reset preset against the actual "
                         "board schematic before programming. build_zedboard.tcl defaults to "
                         "ZedBoard PS preset; an identical XC7Z020 part is not sufficient.",
        "next_step": "Verify PS7 board setup, then reproduce W=4 bit-exact board baseline and "
                     "measure host im2col, DMA transfer, PL compute and requantization separately."
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print("\n=== Q1 FPGA RESEARCH PREFLIGHT ===")
    print(f"Vivado       : {version or 'NOT FOUND'} (required {REQUIRED_VIVADO})")
    print(f"Vivado tool  : {shutil.which('vivado') or 'NOT FOUND'}")
    print(f"XSDB         : {xsdb or 'NOT FOUND'}")
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'CHECK':5} {name}")
    print("\nBOARD SAFETY HOLD: Smart ZYNQ SL PS7/DDR/MIO configuration NOT verified.")
    print("No bitstream was generated or loaded to the FPGA.")
    print(f"Report       : {args.output.resolve()}")
    if not checks["vivado_2026_1"]:
        print("ACTION: Correct the Vivado installation path/version first.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
