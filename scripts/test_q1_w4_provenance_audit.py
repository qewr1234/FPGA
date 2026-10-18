"""Tests for purely offline historical W4 provenance. No FPGA required."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("q1_w4_provenance_audit", Path(__file__).with_name("q1_w4_provenance_audit.py"))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class Tests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        layers = [
            {"name": f"conv{i}", "emulated": False, "cycles": 10, "mismatches": 0,
             "core_id": ["0x4d410303"], "fclk_mhz": [50], "in_stall": 12 if i == 5 else 0,
             "out_stall": 0} for i in range(1, 11)
        ]
        self.rep = {"emulated": False, "model": a.MODEL, "set": "Set12",
                    "sigma": 25, "mode_seq": 1, "activations_per_cycle": 4, "mismatches": 0,
                    "images": [{"image": "05.png", "layers": layers, "cycles": 100}]}
        self.meas = {"networks": {"target": {"model": a.MODEL, "measured_total": 100,
                     "in_stall": 12, "out_stall": 0, "core_id": ["0x4d410303"],
                     "speedup_over_w1": 3.3}}}
        self.rep_path = self.root / "physical.json"
        self.meas_path = self.root / "measured.json"
        self.save()

    def save(self):
        self.rep_path.write_text(json.dumps(self.rep))
        self.meas_path.write_text(json.dumps(self.meas))

    def check(self):
        return a.verify_historical_report(self.rep_path, self.meas_path)

    def test_valid_physical_w4(self):
        found = self.check()
        self.assertEqual(found["total_cycles"], 100)
        self.assertEqual(found["in_stall_cycles"], 12)
        self.assertIsNone(found["historical_bitstream_sha256"])

    def test_rejects_emulated_and_wrong_mode(self):
        for field, value in [("emulated", True), ("mode_seq", 0), ("activations_per_cycle", 1)]:
            old = self.rep[field]
            self.rep[field] = value
            self.save()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check()
            self.rep[field] = old
            self.save()

    def test_rejects_mismatch_or_bad_total(self):
        self.rep["images"][0]["layers"][0]["mismatches"] = 1
        self.save()
        with self.assertRaises(ValueError):
            self.check()
        self.rep["images"][0]["layers"][0]["mismatches"] = 0
        self.rep["images"][0]["cycles"] = 101
        self.save()
        with self.assertRaises(ValueError):
            self.check()

    def test_real_vivado_bd_nested_ps_settings(self):
        build = self.root / "nested_vivado"
        build.mkdir()
        (build / "system_wrapper.bit").write_bytes(b"test-only-bitstream")
        bdpath = build / "system.srcs" / "sources_1" / "bd" / "system" / "system.bd"
        bdpath.parent.mkdir(parents=True)
        bdpath.write_text(json.dumps({
            "design": {"components": {"processing_system7_0": {"parameters": {
                "PCW_FPGA0_PERIPHERAL_FREQMHZ": {"value": "100"},
                "PCW_UIPARAM_DDR_PARTNO": {"value": "MT41J256M8 HX-15E"},
                "PCW_UIPARAM_DDR_FREQ_MHZ": {"value": "533.333333"},
                "PCW_DDR_RAM_HIGHADDR": {"value": "0x3FFFFFFF"}
            }}}}
        }), encoding="utf-8")
        row = a.inspect_candidate_build(build)
        self.assertEqual(row["PCW_FPGA0_PERIPHERAL_FREQMHZ"], "100")
        self.assertEqual(row["PCW_UIPARAM_DDR_PARTNO"], "MT41J256M8 HX-15E")
        self.assertEqual(row["PCW_UIPARAM_DDR_FREQ_MHZ"], "533.333333")
        self.assertEqual(row["PCW_DDR_RAM_HIGHADDR"], "0x3FFFFFFF")

    def test_candidate_hash_is_not_hardware_approval(self):
        build = self.root / "legacy_build"
        build.mkdir()
        (build / "system_wrapper.bit").write_bytes(b"not-a-real-bitstream")
        (build / "system.xpr").write_text('<Option Name="BoardPart" Val="xilinx.com:zc702:part0:1.4"/>')
        meta = a.inspect_candidate_build(build)
        self.assertEqual(meta["BoardPart"], "xilinx.com:zc702:part0:1.4")
        self.assertEqual(len(meta["bitstream_sha256"]), 64)
        self.assertFalse(meta["same_binary_as_historical_run_proven"])
        self.assertEqual(meta["hardware_safety_status"], "NOT_AUTOMATICALLY_APPROVED")


if __name__ == "__main__":
    unittest.main()
