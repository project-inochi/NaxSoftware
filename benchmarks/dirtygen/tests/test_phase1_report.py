import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import phase1_report


def valid_log() -> str:
    return """unrelated Mill output
SHDLT_PHASE1_BEGIN cases=0x4
SHDLT_PHASE1 case=boundary_full_a0d0 id=0x0 status=0x0 expected_cause=0x18 actual_cause=0x18 pte_before=0x20000017 pte_after=0x20000017 data_before=0xa70d1c0000000000 data_after=0xa70d1c0000000000 idx_before=0x200 idx_after=0x200 buffer_errors=0x0
SHDLT_PHASE1 case=log_target_store_fault id=0x1 status=0x0 expected_cause=0x7 actual_cause=0x7 pte_before=0x20000457 pte_after=0x20000457 data_before=0xa70d1c0000000001 data_after=0xa70d1c0000000001 idx_before=0x0 idx_after=0x0 buffer_errors=0x0
SHDLT_PHASE1 case=invalid_gstage_pte_full id=0x2 status=0x0 expected_cause=0x17 actual_cause=0x17 pte_before=0x20000800 pte_after=0x20000800 data_before=0xa70d1c0000000002 data_after=0xa70d1c0000000002 idx_before=0x200 idx_after=0x200 buffer_errors=0x0
SHDLT_PHASE1 case=write_permission_denied_full id=0x3 status=0x0 expected_cause=0x17 actual_cause=0x17 pte_before=0x20000c53 pte_after=0x20000c53 data_before=0xa70d1c0000000003 data_after=0xa70d1c0000000003 idx_before=0x200 idx_after=0x200 buffer_errors=0x0
SHDLT_PHASE1_END cases=0x4 failures=0x0 status=0x0
"""


class Phase1ReportTest(unittest.TestCase):
    def parse_valid(self):
        report = phase1_report.parse_lines(io.StringIO(valid_log()))
        report.validate()
        return report

    def test_valid_report(self):
        report = self.parse_valid()
        self.assertEqual(len(report.cases), 4)

    def test_wrong_fault_cause_is_rejected(self):
        report = phase1_report.parse_lines(
            io.StringIO(
                valid_log().replace(
                    "expected_cause=0x17 actual_cause=0x17",
                    "expected_cause=0x17 actual_cause=0x18",
                    1,
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "actual_cause"):
            report.validate()

    def test_invalid_pte_with_valid_bit_is_rejected(self):
        report = phase1_report.parse_lines(
            io.StringIO(valid_log().replace("0x20000800", "0x20000801"))
        )
        with self.assertRaisesRegex(ValueError, "initial PTE flags"):
            report.validate()

    def test_permission_pte_with_write_bit_is_rejected(self):
        report = phase1_report.parse_lines(
            io.StringIO(valid_log().replace("0x20000c53", "0x20000c57"))
        )
        with self.assertRaisesRegex(ValueError, "initial PTE flags"):
            report.validate()

    def test_partial_pte_update_is_rejected(self):
        report = phase1_report.parse_lines(
            io.StringIO(valid_log().replace("pte_after=0x20000017", "pte_after=0x200000d7"))
        )
        with self.assertRaisesRegex(ValueError, "changed its PTE"):
            report.validate()

    def test_index_change_is_rejected(self):
        report = phase1_report.parse_lines(
            io.StringIO(valid_log().replace("idx_after=0x0", "idx_after=0x1"))
        )
        with self.assertRaisesRegex(ValueError, "idx_after"):
            report.validate()

    def test_buffer_change_is_rejected(self):
        report = phase1_report.parse_lines(
            io.StringIO(valid_log().replace("buffer_errors=0x0", "buffer_errors=0x1", 1))
        )
        with self.assertRaisesRegex(ValueError, "buffer_errors"):
            report.validate()

    def test_missing_case_is_rejected(self):
        lines = [
            line
            for line in valid_log().splitlines()
            if "case=invalid_gstage_pte_full" not in line
        ]
        report = phase1_report.parse_lines(io.StringIO("\n".join(lines)))
        with self.assertRaisesRegex(ValueError, "expected 4 Phase-1 cases"):
            report.validate()


if __name__ == "__main__":
    unittest.main()
