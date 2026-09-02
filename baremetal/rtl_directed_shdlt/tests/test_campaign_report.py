import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "campaign_report.py"


def result(run_id: str, mmu_stores: int = 2) -> dict:
    return {
        "family": "race",
        "case": run_id,
        "cpus": 2,
        "status": "PASS",
        "trace": {
            "cpus": 2,
            "mmu_stores": mmu_stores,
            "appends": 1,
            "pte_updates": mmu_stores - 1,
            "traps": 2,
            "dirty_log_faults": 0,
            "attribution_errors": 0,
        },
        "details": {},
    }


class CampaignReportTest(unittest.TestCase):
    def run_report(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--expected", str(root / "expected.txt"),
                "--results", str(root / "results"),
                "--json", str(root / "summary.json"),
                "--text", str(root / "summary.txt"),
            ],
            text=True, capture_output=True, check=False,
        )

    def test_complete_selected_set_is_aggregated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            (root / "expected.txt").write_text("run-a\nrun-b\n")
            (results / "run-a.json").write_text(json.dumps(result("a", 2)))
            (results / "run-b.json").write_text(json.dumps(result("b", 4)))
            invariant = {"status": "PASS", "checks": {"example": True}}
            (results / "run-a.invariants.json").write_text(json.dumps(invariant))
            (results / "run-b.invariants.json").write_text(json.dumps(invariant))
            (results / "unselected.json").write_text(json.dumps(result("x", 8)))
            completed = self.run_report(root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads((root / "summary.json").read_text())
            self.assertEqual(summary["totals"]["runs"], 2)
            self.assertEqual(summary["totals"]["mmu_stores"], 6)
            self.assertEqual(summary["totals"]["invariant_failures"], 0)
            self.assertEqual(summary["extra_ignored"], ["unselected"])

    def test_missing_selected_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "expected.txt").write_text("run-a\nrun-b\n")
            (root / "results" / "run-a.json").write_text(
                json.dumps(result("a")))
            completed = self.run_report(root)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("campaign results missing", completed.stderr)

    def test_duplicate_expected_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "expected.txt").write_text("run-a\nrun-a\n")
            completed = self.run_report(root)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("duplicate run IDs", completed.stderr)

    def test_trace_availability_is_aggregated_without_inventing_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            (root / "expected.txt").write_text("arch-only\nrvls\n")
            arch = result("arch-only", 0)
            arch["trace"]["available"] = False
            arch["trace_available"] = False
            rvls = result("rvls", 2)
            rvls["trace"]["available"] = True
            rvls["trace_available"] = True
            (results / "arch-only.json").write_text(json.dumps(arch))
            (results / "rvls.json").write_text(json.dumps(rvls))
            invariant = {"status": "PASS", "checks": {"example": True}}
            (results / "arch-only.invariants.json").write_text(json.dumps(invariant))
            (results / "rvls.invariants.json").write_text(json.dumps(invariant))
            completed = self.run_report(root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads((root / "summary.json").read_text())
            self.assertEqual(summary["totals"]["trace_available_runs"], 1)
            self.assertEqual(summary["totals"]["trace_unavailable_runs"], 1)
            self.assertIn("trace_unavailable=1", (root / "summary.txt").read_text())


if __name__ == "__main__":
    unittest.main()
