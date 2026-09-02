import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RTL_SPEC = importlib.util.spec_from_file_location(
    "rtl_report_for_invariants", ROOT / "tools" / "rtl_report.py")
rtl_report = importlib.util.module_from_spec(RTL_SPEC)
assert RTL_SPEC.loader
sys.modules[RTL_SPEC.name] = rtl_report
RTL_SPEC.loader.exec_module(rtl_report)
SPEC = importlib.util.spec_from_file_location(
    "invariant_report", ROOT / "tools" / "invariant_report.py")
invariant_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = invariant_report
SPEC.loader.exec_module(invariant_report)


def race_hart(hart: int, entries: int = 1) -> dict:
    return {
        "case": 6, "hart": hart, "status": 0x600D, "done": 1, "phase": 0,
        "target0": 0x30000, "target1": 0, "a": 1, "d": 1, "expected_d": 1,
        "initial": 0, "final": entries, "entries": entries,
        "entry_min": 0, "entry_max": 1, "log_bitmap": 1 if entries else 0,
        "duplicates": 0, "missing": 0, "extra": 0, "foreign": 0,
        "launch0": hart, "finish0": 1 - hart, "launch1": 0, "finish1": 0,
        "buffer_errors": 0, "result_errors": 0, "tail_writes": 0,
        "data_errors": 0, "pte_errors": 0, "faults": 0, "unexpected": 0,
        "isolation_errors": 0,
    }


class InvariantReportTest(unittest.TestCase):
    def trace(self, appends: int, ptes: int) -> rtl_report.TraceSummary:
        return rtl_report.TraceSummary(2, appends + ptes, appends, ptes, 0, 0, 0)

    def test_same_pte_allows_one_global_winner(self):
        arch = {"harts": [race_hart(0, 1), race_hart(1, 0)]}
        report = invariant_report.check_invariants(
            "race", "same_pte", 2, self.trace(1, 1), arch)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["checks"]["retry_no_duplicate_architectural_commit"])

    def test_architecture_records_are_checked_without_rvls_trace(self):
        arch = {"harts": [race_hart(0, 1), race_hart(1, 1)]}
        trace = rtl_report.empty_trace(2)
        report = invariant_report.check_invariants(
            "race", "different_pages", 2, trace, arch)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["trace_available"])
        self.assertEqual(
            report["trace_checks_skipped"],
            ["trace_balance", "trace_attribution", "trace_event_counts"],
        )
        self.assertTrue(report["checks"]["hart_isolation"])

    def test_architecture_only_does_not_hide_missing_arch_records(self):
        report = invariant_report.check_invariants(
            "race", "different_pages", 2, rtl_report.empty_trace(2), None)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["trace_available"])

    def test_same_pte_duplicate_commit_is_rejected(self):
        arch = {"harts": [race_hart(0, 1), race_hart(1, 1)]}
        report = invariant_report.check_invariants(
            "race", "same_pte", 2, self.trace(2, 1), arch)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["retry_no_duplicate_architectural_commit"])

    def test_duplicate_hart_record_is_rejected_as_contamination(self):
        first = race_hart(0, 1)
        second = race_hart(0, 1)
        report = invariant_report.check_invariants(
            "race", "same_pte", 2, self.trace(1, 1), {"harts": [first, second]})
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["hart_isolation"])

    def test_ctc_pte_permission_change_is_rejected(self):
        records = []
        for hart in range(2):
            record = {
                "hart": hart, "entries": 1, "initial_index": 0,
                "final_index": 1, "duplicates": 0, "faults": 0,
                "pte_errors": 0, "foreign": 0, "buffer_errors": 0,
                "result_errors": 0, "isolation_errors": 0,
                "pte_before": 0x1000, "pte_after": 0x1000 | 0x80,
            }
            records.append(record)
        records[1]["pte_after"] |= 0x4  # W changed: not a dirty transition.
        report = invariant_report.check_invariants(
            "ctc", "cas_retry", 2, self.trace(2, 0), {"harts": records})
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["cas_preserves_pte_bits"])

    def test_smoke_logger_off_requires_no_append(self):
        report = invariant_report.check_invariants(
            "smoke", "log_off", 2, self.trace(0, 2))
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["checks"]["logger_disabled_or_frozen_no_append"])

    def test_smoke_logger_off_append_is_rejected(self):
        report = invariant_report.check_invariants(
            "smoke", "log_off", 2, self.trace(1, 2))
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["checks"]["logger_disabled_or_frozen_no_append"])

    def test_smoke_architecture_only_marks_trace_unavailable(self):
        report = invariant_report.check_invariants(
            "smoke", "load_only", 2, rtl_report.empty_trace(2))
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["trace_available"])
        self.assertEqual(
            report["architecture_evidence"],
            "firmware-result+pass-policy-all",
        )
        self.assertIn("trace_balance", report["trace_checks_skipped"])

    def test_dirtygen_missing_architecture_report_is_rejected(self):
        report = invariant_report.check_invariants(
            "dirtygen", "all", 1, rtl_report.empty_trace(1), None)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["architecture_evidence"], "missing")

    def test_cli_writes_machine_readable_result(self):
        trace_text = "\n".join([
            "rv new 0 RV64 0 0 0 0 0 0",
            "rv new 1 RV64 0 0 0 0 0 0",
            "rv mmu store 0 0000000082010000 8 0000000000030000 0",
            "rv mmu store 1 0000000082810000 8 0000000000040000 0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / "tracer.log"
            arch = root / "race.json"
            output = root / "invariants.json"
            trace.write_text(trace_text)
            harts = [race_hart(h, 1) for h in range(2)]
            for h, record in enumerate(harts):
                record["case"] = 0
                record["target0"] = 0x30000 + h * 0x8000
                record["entry_min"] = record["entry_max"] = 1
                record["log_bitmap"] = 1
            arch.write_text(json.dumps({"harts": harts}))
            completed = __import__("subprocess").run(
                [sys.executable, str(ROOT / "tools" / "invariant_report.py"),
                 "--family", "race", "--case", "different_pages", "--cpus", "2",
                 "--trace", str(trace), "--arch", str(arch),
                 "--json", str(output)],
                text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(output.read_text())["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
