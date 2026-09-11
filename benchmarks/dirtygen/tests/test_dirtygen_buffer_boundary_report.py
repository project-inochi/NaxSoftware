import io
import sys
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from dirtygen_buffer_boundary_report import (  # noqa: E402
    ABI_VERSION, EXACT_FULL_FAULT, FULL_PREDIRTY_BYPASS, LAST_SLOT_COMMIT,
    PROFILE_H1, PROFILE_MULTI, PROFILE_STRESS, STRESS_ABI_VERSION,
    RESERVED_SIZE_WARL, STALE_D_FULL_OBSERVERS,
    BoundaryReport, ReportError, capacity, check_trace, expected_committed_logs,
    diagnostic_trace_summary, expected_d, expected_log, expected_pte_stores,
    fault_count, final_dirty,
    final_index, initial_index, logging_enabled, parse_lines, primary,
    pte, recovery, replacement, replacement_sentinel, schedule, sentinel,
    store_succeeds, stress_performance, target_gpa, target_page, value,
    value_hart,
)


def record(tag, fields):
    return tag + " " + " ".join(
        f"{name}=0x{item:x}" for name, item in fields.items())


def valid_console(hart_count, profile, store_pc=0x108):
    selections = schedule(profile, hart_count)
    lines = [record("SHDLT_BUFFER_BOUNDARY_BEGIN", {
        "abi": STRESS_ABI_VERSION if profile == PROFILE_STRESS else ABI_VERSION,
        "profile": profile, "hart_count": hart_count,
        "selections": len(selections),
    })]
    for selection, (case, requested_size) in enumerate(selections):
        sample_faults = sum(fault_count(case, hart) for hart in range(hart_count))
        sample_fields = {
            "selection": selection, "case": case,
            "size_requested": requested_size, "hart_count": hart_count,
            "status": 0, "pte_errors": 0, "data_errors": 0,
            "buffer_errors": 0, "control_errors": 0,
            "faults": sample_faults,
            "d_transitions": sum(expected_d(case, hart) for hart in range(hart_count)),
            "committed_logs": sum(expected_log(case, hart) for hart in range(hart_count)),
            "cas_attempts": sum(expected_d(case, hart) for hart in range(hart_count)),
            "log_faults": sample_faults,
        }
        if profile == PROFILE_STRESS:
            sample_fields.update({
                "warmup": int(selection % 6 == 0),
                "repetition": 0 if selection % 6 == 0 else selection % 6 - 1,
            })
        lines.append(record("SHDLT_BUFFER_BOUNDARY_SAMPLE", sample_fields))
        for hart in range(hart_count):
            size = requested_size if requested_size <= 9 else 0
            cap = capacity(size)
            base = primary(hart)
            faults = fault_count(case, hart)
            before_dirty = case == FULL_PREDIRTY_BYPASS
            primary0 = sentinel(hart, 0)
            primary_last = sentinel(hart, cap - 1)
            replacement0 = replacement_sentinel(hart, 0)
            if case == LAST_SLOT_COMMIT and hart == 0:
                primary_last = target_gpa(case, hart)
            if case in (8, 10) and hart == 0:
                primary0 = target_gpa(case, hart)
            if recovery(case) and faults:
                replacement0 = target_gpa(case, hart)
            hart_fields = {
                "selection": selection, "case": case, "hart": hart,
                "status": 0, "size_requested": requested_size,
                "size_readback": size, "capacity": cap,
                "base_readback": base,
                "idx_before": initial_index(case, hart, cap),
                "idx_at_fault": initial_index(case, hart, cap) if faults else 0,
                "idx_after": final_index(case, hart, cap),
                "ctl": ((base >> 12) << 10) | (size << 1) | int(logging_enabled(case)),
                "fault_count": faults, "fault_cause": 24 if faults else 0,
                "fault_sepc": store_pc if faults else 0,
                "fault_stval": 0, "fault_htval": 0,
                "pte_at_fault": pte(target_page(case, hart), False) if faults else 0,
                "data_at_fault": 0,
                "primary0_at_fault": sentinel(hart, 0) if faults else 0,
                "primary_last_at_fault": sentinel(hart, cap - 1) if faults else 0,
                "primary_guard_at_fault": sentinel(hart, cap) if faults else 0,
                "ecall_count": 1, "ecall_cause": 10,
                "cycle_start": 100, "cycle_end": 120,
                "instret_start": 20, "instret_end": 28,
                "prefill_value": 0,
                "pte_before": pte(target_page(case, hart), before_dirty),
                "pte_final": pte(target_page(case, hart), final_dirty(case)),
                "data_final": value(selection, value_hart(case, hart))
                if store_succeeds(case) else 0,
                "primary0_final": primary0,
                "primary_last_final": primary_last,
                "primary_guard_final": sentinel(hart, cap),
                "replacement0_final": replacement0,
                "replacement_last_final": replacement_sentinel(hart, cap - 1),
                "replacement_guard_final": replacement_sentinel(hart, cap),
                "d_transitions": expected_d(case, hart),
                "committed_logs": expected_log(case, hart),
                "cas_attempts": expected_d(case, hart),
                "log_faults": faults,
            }
            if profile == PROFILE_STRESS:
                hart_fields.update({
                    "fault_entry_cycle": 108 if faults else 0,
                    "fault_resume_cycle": 114 if faults else 0,
                })
            lines.append(record("SHDLT_BUFFER_BOUNDARY_HART", hart_fields))
    lines.append(record("SHDLT_BUFFER_BOUNDARY_END", {
        "selections": len(selections), "failures": 0, "status": 0,
    }))
    return "\n".join(lines) + "\n"


