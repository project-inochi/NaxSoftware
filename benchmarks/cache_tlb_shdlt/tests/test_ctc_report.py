import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from ctc_report import CASE_NAMES, EXPECTED_ENTRIES, EXPECTED_OUTCOME, EXPECTED_PHASE, parse_text

def transcript(case=0, cpus=2):
    lines = []
    for phase in range(EXPECTED_PHASE[case]):
        for action in ("begin", "end"):
            lines.append(f"SHDLT_CTC_PHASE case=0x{case:x} phase=0x{phase:x} action={action} "
                         f"hart_mask=0x{(1<<cpus)-1:x} gpa_base=0x40000 gpa_mask=0xfff "
                         "pte_base=0x83008200 pte_mask=0x7 probe_pa=0x83008200 probe_requested=0x0")
    lines.append(f"SHDLT_CTC_BEGIN abi_version=0x1 case=0x{case:x} cpus=0x{cpus:x} result_bytes=0x200")
    low, _ = EXPECTED_ENTRIES[case]
    total_entries = 0
    xfail = EXPECTED_OUTCOME[case] == 2
    for hart in range(cpus):
        entries = 1 if case == 4 and hart == 0 else low
        total_entries += entries
        values = dict(abi_version=1, case=case, outcome=EXPECTED_OUTCOME[case], status=0, done=1,
            hart=hart, cpus=cpus, phase=EXPECTED_PHASE[case], requested_gpa=0x40000,
            requested_vmid=(hart+1 if case == 7 else 0), readback_vmid=0,
            pte_before=1, pte_modified=1, pte_after=1, old_mapping_bitmap=(2 if case == 6 else 0),
            new_mapping_bitmap=(3 if xfail else 0), a_bitmap=1, d_bitmap=1, expected_bitmap=1,
            initial_index=0, final_index=entries, entries=entries,
            log_bitmap=((1 << entries)-1 if entries < 64 else (1<<64)-1), duplicates=0,
            missing=0, extra=0, data_errors=0, pte_errors=0,
            fence_errors=(1 if xfail else 0), faults=0,
            observer_required_mask=0, observer_available_mask=0, observer_valid_mask=0)
        lines.append("SHDLT_CTC_HART " + " ".join(f"{k}=0x{v:x}" for k,v in values.items()))
    passes = 0 if xfail else cpus
    lines.append(f"SHDLT_CTC_GLOBAL case=0x{case:x} cpus=0x{cpus:x} completed=0x{cpus:x} "
                 f"pass=0x{passes:x} fail=0x0 xfail=0x{cpus if xfail else 0:x} xpass=0x0 "
                 f"total_entries=0x{total_entries:x} status=0x0")
    lines.append(f"SHDLT_CTC_END completed=0x{cpus:x} fail=0x0 xfail=0x{cpus if xfail else 0:x} xpass=0x0 status=0x0")
    return "\n".join(lines)

class ReportTest(unittest.TestCase):
    def test_all_cases_2_and_4_harts(self):
        for case in range(len(CASE_NAMES)):
            for cpus in (2, 4):
                with self.subTest(case=case, cpus=cpus):
                    parse_text(transcript(case, cpus))

    def test_duplicate_hart(self):
        text = transcript().replace("hart=0x1", "hart=0x0")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_text(text)

    def test_missing_phase(self):
        text = "\n".join(line for line in transcript().splitlines()
                         if not ("SHDLT_CTC_PHASE" in line and "action=end" in line))
        with self.assertRaisesRegex(ValueError, "phase"):
            parse_text(text)

    def test_xpass_rejected(self):
        text = transcript(6).replace("outcome=0x2", "outcome=0x3")
        with self.assertRaisesRegex(ValueError, "XPASS"):
            parse_text(text)

    def test_xfail_needs_evidence(self):
        text = transcript(7).replace("fence_errors=0x1", "fence_errors=0x0")
        with self.assertRaisesRegex(ValueError, "evidence"):
            parse_text(text)

    def test_rvls_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, "RVLS"):
            parse_text(transcript() + "\nINTEGER WRITE MISSMATCH")

    def test_observer_required(self):
        with self.assertRaisesRegex(ValueError, "observer"):
            parse_text(transcript(), require_observer=True)

if __name__ == "__main__":
    unittest.main()
