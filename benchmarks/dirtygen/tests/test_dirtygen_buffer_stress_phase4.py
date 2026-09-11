import tempfile
import unittest
from pathlib import Path
import sys


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from run_dirtygen_buffer_stress_phase4 import (  # noqa: E402
    LOADS, Selection, campaign_schedule, cpu_config, pair_document, write_json,
)


class BufferStressCampaignTest(unittest.TestCase):
    def test_schedule_is_serial_pair_order_and_396_samples(self):
        schedule = campaign_schedule()
        self.assertEqual(len(schedule), 18)
        self.assertEqual(
            sum(18 if row.harts == 1 else 24 for row in schedule), 396)
        for ordinal in range(0, len(schedule), 2):
            self.assertEqual(schedule[ordinal].mode, "architecture")
            self.assertEqual(schedule[ordinal + 1].mode, "rvls")
            self.assertEqual(schedule[ordinal].harts, schedule[ordinal + 1].harts)
            self.assertEqual(schedule[ordinal].load, schedule[ordinal + 1].load)

    def test_pair_requires_identical_architecture_evidence(self):
        selection = Selection(2, LOADS[0], "architecture")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            architecture, rvls = root / "architecture", root / "rvls"
            artifact = {"elf_sha256": "abc"}
            for run in (architecture, rvls):
                (run / "report").mkdir(parents=True)
                write_json(run / "metadata.json", {
                    "artifact": artifact, "cpu_config": cpu_config(selection),
                })
                write_json(run / "report" / "samples.json", {
                    "status": "PASS", "samples": [{} for _ in range(24)]})
                for name in ("trace-report.json", "performance.json"):
                    write_json(run / "report" / name, {"status": "PASS"})
                (run / "tracer.log").write_text("trace\n")
                (run / "TestBenchDut.generated.v").write_text("module dut; endmodule\n")
            self.assertEqual(
                pair_document(architecture, rvls, selection)["status"], "PASS")
            write_json(rvls / "report" / "performance.json", {"status": "changed"})
            with self.assertRaises(RuntimeError):
                pair_document(architecture, rvls, selection)


if __name__ == "__main__":
    unittest.main()