def valid_trace(hart_count, profile, epoch_start=0x2000, epoch_end=0x2100,
                add_superseded=False):
    lines = []
    attempt = 0
    for selection, (case, requested_size) in enumerate(schedule(profile, hart_count)):
        for hart in range(hart_count):
            lines.append(f"rv commit {hart} {epoch_start:016x} 00000013")
        cap = capacity(requested_size if requested_size <= 9 else 0)
        logs = expected_committed_logs(case, cap, hart_count)
        for hart, address, length, data, error in logs:
            attempt += 1
            lines.append(
                f"rv mmu physical-store {hart} {hart + 1} {attempt} 100 "
                f"{address:016x} {length} {data:016x} {error} pending")
            lines.append(
                f"rv mmu physical-store {hart} {hart + 1} {attempt} 101 "
                f"{address:016x} {length} {data:016x} {error} committed")
        if add_superseded and case == STALE_D_FULL_OBSERVERS:
            for hart in range(1, hart_count):
                attempt += 1
                address = primary(hart) + cap * 8
                data = target_gpa(case, hart)
                lines.append(
                    f"rv mmu physical-store {hart} {hart + 1} {attempt} 102 "
                    f"{address:016x} 8 {data:016x} 0 pending")
                lines.append(
                    f"rv mmu physical-store {hart} {hart + 1} {attempt} 103 "
                    f"{address:016x} 8 {data:016x} 0 superseded")
        for item in logs + expected_pte_stores(case, hart_count):
            hart, address, length, data, error = item
            lines.append(f"rv mmu store {hart} {address:016x} {length} {data:016x} {error}")
        for hart in range(hart_count):
            lines.append(f"rv commit {hart} {epoch_end:016x} 00000013")
    return "\n".join(lines) + "\n"


class BufferBoundaryReportTest(unittest.TestCase):
    def test_h1_all_sizes_and_warl(self):
        report = parse_lines(io.StringIO(valid_console(1, PROFILE_H1)))
        self.assertEqual(report.architecture_errors(1, PROFILE_H1, 0x108), [])
        trace = check_trace(io.StringIO(valid_trace(1, PROFILE_H1)),
                            0x2000, 0x2100, 1, PROFILE_H1)
        self.assertEqual(trace["status"], "PASS")

    def test_h4_multi_and_legal_superseded(self):
        report = parse_lines(io.StringIO(valid_console(4, PROFILE_MULTI)))
        self.assertEqual(report.architecture_errors(4, PROFILE_MULTI, 0x108), [])
        trace = check_trace(io.StringIO(valid_trace(
            4, PROFILE_MULTI, add_superseded=True)),
            0x2000, 0x2100, 4, PROFILE_MULTI)
        self.assertGreater(trace["totals"]["superseded"], 0)

    def test_stress_schedules_and_metrics(self):
        self.assertEqual(len(schedule(PROFILE_STRESS, 1)), 18)
        self.assertEqual(len(schedule(PROFILE_STRESS, 2)), 24)
        self.assertEqual(len(schedule(PROFILE_STRESS, 4)), 24)
        report = parse_lines(io.StringIO(valid_console(4, PROFILE_STRESS)))
        self.assertEqual(report.architecture_errors(4, PROFILE_STRESS, 0x108), [])
        performance = stress_performance(report, 4)
        self.assertEqual(len(performance["samples"]), 24)
        self.assertEqual(
            performance["summary"]["STALE_D_FULL_OBSERVERS"]["measured_samples"], 5)
        self.assertEqual(
            performance["summary"]["EXACT_FULL_FAULT"]
            ["handler_service_cycles"]["median"], 6)

    def test_stress_fault_timing_order_is_enforced(self):
        text = valid_console(1, PROFILE_STRESS).replace(
            "fault_entry_cycle=0x6c", "fault_entry_cycle=0x73", 1).replace(
                "fault_resume_cycle=0x72", "fault_resume_cycle=0x70", 1)
        report = parse_lines(io.StringIO(text))
        self.assertTrue(report.architecture_errors(1, PROFILE_STRESS, 0x108))

    def test_fault_atomicity_corruption_is_rejected(self):
        text = valid_console(1, PROFILE_H1).replace(
            "data_at_fault=0x0", "data_at_fault=0x1", 1)
        report = parse_lines(io.StringIO(text))
        self.assertTrue(report.architecture_errors(1, PROFILE_H1, 0x108))

    def test_missing_hart_is_rejected(self):
        lines = valid_console(2, PROFILE_MULTI).splitlines()
        del lines[2]
        report = parse_lines(io.StringIO("\n".join(lines) + "\n"))
        with self.assertRaises(ReportError):
            report.validate_shape(2, PROFILE_MULTI)

    def test_duplicate_terminal_lifecycle_is_rejected(self):
        trace = valid_trace(1, PROFILE_H1)
        first = next(line for line in trace.splitlines() if line.endswith(" committed"))
        trace = trace.replace(first, first + "\n" + first, 1)
        with self.assertRaises(ReportError):
            check_trace(io.StringIO(trace), 0x2000, 0x2100, 1, PROFILE_H1)

    def test_unclosed_lifecycle_is_rejected(self):
        trace = valid_trace(1, PROFILE_H1).replace(" committed\n", " pending\n", 1)
        with self.assertRaises(ReportError):
            check_trace(io.StringIO(trace), 0x2000, 0x2100, 1, PROFILE_H1)

    def test_failure_trace_summary_does_not_hide_open_lifecycle(self):
        trace = valid_trace(1, PROFILE_H1).replace(" committed\n", " pending\n", 1)
        summary = diagnostic_trace_summary(io.StringIO(trace))
        self.assertEqual(summary["status"], "DIAGNOSTIC_INCOMPLETE")
        self.assertTrue(summary["architecture_verdict_independent"])


if __name__ == "__main__":
    unittest.main()
