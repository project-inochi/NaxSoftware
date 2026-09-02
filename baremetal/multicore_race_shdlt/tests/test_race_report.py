import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import race_report as p


def line(kind, values):
    return "SHDLT_RACE_" + kind + " " + " ".join(f"{k}=0x{v:x}" for k, v in values.items())


def records(case=0, cpus=2):
    phases = 2 if case == 1 else 1
    mask = (1 << phases) - 1
    begin = {"version": 1, "case": case, "cpus": cpus, "result_bytes": 512}
    harts = []
    for hart in range(cpus):
        entries = 1 if case == 6 and hart == 0 else (0 if case == 6 else phases)
        launch0 = hart
        finish0 = cpus - 1 - hart if case == 1 else hart
        values = {
            "case": case, "hart": hart, "status": p.STATUS_READY, "done": 1,
            "phase": 1 if case == 1 else 0,
            "target0": p.target_gpa(case, hart, 0),
            "target1": p.target_gpa(case, hart, 1) if phases == 2 else 0,
            "a": mask, "d": mask, "expected_d": mask, "initial": 0, "final": entries,
            "entries": entries, "entry_min": 0 if case == 6 else phases,
            "entry_max": 1 if case == 6 else phases,
            "log_bitmap": 1 if case == 6 and entries else (0 if case == 6 else mask),
            "duplicates": 0, "missing": 0, "extra": 0, "foreign": 0,
            "launch0": launch0, "finish0": finish0,
            "launch1": cpus - 1 - hart if case == 1 else 0,
            "finish1": hart if case == 1 else 0,
            "buffer_errors": 0, "result_errors": 0, "tail_writes": 0,
            "data_errors": 0, "pte_errors": 0, "faults": 0, "unexpected": 0,
            "isolation_errors": 0,
        }
        harts.append(values)
    total = sum(item["entries"] for item in harts)
    recorded = sum((1 << item["hart"]) for item in harts if item["entries"])
    global_record = {"case": case, "cpus": cpus, "completed": cpus, "failures": 0,
                     "total_entries": total, "recorded_harts": recorded, "data_errors": 0,
                     "pte_errors": 0, "buffer_errors": 0, "isolation_errors": 0, "status": 0}
    end = {"completed": cpus, "failures": 0, "status": 0}
    return begin, harts, global_record, end


def text(items=None):
    begin, harts, global_record, end = items or records()
    lines = [line("BEGIN", begin)]
    lines.extend(line("HART", hart) for hart in harts)
    lines.append(line("GLOBAL", global_record))
    lines.append(line("END", end))
    return "\n".join(lines) + "\n"


class RaceReportTests(unittest.TestCase):
    def test_all_cases_cpu_counts(self):
        for case in range(8):
            for cpus in (2, 4):
                with self.subTest(case=case, cpus=cpus):
                    report = p.parse_text(text(records(case, cpus)))
                    self.assertEqual(len(report.harts), cpus)

    def test_noise_is_ignored(self):
        p.parse_text("boot noise\n" + text() + "tail noise\n")

    def test_missing_hart(self):
        items = list(records())
        items[1].pop()
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_duplicate_hart(self):
        items = list(records())
        items[1][1] = copy.copy(items[1][0])
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_same_pte_requires_one_global_entry(self):
        items = list(records(6, 2))
        items[1][0]["entries"] = items[1][0]["final"] = items[1][0]["log_bitmap"] = 0
        items[2]["total_entries"] = items[2]["recorded_harts"] = 0
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_same_pte_rejects_two_entries_per_hart(self):
        items = list(records(6, 2))
        items[1][0]["entries"] = items[1][0]["final"] = 2
        items[2]["total_entries"] = 2
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_foreign_entry(self):
        items = list(records(4, 2))
        items[1][0]["foreign"] = 1
        items[2]["isolation_errors"] = 1
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_order_rank_mismatch(self):
        items = list(records(1, 4))
        items[1][0]["finish0"] = 0
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_guard_error(self):
        items = list(records())
        items[1][0]["buffer_errors"] = 1
        items[2]["buffer_errors"] = 1
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_failure_isolation_retains_all_harts(self):
        items = list(records(3, 4))
        items[1][2]["status"] = p.STATUS_FAIL
        items[2]["failures"] = items[2]["status"] = 1
        items[3]["failures"] = items[3]["status"] = 1
        report = p.parse_text(text(items), require_pass=False)
        self.assertEqual([item["hart"] for item in report.harts], [0, 1, 2, 3])
        with self.assertRaises(ValueError):
            p.parse_text(text(items))

    def test_error_record_rejected(self):
        with self.assertRaises(ValueError):
            p.parse_text(text() + "SHDLT_RACE_ERROR code=0x1\n")

    def test_duplicate_field_rejected(self):
        with self.assertRaises(ValueError):
            p.parse_text("SHDLT_RACE_BEGIN version=0x1 version=0x1\n", validate=False)


if __name__ == "__main__":
    unittest.main()
