"""Offline tests for exact-bitstream original-only W4 canary and triplet gate."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from q1_existing_w4_canary import verify_live_report
from q1_fpga_triplet import verify_existing_w4_canary, summarize

CORE="0x4d410303"
MODEL="dn_d10_c32_us_fx_qat"
BASE=13289042


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.build=self.root/"zed_v4_p16_t4_w4_test"
        self.build.mkdir()
        (self.build/"system_wrapper.bit").write_bytes(b"fake-test-only-w4-not-for-hardware")
        self.sha=hashlib.sha256((self.build/"system_wrapper.bit").read_bytes()).hexdigest()
        cycles=[1328904]*9+[1328906]
        layers=[
            dict(name=f"conv{i}",emulated=False,mismatches=0,
                 core_id=[CORE],fclk_mhz=[50],cycles=c,
                 in_stall=12 if i==5 else 0,out_stall=0)
            for i,c in enumerate(cycles,1)]
        self.report=self.root/"report.json"
        self.physical=dict(emulated=False,model=MODEL,set="Set12",sigma=25,
                           mode_seq=1,activations_per_cycle=4,mismatches=0,
                           images=[dict(image="05.png",start_layer=1,
                                        layers=layers,cycles=BASE)])
        self.write_report()

    def write_report(self):
        self.report.write_text(json.dumps(self.physical),encoding="utf-8")

    def live(self):
        return verify_live_report(self.report,dict(total_cycles=BASE),self.sha,self.build)

    def make_canary(self):
        row=self.live()
        self.canary=self.root/"canary.json"
        self.canary.write_text(json.dumps(row),encoding="utf-8")
        return row

    def test_original_only_canary_valid_and_sha_bound(self):
        self.make_canary()
        self.assertEqual(verify_existing_w4_canary(self.canary,self.build),self.sha)

    def test_tampered_bitstream_rejected(self):
        self.make_canary()
        (self.build/"system_wrapper.bit").write_bytes(b"different, also fake")
        with self.assertRaises(ValueError):
            verify_existing_w4_canary(self.canary,self.build)

    def test_canary_rejects_mismatches_and_wrong_clock(self):
        self.physical["images"][0]["layers"][0]["mismatches"]=1
        self.write_report()
        with self.assertRaises(ValueError):
            self.live()
        self.physical["images"][0]["layers"][0]["mismatches"]=0
        self.physical["images"][0]["layers"][0]["fclk_mhz"]=[100]
        self.write_report()
        with self.assertRaises(ValueError):
            self.live()

    def test_triplet_summary_separates_conv2to9_and_stalls(self):
        rows=[
            dict(rep=1,cycles={"original":1000,"frozen":900,"multistart":850},
                 inner_cycles={"original":800,"frozen":720,"multistart":680},
                 in_stall={"original":12,"frozen":0,"multistart":1},
                 out_stall={"original":0,"frozen":0,"multistart":0}),
            dict(rep=2,cycles={"original":1000,"frozen":905,"multistart":845},
                 inner_cycles={"original":800,"frozen":725,"multistart":675},
                 in_stall={"original":0,"frozen":0,"multistart":0},
                 out_stall={"original":0,"frozen":0,"multistart":0}),
        ]
        result=summarize(self.root,rows,50)
        self.assertAlmostEqual(result["frozen_conv2to9_pct_saved"],9.6875)
        self.assertAlmostEqual(result["multistart_conv2to9_pct_saved"],15.3125)
        self.assertAlmostEqual(result["frozen_total_pct_saved"],9.75)
        self.assertAlmostEqual(result["multistart_total_pct_saved"],15.25)
        self.assertEqual(result["repeat_rows"][0]["in_stall"]["original"],12)
        md=(self.root/"triplet_summary.md").read_text(encoding="utf-8")
        self.assertIn("Conv2",md)
        self.assertIn("DMA stall",md)

    def test_triplet_rejects_fabricated_or_deviating_canary(self):
        obj=self.make_canary()
        for override in (
            {"status":"OFFLINE_PROVENANCE_AUDIT_ONLY"},
            {"physical_board_test_performed":False},
            {"core_id":"0x4d410000"},
            {"delta_pct":3.5},
            {"build_path":str(self.root/"other")},
        ):
            record={**obj,**override}
            self.canary.write_text(json.dumps(record),encoding="utf-8")
            with self.subTest(override=override),self.assertRaises(ValueError):
                verify_existing_w4_canary(self.canary,self.build)


if __name__=="__main__":
    unittest.main()
