"""One controlled physical original-only W4 canary on a previously working FPGA.

Do NOT treat the ZC702-named project as compatible solely because its PL
device matches. Run ONLY on the actual board/DDR setup where W4 has already
been proved functional, with deliberate human acknowledgement and matching
SHA256 from the read-only provenance audit. This script NEVER auto-selects a bitstream.
The default is offline-only validation and does not touch FPGA/JTAG.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from q1_board_ab_compare import load, check_img
from q1_w4_provenance_audit import verify_historical_report, HISTORICAL, MEASURED

APPROVAL = "SAME_PHYSICAL_BOARD_PREVIOUSLY_RAN_W4"
MODEL = "dn_d10_c32_us_fx_qat"
EXPECTED_BASELINE = 13289042
EXPECTED_CORE = "0x4d410303"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_inputs(a):
    audit = json.loads(a.audit.read_text(encoding="utf-8"))
    historical = verify_historical_report(HISTORICAL, MEASURED)
    if audit.get("status") != "OFFLINE_PROVENANCE_AUDIT_ONLY":
        raise ValueError("Expected existing read-only provenance audit")
    if audit.get("historical", {}).get("total_cycles") != historical["total_cycles"]:
        raise ValueError("Audited historical physical run differs")
    candidate = audit.get("candidate") or {}
    if Path(candidate.get("candidate_path", "")).resolve() != a.build.resolve():
        raise ValueError("Audit build path differs from requested build")
    bit = a.build / "system_wrapper.bit"
    if not bit.is_file():
        raise FileNotFoundError("Current W4 .bit not found")
    actual_sha = digest(bit)
    if candidate.get("bitstream_sha256") != actual_sha:
        raise ValueError("Bitstream changed after read-only provenance audit")
    if a.expected_sha256.lower() != actual_sha:
        raise ValueError("Explicit SHA256 and actual W4 bitstream differ")
    if historical["total_cycles"] != EXPECTED_BASELINE or historical["core_id"] != EXPECTED_CORE:
        raise ValueError("Past validated reference does not match known experiment")
    if a.run_dir.exists():
        raise FileExistsError("Refusing to overwrite previous physical run")
    if a.execute and (not a.xsdb or not a.xsdb.is_file()):
        raise FileNotFoundError("Explicit XSDB executable missing")
    return historical, actual_sha, candidate


def verify_live_report(report_path: Path, historical: dict, sha: str, build: Path) -> dict:
    o = load(report_path)
    img = check_img(o, report_path)
    if (o.get("model"), o.get("set"), o.get("sigma"), img.get("image")) != (
        MODEL, "Set12", 25, "05.png"
    ):
        raise ValueError("Current image/model/noise differs from historical W4")
    layers = img["layers"]
    if [r["name"] for r in layers] != [f"conv{i}" for i in range(1, 11)]:
        raise ValueError("Unexpected layer identities")
    for r in layers:
        if r.get("core_id") != [EXPECTED_CORE] or r.get("fclk_mhz") != [50]:
            raise ValueError(f"Unexpected W4 core ID or measured FCLK: {r['name']}")
    actual = sum(int(r["cycles"]) for r in layers)
    delta = 100 * (actual - historical["total_cycles"]) / historical["total_cycles"]
    ok = abs(delta) <= 2.0  # A canary sanity bound, not a performance acceptance threshold
    return {
        "status": ("PHYSICAL_ORIGINAL_W4_CANARY_PASS" if ok else
                   "PHYSICAL_ORIGINAL_W4_CANARY_DEVIATION_REVIEW_REQUIRED"),
        "bitstream_sha256": sha,
        "build_path": str(build.resolve()),
        "source_report": str(report_path.resolve()),
        "core_id": EXPECTED_CORE,
        "fclk_mhz": 50.0, "image": "05.png", "sigma": 25,
        "mode": 1, "model": MODEL,
        "historical_baseline_cycles": historical["total_cycles"],
        "canary_cycles": actual, "delta_pct": delta,
        "bitexact_mismatches": 0,
        "in_stall_cycles": sum(int(r["in_stall"]) for r in layers),
        "out_stall_cycles": sum(int(r["out_stall"]) for r in layers),
        "physical_board_test_performed": True,
        "meaning": (
            "A matching candidate .bit was actually programmed and passed original-model "
            "layer-by-layer output checks on this board. This is not manufacturer DDR/MIO "
            "certification or a permutation A/B/C speed result."
        ),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", type=Path, required=True)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--expected-sha256", required=True)
    ap.add_argument("--xsdb", type=Path)
    ap.add_argument("--run-id", default="canary_01")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--board-acknowledged", default="")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", a.run_id):
        ap.error("Unsafe run id")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", a.expected_sha256):
        ap.error("Expected .bit SHA256 must be 64 hex characters")
    a.audit, a.build = a.audit.resolve(), a.build.resolve()
    a.run_dir = ROOT / "build" / "q1_existing_w4_canary" / a.run_id
    historical, sha, candidate = check_inputs(a)
    print(f"PASS offline: {historical['total_cycles']:,} historic W4 cycles; SHA {sha}")
    print("Vivado board preset:", candidate.get("BoardPart"))
    print("This is the existing legacy W4 design, not a proven Smart ZYNQ SL DDR preset.")
    if not a.execute:
        print("DRY RUN ONLY: NO JTAG/FPGA/DDR accessed. To execute requires human approval.")
        return
    if a.board_acknowledged != APPROVAL:
        ap.error("Must explicitly confirm same physical board previously ran W4")
    a.run_dir.mkdir(parents=True)
    dest = a.run_dir / "original"
    cmd = [sys.executable, str(ROOT / "scripts" / "run_denoise.py"),
           "--model", MODEL,
           "--xsdb", str(a.xsdb), "--build", str(a.build),
           "--w4", "--mode", "1", "--fclk", "50", "--set", "Set12",
           "--images", "05.png", "--tile", "65536", "--out", str(dest),
           "--board-dir", str(a.run_dir / "original_io")]
    print("Programming current bitstream to the SAME user-confirmed physical board.", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    result = verify_live_report(dest / "report.json", historical, sha, a.build)
    (a.run_dir / "canary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("CANARY STATUS:", result["status"])
    print("Measured physical core cycles:", result["canary_cycles"])
    print("Save:", a.run_dir / "canary.json")
    if result["status"] != "PHYSICAL_ORIGINAL_W4_CANARY_PASS":
        raise SystemExit("2%+ original baseline divergence. Investigate before any A/B/C.")


if __name__ == "__main__":
    main()
