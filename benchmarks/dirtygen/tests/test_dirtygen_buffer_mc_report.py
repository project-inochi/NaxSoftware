import io
import sys
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from dirtygen_buffer_mc_report import (  # noqa: E402
    CAPACITY, CASE, HART_COUNT, LOG_BASE, LOG_STRIDE, PTE_CLEAN, PTE_DIRTY,
    RUNS, TRACKED_GPA, BufferMcReport, ReportError, check_trace,
    expected_value, logger_control, parse_lines, sentinel,
)


def record(tag, fields):
    return tag + " " + " ".join(f"{name}=0x{value:x}" for name, value in fields.items())


def valid_console(false_full=False, hart_count=HART_COUNT):
    lines = [record("SHDLT_BUFFER_MC_BEGIN", {
        "abi": 1, "hart_count": hart_count, "case": CASE, "size": 0,
        "capacity": CAPACITY, "samples": RUNS,
    })]
    for sample in range(RUNS):
        lines.append(record("SHDLT_BUFFER_MC_SAMPLE", {
            "sample": sample, "warmup": int(sample == 0),
            "repetition": 0 if sample == 0 else sample - 1,
            "status": 0x45 if false_full else 0,
            "pte_before": PTE_CLEAN, "pte_after": PTE_DIRTY,
            "data_errors": (hart_count - 1) if false_full else 0,
            "buffer_errors": 0,
            "d_transitions": 1, "committed_logs": 1, "cas_attempts": 1,
            "log_faults": (hart_count - 1) if false_full else 0,
        }))
        for hart in range(hart_count):
            fault = false_full and hart != 0
            lines.append(record("SHDLT_BUFFER_MC_HART", {
                "sample": sample, "hart": hart, "case": CASE,
                "status": 0x45 if fault else 0,
                "logger_base": LOG_BASE + hart * LOG_STRIDE,
                "size_readback": 0, "capacity": CAPACITY,
                "idx_before": 0 if hart == 0 else CAPACITY,
                "idx_at_fault": CAPACITY if fault else 0,
                "idx_after": 1 if hart == 0 else CAPACITY,
                "ctl": logger_control(hart), "fault_count": int(fault),
                "fault_cause": 24 if fault else 0,
                "fault_sepc": 0x6C if fault else 0,
                "fault_stval": 0, "fault_htval": 0,
                "pte_at_fault": PTE_DIRTY if fault else 0,
                "data_at_fault": 0,
                "log0_at_fault": sentinel(hart, 0) if fault else 0,
                "log_last_at_fault": sentinel(hart, CAPACITY - 1) if fault else 0,
                "guard_at_fault": sentinel(hart, CAPACITY) if fault else 0,
                "ecall_count": 1, "ecall_cause": 10,
                "cycle_start": 100, "cycle_end": 120,
                "instret_start": 20, "instret_end": 28,
                "prefill_value": 0, "pte_final": PTE_DIRTY,
                "data_final": (0 if fault else expected_value(sample, hart)),
                "log0_final": TRACKED_GPA if hart == 0 else sentinel(hart, 0),
                "log_last_final": sentinel(hart, CAPACITY - 1),
                "guard_final": sentinel(hart, CAPACITY),
                "d_transitions": 1 if hart == 0 else 0,
                "committed_logs": 1 if hart == 0 else 0,
                "cas_attempts": 1 if hart == 0 else 0,
                "log_faults": int(fault),
            }))
    lines.append(record("SHDLT_BUFFER_MC_END", {
        "samples": RUNS, "failures": RUNS if false_full else 0,
        "status": int(false_full),
    }))
    return "\n".join(lines) + "\n"


def valid_trace(epoch_start=0x2000, epoch_end=0x2100,
                hart_count=HART_COUNT):
    lines = []
    for sample in range(RUNS):
        for hart in range(hart_count):
            lines.append(f"rv commit {hart} {epoch_start:016x} 00000013")
        source = sample + 1
        lines.extend([
            f"rv mmu physical-store 0 {source} 0 100 {LOG_BASE:016x} 8 {TRACKED_GPA:016x} 0 pending",
            f"rv mmu store 0 {LOG_BASE:016x} 8 {TRACKED_GPA:016x} 0",
            f"rv mmu store 0 0000000081005080 8 {PTE_DIRTY:016x} 0",
            f"rv mmu physical-store 0 {source} 0 101 {LOG_BASE:016x} 8 {TRACKED_GPA:016x} 0 committed",
        ])
        for hart in range(hart_count):
            lines.append(f"rv commit {hart} {epoch_end:016x} 00000013")
    return "\n".join(lines) + "\n"


class BufferMcReportTest(unittest.TestCase):
    def test_valid_architecture_and_trace(self):
        report = parse_lines(io.StringIO(valid_console()))
        self.assertEqual(report.architecture_errors(), [])
        trace = check_trace(io.StringIO(valid_trace()), 0x2000, 0x2100)
        self.assertEqual(trace["totals"]["committed"], RUNS)
        self.assertEqual(trace["totals"]["architectural_stores"], RUNS * 2)

    def test_valid_h4_architecture_and_trace(self):
        report = parse_lines(io.StringIO(valid_console(hart_count=4)))
        self.assertEqual(report.architecture_errors(4), [])
        trace = check_trace(io.StringIO(valid_trace(hart_count=4)),
                            0x2000, 0x2100, 4)
        self.assertEqual(trace["totals"]["committed"], RUNS)

    def test_stale_d_false_full_is_rejected_and_classified(self):
        report = parse_lines(io.StringIO(valid_console(false_full=True)))
        self.assertTrue(report.architecture_errors())
        self.assertEqual(report.classification(0x6C), "STALE_D_FALSE_FULL_FAULT")

    def test_missing_hart_record_is_rejected(self):
        lines = valid_console().splitlines()
        del lines[3]
        report = parse_lines(io.StringIO("\n".join(lines) + "\n"))
        with self.assertRaises(ReportError):
            report.validate_shape()

    def test_duplicate_terminal_lifecycle_is_rejected(self):
        trace = valid_trace().replace(
            " 0 committed\n", " 0 committed\n" +
            f"rv mmu physical-store 0 1 0 102 {LOG_BASE:016x} 8 {TRACKED_GPA:016x} 0 committed\n",
            1,
        )
        with self.assertRaises(ReportError):
            check_trace(io.StringIO(trace), 0x2000, 0x2100)

    def test_unclosed_lifecycle_is_rejected(self):
        trace = valid_trace().replace(" 0 committed\n", " 0 pending\n", 1)
        with self.assertRaises(ReportError):
            check_trace(io.StringIO(trace), 0x2000, 0x2100)


if __name__ == "__main__":
    unittest.main()
