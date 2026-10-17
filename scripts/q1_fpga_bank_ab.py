"""Prepare frozen W=4 bank-permutation model and (when explicitly authorized) run FPGA A/B.

Safe default: archive integrity/preflight only, absolutely NO board programming.
Board run is opt-in: --execute --board-verified SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED
and requires explicit compatible --build and --xsdb paths.

The old ZedBoard PS7 preset/bitstream is NOT assumed compatible with Smart ZYNQ SL.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "dn_d10_c32_us_fx_qat"
ARCHIVE = ROOT / "research" / "q1_codesign" / "artifacts" / "q1_bank_reordered_export_20261018.zip"
ORIGINAL = ROOT / "denoise" / "export" / MODEL
CANDIDATE = ROOT / "build" / "q1_reviewer_export" / MODEL
PERM = ROOT / "research" / "q1_codesign" / "bank_export_perm.json"
APPROVAL = "SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED"


def verify_archive():
    if not ARCHIVE.is_file():
        raise ValueError("GitHub ZIP missing: git pull origin main first")
    if not (ORIGINAL / "manifest.json").is_file():
        raise ValueError("GitHub original QAT model not found")
    expected = json.loads(PERM.read_text(encoding="utf-8"))
    manifest_orig = json.loads((ORIGINAL / "manifest.json").read_text(encoding="utf-8"))
    if expected["model"] != MODEL or manifest_orig["model"] != MODEL:
        raise ValueError("Model mismatch in original/permissions")
    with zipfile.ZipFile(ARCHIVE) as arc:
        names = arc.namelist()
        prefix = MODEL + "/"
        required = {prefix + f"conv{i}_config.bin" for i in range(1, 11)}
        required |= {prefix + n for n in ("manifest.json", "int_eval.json",
                                           "permutation_manifest.json", "SHA256SUMS.txt")}
        if not required.issubset(set(names)):
            raise ValueError(f"Archive missing: {sorted(required-set(names))}")
        if len(names) != len(set(names)):
            raise ValueError("Archive contains duplicate file names")
        if any(not n.startswith(prefix) and n != "README_FIRST.txt" for n in names):
            raise ValueError("Unexpected archive member; refuse extraction")
        sums = {}
        for line in arc.read(prefix + "SHA256SUMS.txt").decode("utf-8").splitlines():
            digest, filename = line.split("  ", 1)
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or "/" in filename or "\\" in filename:
                raise ValueError("Malformed SHA256SUMS entry")
            sums[filename] = digest
        for filename, expected_hash in sums.items():
            actual = hashlib.sha256(arc.read(prefix + filename)).hexdigest()
            if actual != expected_hash:
                raise ValueError(f"Archive integrity mismatch: {filename}")
        frozen_orders = json.loads(arc.read(prefix + "permutation_manifest.json"))["orders"]
        if frozen_orders != expected["orders"]:
            raise ValueError("ZIP and frozen permutation definition differ")
        manifest_new = json.loads(arc.read(prefix + "manifest.json"))
        if manifest_new["model"] != MODEL or len(manifest_new["layers"]) != 10:
            raise ValueError("Wrong candidate manifest")
        if CANDIDATE.exists():
            # Never overwrite existing candidate: mismatch indicates a stale or modified export.
            for item in required:
                filename = item[len(prefix):]
                on_disk = CANDIDATE / filename
                if not on_disk.is_file() or on_disk.read_bytes() != arc.read(item):
                    raise ValueError(f"Candidate directory exists but differs: {on_disk}. "
                                     "Move the stale copy aside; never overwrite source.")
            state = "already installed, byte-for-byte verified"
        else:
            CANDIDATE.mkdir(parents=True, exist_ok=False)
            for item in sorted(required):
                (CANDIDATE / item[len(prefix):]).write_bytes(arc.read(item))
            state = "installed from GitHub archive, hashes checked"
    if CANDIDATE.resolve() == ORIGINAL.resolve():
        raise ValueError("Original model must not be overwritten")
    print(f"PASS: frozen model {state}")
    print("Original: ", ORIGINAL)
    print("Permuted: ", CANDIDATE)
    print("ZIP SHA256:", hashlib.sha256(ARCHIVE.read_bytes()).hexdigest())


def run_one(variant, output, build, xsdb, fclk, set_name, image):
    if variant not in ("baseline", "permuted"):
        raise ValueError("Invalid variant")
    args = [
        sys.executable, str(ROOT / "scripts" / "run_denoise.py"),
        "--model", MODEL,
        "--xsdb", str(xsdb),
        "--build", str(build),
        "--w4", "--fclk", str(fclk),
        "--mode", "1",
        "--set", set_name,
        "--images", image,
        "--tile", "65536",
        "--out", str(output),
        "--board-dir", str(output) + "_io",
    ]
    if variant == "permuted":
        args += ["--export-dir", str(CANDIDATE)]
    print(f"\n=== Physical FPGA {variant}: {output} ===", flush=True)
    subprocess.run(args, cwd=str(ROOT), check=True)
    if not (output / "report.json").is_file():
        raise RuntimeError("Board driver returned but report.json is missing")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build", type=Path, help="explicit board-verified W4 build directory")
    p.add_argument("--xsdb", type=Path, help="explicit Vivado xsdb.exe / xsdb.bat path")
    p.add_argument("--execute", action="store_true", help="opt-in to physical board programming")
    p.add_argument("--board-verified", default="", help="explicit verified Smart ZYNQ SL PS/DDR/MIO approval")
    p.add_argument("--run-id", default="trial_01", help="unique run label; existing results are never overwritten")
    p.add_argument("--repeat", type=int, default=1, help="paired A/B runs, 1 to 5")
    p.add_argument("--image", default="05.png")
    p.add_argument("--set", choices=("Set12", "BSD68"), default="Set12")
    p.add_argument("--fclk", type=float, default=50.0)
    a = p.parse_args()
    verify_archive()
    if not a.execute:
        print("PREFLIGHT ONLY: did not access the FPGA, Vivado or JTAG.")
        print("Before running: validate Smart ZYNQ SL PS/DDR/MIO configuration with the board vendor.")
        print(f"Authorized run requires --execute --board-verified {APPROVAL}")
        return
    if a.board_verified != APPROVAL:
        p.error("No physical board run without explicit Smart ZYNQ SL PS/DDR/MIO approval.")
    if not a.build or not a.xsdb:
        p.error("--build and --xsdb must be explicit; no automatic ZedBoard bitstream selection")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", a.run_id):
        p.error("--run-id must be 1-48 letters/digits/dashes/underscores")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", a.image):
        p.error("--image must be a single image filename, e.g. 05.png")
    if a.fclk != 50:
        p.error("For this controlled A/B protocol, --fclk must be exactly 50MHz")
    if not 1 <= a.repeat <= 5:
        p.error("--repeat must be between 1 and 5")
    build = a.build.resolve()
    xsdb = a.xsdb.resolve()
    if "zed_v" in str(build).lower() or "zedboard" in str(build).lower():
        p.error("Legacy ZedBoard-named build refused for Smart ZYNQ SL. "
                "Use a separately verified Smart ZYNQ SL bitstream.")
    if not (build / "system_wrapper.bit").is_file():
        p.error("Missing system_wrapper.bit under explicit --build path")
    if not xsdb.is_file():
        p.error("Missing explicit --xsdb executable/batch")
    out_root = ROOT / "build" / "q1_bank_fpga_runs" / a.run_id
    if out_root.exists():
        p.error(f"Run directory exists; refusal to overwrite: {out_root}")
    # All output directories are new; protect prior board data.
    for n in range(a.repeat):
        iteration = out_root / f"pair_{n+1:02}"
        o = iteration / "baseline"
        v = iteration / "permuted"
        run_one("baseline", o, build, xsdb, a.fclk, a.set, a.image)
        run_one("permuted", v, build, xsdb, a.fclk, a.set, a.image)
        compare = [
            sys.executable, str(ROOT / "scripts" / "q1_board_ab_compare.py"),
            "--baseline", str(o / "report.json"),
            "--permuted", str(v / "report.json"),
            "--out", str(iteration / "comparison.json")
        ]
        subprocess.run(compare, cwd=str(ROOT), check=True)
    print("\nPASS: physical A/B completed; all output paths:")
    for n in range(a.repeat):
        print(out_root / f"pair_{n+1:02}" / "comparison.json")
    print("Physical core cycles are NOT the same as PS+DMA+PL end-to-end latency.")


if __name__ == "__main__":
    main()
