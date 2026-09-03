import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import phase6_report


def valid_log() -> str:
    return """unrelated Mill output
SHDLT_PHASE6_BEGIN cases=0x1
SHDLT_PHASE6 case=implicit_vs_pte_store id=0x0 status=0x0 expected_cause=0xa actual_cause=0xa vs_pte_before=0x4087 vs_pte_after=0x40c7 gstage_pt_pte_before=0x20040057 gstage_pt_pte_after=0x200400d7 gstage_data_pte_before=0x200800d7 gstage_data_pte_after=0x200800d7 data_before=0xa60d1c0000000000 data_after=0x1122334455667788 idx_before=0x0 idx_after=0x1 expected_log_entry=0x202000 actual_log_entry=0x202000 buffer_errors=0x0
SHDLT_PHASE6_END cases=0x1 failures=0x0 status=0x0
"""


class Phase6ReportTest(unittest.TestCase):
    def parse_valid(self):
        report = phase6_report.parse_lines(io.StringIO(valid_log()))
        report.validate()
        return report

    def test_valid_report(self):
        report = self.parse_valid()
        self.assertEqual(len(report.cases), 1)

    def test_wrong_cause_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(valid_log().replace("actual_cause=0xa", "actual_cause=0x17"))
        )
        with self.assertRaisesRegex(ValueError, "actual_cause"):
            report.validate()

    def test_wrong_initial_vs_pte_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(valid_log().replace("vs_pte_before=0x4087", "vs_pte_before=0x40c7"))
        )
        with self.assertRaisesRegex(ValueError, "initial vs_pte_before"):
            report.validate()

    def test_missing_vs_accessed_transition_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(valid_log().replace("vs_pte_after=0x40c7", "vs_pte_after=0x4087"))
        )
        with self.assertRaisesRegex(ValueError, "vs_pte transition"):
            report.validate()

    def test_missing_gstage_dirty_transition_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(
                valid_log().replace(
                    "gstage_pt_pte_after=0x200400d7",
                    "gstage_pt_pte_after=0x20040057",
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "gstage_pt_pte transition"):
            report.validate()

    def test_wrong_initial_gstage_pt_pte_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(
                valid_log().replace(
                    "gstage_pt_pte_before=0x20040057",
                    "gstage_pt_pte_before=0x200400d7",
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "initial gstage_pt_pte_before"):
            report.validate()

    def test_wrong_initial_gstage_data_pte_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(
                valid_log().replace(
                    "gstage_data_pte_before=0x200800d7",
                    "gstage_data_pte_before=0x20080057",
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "initial gstage_data_pte"):
            report.validate()

    def test_changed_gstage_data_pte_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(
                valid_log().replace(
                    "gstage_data_pte_after=0x200800d7",
                    "gstage_data_pte_after=0x20080057",
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "changed gstage_data_pte"):
            report.validate()

    def test_data_gpa_log_entry_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(valid_log().replace("actual_log_entry=0x202000", "actual_log_entry=0x10000"))
        )
        with self.assertRaisesRegex(ValueError, "actual_log_entry"):
            report.validate()

    def test_extra_log_index_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(valid_log().replace("idx_after=0x1", "idx_after=0x2"))
        )
        with self.assertRaisesRegex(ValueError, "idx_after"):
            report.validate()

    def test_extra_buffer_write_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(valid_log().replace("buffer_errors=0x0", "buffer_errors=0x1"))
        )
        with self.assertRaisesRegex(ValueError, "buffer_errors"):
            report.validate()

    def test_wrong_guest_data_is_rejected(self):
        report = phase6_report.parse_lines(
            io.StringIO(
                valid_log().replace(
                    "data_after=0x1122334455667788",
                    "data_after=0x1122334455667789",
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "data_after"):
            report.validate()

    def test_missing_case_is_rejected(self):
        lines = [line for line in valid_log().splitlines() if " case=" not in line]
        report = phase6_report.parse_lines(io.StringIO("\n".join(lines)))
        with self.assertRaisesRegex(ValueError, "expected 1 Phase-6 case"):
            report.validate()


if __name__ == "__main__":
    unittest.main()
