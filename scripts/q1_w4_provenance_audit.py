"""Read-only W4 FPGA history and local bitstream provenance audit.

NO Vivado, JTAG, XSDB or board programming. A historical run proves real W4
operation but cannot prove bitstream byte identity without a historical .bit SHA.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "dn_d10_c32_us_fx_qat"
HISTORICAL = ROOT / "denoise" / "board_runs" / f"{MODEL}_05_w4.json"
MEASURED = ROOT / "denoise" / "w4_measured.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_historical_report(report_path: Path, measured_path: Path) -> dict:
    rep, meas = read_json(report_path), read_json(measured_path)
    if rep.get("emulated") is not False or rep.get("model") != MODEL:
        raise ValueError("Not a physical W4 test of the target model")
    if rep.get("set") != "Set12" or rep.get("sigma") != 25:
        raise ValueError("Historical dataset/noise differs")
    if rep.get("activations_per_cycle") != 4 or rep.get("mode_seq") != 1:
        raise ValueError("Historical report is not W4 sparse mode=1")
    images = rep.get("images", [])
    if len(images) != 1 or images[0].get("image") != "05.png":
        raise ValueError("Expected Set12 05.png test")
    img = images[0]
    layers = img.get("layers", [])
    if [r.get("name") for r in layers] != [f"conv{i}" for i in range(1, 11)]:
        raise ValueError("Expected all 10 ordered Conv layers")
    if rep.get("mismatches") != 0 or any(r.get("mismatches") != 0 for r in layers):
        raise ValueError("Physical run had nonzero oracle mismatches")
    if any(r.get("emulated") is not False for r in layers):
        raise ValueError("Emulated layer in physical report")
    ids = {c for r in layers for c in r.get("core_id", [])}
    if ids != {"0x4d410303"} or not all((int(c, 16) >> 9) & 1 for c in ids):
        raise ValueError(f"Incorrect physical W4 core ID {ids}")
    clocks = {round(float(c), 4) for r in layers for c in r.get("fclk_mhz", [])}
    if clocks != {50.0}:
        raise ValueError(f"Physical FCLK differs: {clocks}")
    cycles = sum(int(r["cycles"]) for r in layers)
    stall_in = sum(int(r["in_stall"]) for r in layers)
    stall_out = sum(int(r["out_stall"]) for r in layers)
    if int(img.get("cycles", -1)) != cycles:
        raise ValueError("Per-layer and image cycle totals differ")
    rows = [r for r in meas.get("networks", {}).values() if r.get("model") == MODEL]
    if len(rows) != 1:
        raise ValueError("Target model missing/duplicated in w4_measured")
    old = rows[0]
    for key, actual in (("measured_total", cycles), ("in_stall", stall_in), ("out_stall", stall_out)):
        if int(old.get(key, -1)) != actual:
            raise ValueError(f"Historic report disagrees with w4_measured: {key}")
    if old.get("core_id") != ["0x4d410303"]:
        raise ValueError("Historic core ID inconsistent")
    return {
        "status": "HISTORICAL_W4_PHYSICAL_RUN_VALIDATED",
        "model": MODEL, "dataset": "Set12", "image": "05.png",
        "sigma": 25, "mode": 1, "width": 4, "fclk_mhz": 50.0,
        "core_id": "0x4d410303", "conv_layers": 10, "total_cycles": cycles,
        "in_stall_cycles": stall_in, "out_stall_cycles": stall_out,
        "bitexact_mismatches": 0,
        "measured_w1_to_w4_speedup": old.get("speedup_over_w1"),
        "source_report": str(report_path), "source_measured": str(measured_path),
        "historical_bitstream_sha256": None,
        "historical_bitstream_hash_explanation":
            "The physical report does not record its .bit SHA256. Current binary identity is unproven.",
    }


def inspect_candidate_build(build: Path) -> dict:
    bit = build / "system_wrapper.bit"
    if not bit.is_file():
        raise FileNotFoundError(f"Bitstream missing: {bit}")
    result = {
        "candidate_path": str(build), "bit_path": str(bit),
        "bitstream_sha256": sha256_file(bit), "bitstream_size_bytes": bit.stat().st_size,
    }
    files = {
        "project": build / "system.xpr",
        "block_diagram": build / "system.srcs/sources_1/bd/system/system.bd",
        "ps_init": build / "ps7_init.tcl",
        "hardware_archive": build / "system_wrapper.xsa",
    }
    for key, path in files.items():
        result[key + "_path"] = str(path) if path.is_file() else None
        result[key + "_sha256"] = sha256_file(path) if path.is_file() else None
    if files["project"].is_file():
        xpr = files["project"].read_text(encoding="utf-8", errors="replace")
        for option in ("BoardPart", "DSABoardId", "Part"):
            m = re.search(r'<Option\s+Name="' + option + r'"\s+Val="([^"]+)"', xpr)
            result[option] = m.group(1) if m else None
    else:
        result["BoardPart"] = None
    if files["block_diagram"].is_file():
        bd = files["block_diagram"].read_text(encoding="utf-8", errors="replace")
        for key in ("PCW_FPGA0_PERIPHERAL_FREQMHZ", "PCW_UIPARAM_DDR_PARTNO",
                    "PCW_UIPARAM_DDR_FREQ_MHZ", "PCW_DDR_RAM_HIGHADDR"):
            m = re.search(r'"' + key + r'"\s*:\s*"?([^",}\s]+)', bd)
            result[key] = m.group(1) if m else None
    result["same_binary_as_historical_run_proven"] = False
    result["hardware_safety_status"] = "NOT_AUTOMATICALLY_APPROVED"
    result["notice"] = (
        "SHA identifies the local files only; the earlier physical report has no .bit hash. "
        "Confirm actual board, DDR/MIO and provenance independently before programming."
    )
    return result


def render_md(a: dict) -> str:
    h, c = a["historical"], a["candidate"]
    lines = [
        "# W4 FPGA history / local bitstream provenance (READ-ONLY)",
        "", "**No FPGA/JTAG/DDR access occurred.**", "",
        "## Historical actual board result",
        f"- Model: {h['model']}; Set12 05.png sigma25, W4 sparse",
        f"- {h['total_cycles']:,} core cycles at {h['fclk_mhz']:g} MHz; core ID {h['core_id']}",
        f"- 10 Conv layers, bitexact mismatches 0; DMA input stalls {h['in_stall_cycles']}",
        f"- Measured W1→W4 ratio: {h['measured_w1_to_w4_speedup']:.4f}x",
        "", "## Current local candidate (NOT automatically approved)",
    ]
    if c:
        lines += [
            f"- Build: {c['candidate_path']}",
            f"- Current bitstream SHA256: {c['bitstream_sha256']}",
            f"- Project BoardPart: {c.get('BoardPart') or 'unknown'}",
        ]
    else:
        lines.append("- No local candidate supplied; history-only audit")
    lines += [
        "", "## Provenance limitation",
        "**The historical real-board experiment is valid; the identity of the current "
        "bitstream is NOT proven by that experiment.** The earlier report lacks its .bit hash.",
        "This file does NOT approve programming or waive board PS/DDR/MIO verification.",
        "The CNN three-model preflight checks exports, not physical board compatibility.", "",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", type=Path, help="Existing local W4 build to fingerprint, offline")
    p.add_argument("--out", type=Path, default=ROOT / "build" / "q1_w4_provenance_audit")
    p.add_argument("--historical-report", type=Path, default=HISTORICAL)
    p.add_argument("--w4-measured", type=Path, default=MEASURED)
    a = p.parse_args()
    if a.out.exists():
        p.error(f"Output already exists; use a new audit ID: {a.out}")
    result = {
        "status": "OFFLINE_PROVENANCE_AUDIT_ONLY",
        "historical": verify_historical_report(a.historical_report, a.w4_measured),
        "candidate": inspect_candidate_build(a.build.resolve()) if a.build else None,
        "automatic_hardware_approval": False,
        "physical_fpga_programming_performed": False,
    }
    a.out.mkdir(parents=True)
    (a.out / "audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (a.out / "audit.md").write_text(render_md(result), encoding="utf-8")
    print("PASS: verified physical history:", result["historical"]["total_cycles"], "cycles, zero mismatches")
    if result["candidate"]:
        print("Local bitstream SHA256:", result["candidate"]["bitstream_sha256"])
        print("Vivado BoardPart:", result["candidate"].get("BoardPart"))
        print("Identical to historic .bit: NOT PROVEN (original report lacks hash)")
    print("NO JTAG/FPGA PROGRAMMING ATTEMPTED")
    print("Saved:", a.out / "audit.json")
    print("Saved:", a.out / "audit.md")


if __name__ == "__main__":
    main()
