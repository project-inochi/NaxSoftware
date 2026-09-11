import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "dirtygen_perf_mc_report.py"
SPEC = importlib.util.spec_from_file_location("dirtygen_perf_mc_report", MODULE_PATH)
mc = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mc
SPEC.loader.exec_module(mc)

EPOCH_START = 0x80001000
EPOCH_END = 0x80002000


def valid_report(harts=2, workload="PRIVATE_WEAK", baseline="B3",
                 prefilled_attempts=None):
    report = mc.McReport(
        begin={"abi": mc.ABI_VERSION, "hart_count": harts, "workload": workload,
               "baseline": baseline, "samples": 6},
        end={"samples": 6, "failures": 0, "status": 0},
    )
    ops = mc.operations_per_hart(harts, workload)
    distinct = mc.distinct_pages(harts, workload)
    initial = baseline in ("B0", "B1")
    dirty = 128 if initial else distinct
    logs = distinct if baseline == "B3" else 0
    bits = mc.bitmap(dirty)
    for sample_id in range(6):
        attempts_this_sample = (prefilled_attempts[sample_id]
                                if isinstance(prefilled_attempts, list)
                                else prefilled_attempts)
        if workload == "PREFILLED_SAME_PTE" and attempts_this_sample is None:
            attempts_this_sample = harts
        warmup, repetition = (1, 0) if sample_id == 0 else (0, sample_id - 1)
        records = []
        for hart in range(harts):
            delta = 0
            if baseline == "B3":
                delta = 1 if mc.shared_pte_workload(workload) and hart == 0 else (0 if mc.shared_pte_workload(workload) else ops)
            d = distinct if not initial and hart == 0 else 0
            appends = distinct if baseline == "B3" and hart == 0 else 0
            attempts = (int(hart < attempts_this_sample)
                        if workload == "PREFILLED_SAME_PTE" else
                        (distinct if not initial and hart == 0 else 0))
            retries = int(workload == "PREFILLED_SAME_PTE" and
                          0 < hart < attempts_this_sample)
            tail_writes = int(workload == "PREFILLED_SAME_PTE" and
                              baseline == "B3" and retries)
            record = {
                "sample": sample_id, "hart": hart, "warmup": warmup,
                "repetition": repetition, "cycle_start": 1000 + sample_id * 100 + hart,
                "cycle_end": 1050 + sample_id * 100 + hart, "workload_cycles": 50,
                "instret_start": 2000,
                "instret_end": 2000 + 5 * ops + 5,
                "workload_instret": 5 * ops + 5,
                "operations": ops, "idx_before": 0, "idx_after": delta,
                "idx_delta": delta, "expected_idx_delta": delta,
                "valid_log_entries": delta, "missing": 0, "extra": 0,
                "duplicates": 0, "tail_writes": tail_writes,
                "tail_slot": 0 if tail_writes else (1 << 64) - 1,
                "tail_value": mc.TRACKED_GPA if tail_writes else 0,
                "tail_errors": 0, "data_errors": 0,
                "control_errors": 0, "d_transitions": d,
                "committed_appends": appends, "pte_cas_attempts": attempts,
                "cas_retries": retries, "scause": 10, "sepc": 0x34,
                "stval": 0, "htval": 0, "done": 1, "status": 0,
            }
            records.append(record); report.harts.append(record)
        starts = [int(row["cycle_start"]) for row in records]
        ends = [int(row["cycle_end"]) for row in records]
        report.samples.append({
            "sample": sample_id, "hart_count": harts, "workload": workload,
            "baseline": baseline, "warmup": warmup, "repetition": repetition,
            "total_operations": ops * harts, "max_local_cycles": 50,
            "absolute_start_min": min(starts), "absolute_end_max": max(ends),
            "completion_cycles": 50,
            "distinct_dirty_pages": distinct, "expected_dirty_pages": dirty,
            "actual_dirty_pages": dirty, "expected_log_entries": logs,
            "actual_log_entries": logs, "expected_pte_bitmap0": bits[0],
            "expected_pte_bitmap1": bits[1], "actual_pte_bitmap0": bits[0],
            "actual_pte_bitmap1": bits[1], "missing": 0, "extra": 0,
            "expected_log_bitmap0": mc.bitmap(logs)[0],
            "expected_log_bitmap1": mc.bitmap(logs)[1],
            "actual_log_bitmap0": mc.bitmap(logs)[0],
            "actual_log_bitmap1": mc.bitmap(logs)[1],
            "winner_hart": (0 if baseline in ("B2", "B3") and mc.shared_pte_workload(workload)
                             else (1 << 64) - 1),
            "duplicates": 0, "initial_pte_errors": 0, "pte_errors": 0,
            "tail_writes": ((attempts_this_sample - 1)
                            if workload == "PREFILLED_SAME_PTE" and baseline == "B3"
                            else 0),
            "data_errors": 0, "buffer_errors": 0, "control_errors": 0,
            "d_transitions": distinct if not initial else 0,
            "committed_appends": logs,
            "pte_cas_attempts": (attempts_this_sample
                                 if workload == "PREFILLED_SAME_PTE"
                                 else (distinct if not initial else 0)),
            "cas_retries": (attempts_this_sample - 1
                            if workload == "PREFILLED_SAME_PTE" else 0),
            "status": 0,
        })
    return report


def trace_for(report, start=0x40, end=0x80, same_loser=False):
    lines = []
    harts, workload, baseline = report.hart_count, report.workload, report.baseline
    assert harts and workload and baseline
    distinct = mc.distinct_pages(harts, workload)
    ops = mc.operations_per_hart(harts, workload)
    attempt = 1
    for sample in range(6):
        for hart in range(harts):
            lines.append(f"rv commit {hart} {EPOCH_START:016x} 00000013")
            lines.append(f"rv commit {hart} {start:016x} 00000013")
            pages = []
            if baseline in ("B2", "B3"):
                if mc.shared_pte_workload(workload): pages = [0] if hart == 0 else []
                else: pages = list(range(hart * ops, hart * ops + ops))
            if workload == "PREFILLED_SAME_PTE" and baseline == "B3":
                row = next(item for item in report.harts
                           if item["sample"] == sample and item["hart"] == hart)
                if not row["pte_cas_attempts"]:
                    lines.append(f"rv commit {hart} {end:016x} 00000013")
                    lines.append(f"rv commit {hart} {EPOCH_END:016x} 00000013")
                    continue
                address = mc.LOG_BASE + hart * mc.HART_STRIDE
                data = mc.TRACKED_GPA
                terminal = "committed" if row["d_transitions"] else "superseded"
                lines.append(f"rv mmu physical-store {hart} 1 {attempt} 10 {address:016x} 8 {data:016x} 0 pending")
                lines.append(f"rv mmu physical-store {hart} 1 {attempt} 11 {address:016x} 8 {data:016x} 0 {terminal}")
                if terminal == "committed":
                    lines.append(f"rv mmu store {hart} {address:016x} 8 {data:016x} 0")
                attempt += 1
            if baseline == "B3":
                for slot, page in enumerate(pages if workload != "PREFILLED_SAME_PTE" else []):
                    address = mc.LOG_BASE + hart * mc.HART_STRIDE + slot * 8
                    data = mc.TRACKED_GPA + page * 4096
                    lines.append(f"rv mmu physical-store {hart} 1 {attempt} 10 {address:016x} 8 {data:016x} 0 pending")
                    lines.append(f"rv mmu physical-store {hart} 1 {attempt} 11 {address:016x} 8 {data:016x} 0 committed")
                    lines.append(f"rv mmu store {hart} {address:016x} 8 {data:016x} 0")
                    attempt += 1
            for page in pages:
                address = mc.PTE_BASE + page * 8
                data = (((mc.TRACKED_PHYSICAL + page * 4096) >> 12) << 10) | mc.PTE_DIRTY_FLAGS
                lines.append(f"rv mmu store {hart} {address:016x} 8 {data:016x} 0")
            if same_loser and workload == "SAME_PTE" and baseline == "B3" and hart == 1:
                address = mc.LOG_BASE + hart * mc.HART_STRIDE
                data = mc.TRACKED_GPA
                lines.append(f"rv mmu physical-store {hart} 2 {attempt} 10 {address:016x} 8 {data:016x} 0 pending")
                lines.append(f"rv mmu physical-store {hart} 2 {attempt} 11 {address:016x} 8 {data:016x} 0 superseded")
                attempt += 1
            lines.append(f"rv commit {hart} {end:016x} 00000013")
            lines.append(f"rv commit {hart} {EPOCH_END:016x} 00000013")
    return lines


def render_report(report):
    def fields(record):
        return " ".join(f"{key}={value}" for key, value in record.items())
    lines = [mc.PREFIX + "_BEGIN " + fields(report.begin)]
    for sample in report.samples:
        lines.append(mc.PREFIX + "_SAMPLE " + fields(sample))
        for hart in sorted((row for row in report.harts if row["sample"] == sample["sample"]), key=lambda row: row["hart"]):
            lines.append(mc.PREFIX + "_HART " + fields(hart))
    lines.append(mc.PREFIX + "_END " + fields(report.end))
    return "\n".join(lines) + "\n"


class McReportTest(unittest.TestCase):
    def test_abi_v1_and_wrong_instret_are_rejected(self):
        for field, value in (("abi", 1), ("workload_instret", 9)):
            report = valid_report(2, "SAME_PTE", "B3")
            (report.begin if field == "abi" else report.harts[0])[field] = value
            with self.assertRaises(mc.ReportError):
                report.validate(2, "SAME_PTE", "B3")

    def test_same_pte_old_hpm_trace_contradiction_is_rejected(self):
        report = valid_report(2, "SAME_PTE", "B3")
        # Phase-1 minimal: physical loser/tail present but loser HPM says no attempt.
        for sample in range(6):
            row = next(r for r in report.harts if r["sample"] == sample and r["hart"] == 1)
            row.update(tail_writes=1, tail_slot=0, tail_value=mc.TRACKED_GPA)
            report.samples[sample]["tail_writes"] = 1
        with self.assertRaises(mc.ReportError):
            report.validate(2, "SAME_PTE", "B3")

    def test_hs_epoch_accepts_events_before_timed_retirement(self):
        report = valid_report(2, "SAME_PTE", "B3")
        report.validate(2, "SAME_PTE", "B3")
        lines = trace_for(report)
        # Move one pending event before timed_start, but keep it in the HS epoch.
        pending = lines.pop(2)
        lines.insert(1, pending)
        result = mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        self.assertEqual(result["outside_timed_events"], 1)
        lines.pop(1); lines.insert(0, pending)
        with self.assertRaises(mc.DiagnosticIncomplete):
            mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)

    def test_lifecycle_negative_evidence(self):
        report = valid_report(2, "SAME_PTE", "B3")
        report.validate(2, "SAME_PTE", "B3")
        for mutation in ("duplicate-terminal", "foreign-hart", "missing-completion", "reserved-bit", "malformed"):
            lines = trace_for(report)
            with self.subTest(mutation=mutation), self.assertRaises(mc.ReportError):
                if mutation == "duplicate-terminal": lines.insert(4, lines[3])
                elif mutation == "foreign-hart": lines[2] = lines[2].replace("physical-store 0", "physical-store 2")
                elif mutation == "missing-completion": lines = [l for l in lines if f"{EPOCH_END:016x}" not in l]
                elif mutation == "reserved-bit": lines[2] = lines[2].replace(f"{mc.TRACKED_GPA:016x}", f"{mc.TRACKED_GPA + 1:016x}")
                else: lines.append("rv mmu physical-store malformed")
                mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)

    def test_known_terminal_keeps_original_hs_epoch(self):
        report = valid_report(2, "SAME_PTE", "B3")
        report.validate(2, "SAME_PTE", "B3")
        lines = trace_for(report)
        terminal = lines.pop(3)
        end = next(i for i, line in enumerate(lines) if f"{EPOCH_END:016x}" in line)
        lines.insert(end + 1, terminal)
        result = mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        self.assertEqual(result["totals"]["committed"], 6)
        self.assertEqual(result["outside_timed_events"], 1)

    def test_shared_pte_store_owner_must_match_hpm(self):
        report = valid_report(2, "SAME_PTE", "B2")
        report.validate(2, "SAME_PTE", "B2")
        lines = trace_for(report)
        # Put the PTE store inside hart 1's valid epoch, leaving HPM winner 0.
        store = lines.pop(2).replace("rv mmu store 0", "rv mmu store 1")
        next_start = next(i for i, l in enumerate(lines) if l.startswith("rv commit 1"))
        lines.insert(next_start + 2, store)
        with self.assertRaisesRegex(mc.ReportError, "owner"):
            mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)

    def test_uart_parser_preserves_strict_sample_hart_order(self):
        expected = valid_report(4, "SAME_PTE", "B2")
        parsed = mc.parse_lines(io.StringIO(render_report(expected)))
        parsed.validate(4, "SAME_PTE", "B2")
        parsed.record_order[1], parsed.record_order[2] = parsed.record_order[2], parsed.record_order[1]
        with self.assertRaises(mc.ReportError): parsed.validate(4, "SAME_PTE", "B2")

    def test_all_architectural_selections(self):
        for harts in (1, 2, 4):
            for workload in mc.WORKLOADS[:3]:
                for baseline in mc.BASELINES:
                    with self.subTest(harts=harts, workload=workload, baseline=baseline):
                        report = valid_report(harts, workload, baseline)
                        report.validate(harts, workload, baseline)

    def test_prefilled_same_pte_accepts_observed_participation(self):
        for harts in (2, 4):
            for baseline in ("B2", "B3"):
                for attempts in range(1, harts + 1):
                    with self.subTest(harts=harts, baseline=baseline,
                                      attempts=attempts):
                        report = valid_report(harts, "PREFILLED_SAME_PTE",
                                              baseline, attempts)
                        report.validate(harts, "PREFILLED_SAME_PTE", baseline)
                        trace = mc.check_trace(iter(trace_for(report)), report,
                                               0x40, 0x80, EPOCH_START, EPOCH_END)
                        self.assertEqual(trace["totals"]["physical_attempts"],
                                         6 * attempts if baseline == "B3" else 0)
                        self.assertEqual(trace["totals"]["committed"],
                                         6 if baseline == "B3" else 0)
                        self.assertEqual(trace["totals"]["superseded"],
                                         6 * (attempts - 1) if baseline == "B3" else 0)
                        self.assertEqual(trace["totals"]["architectural_stores"],
                                         12 if baseline == "B3" else 6)

    def test_prefilled_same_pte_accepts_mixed_sample_participation(self):
        report = valid_report(4, "PREFILLED_SAME_PTE", "B3",
                              [1, 2, 3, 4, 1, 4])
        report.validate(4, "PREFILLED_SAME_PTE", "B3")
        trace = mc.check_trace(iter(trace_for(report)), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        self.assertEqual([item["cas_attempts"] for item in trace["samples"]],
                         [1, 2, 3, 4, 1, 4])
        self.assertEqual(trace["samples"][0]["observer_harts"], [1, 2, 3])

    def test_prefilled_same_pte_rejects_invalid_selection_and_roles(self):
        with self.assertRaises(mc.ReportError):
            valid_report(1, "PREFILLED_SAME_PTE", "B3").validate(
                1, "PREFILLED_SAME_PTE", "B3")
        with self.assertRaises(mc.ReportError):
            valid_report(2, "PREFILLED_SAME_PTE", "B1").validate(
                2, "PREFILLED_SAME_PTE", "B1")
        report = valid_report(4, "PREFILLED_SAME_PTE", "B3", 2)
        loser = next(row for row in report.harts
                     if row["sample"] == 0 and row["hart"] == 1)
        loser["cas_retries"] = 0
        with self.assertRaises(mc.ReportError):
            report.validate(4, "PREFILLED_SAME_PTE", "B3")

    def test_rejects_missing_hart_and_oracle_errors(self):
        report = valid_report(); report.harts.pop()
        with self.assertRaises(mc.ReportError): report.validate(2, "PRIVATE_WEAK", "B3")
        report = valid_report(); report.samples[2]["pte_errors"] = 1
        with self.assertRaises(mc.ReportError): report.validate(2, "PRIVATE_WEAK", "B3")
        report = valid_report(); report.harts[0]["idx_delta"] = 31
        with self.assertRaises(mc.ReportError): report.validate(2, "PRIVATE_WEAK", "B3")

    def test_private_trace_lifecycle_and_architectural_stream(self):
        report = valid_report(2, "PRIVATE_WEAK", "B3"); report.validate(2, "PRIVATE_WEAK", "B3")
        result = mc.check_trace(iter(trace_for(report)), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        self.assertEqual(result["totals"]["committed"], 6 * 64)
        self.assertEqual(result["totals"]["architectural_stores"], 6 * 128)

    def test_all_noncontended_trace_paths(self):
        for harts in (1, 2, 4):
            for workload in mc.WORKLOADS[:3]:
                for baseline in mc.BASELINES:
                    with self.subTest(harts=harts, workload=workload, baseline=baseline):
                        report = valid_report(harts, workload, baseline)
                        report.validate(harts, workload, baseline)
                        result = mc.check_trace(iter(trace_for(report)), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
                        self.assertEqual(result["status"], "PASS")

    def test_same_pte_superseded_requires_exact_tail(self):
        report = valid_report(2, "SAME_PTE", "B3")
        for sample in range(6):
            row = next(item for item in report.harts if item["sample"] == sample and item["hart"] == 1)
            row.update(tail_writes=1, tail_slot=0, tail_value=mc.TRACKED_GPA,
                       pte_cas_attempts=1, cas_retries=1)
            report.samples[sample]["tail_writes"] = 1
            report.samples[sample].update(pte_cas_attempts=2, cas_retries=1)
        report.validate(2, "SAME_PTE", "B3")
        result = mc.check_trace(iter(trace_for(report, same_loser=True)), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        self.assertEqual(result["totals"]["superseded"], 6)
        broken = trace_for(report, same_loser=True)
        broken = [line.replace(f"{mc.TRACKED_GPA:016x} 0 superseded", "0000000000020000 0 superseded") if "superseded" in line else line for line in broken]
        with self.assertRaises(mc.ReportError): mc.check_trace(iter(broken), report, 0x40, 0x80, EPOCH_START, EPOCH_END)

    def test_trace_rejects_open_lifecycle_and_failure_marker(self):
        report = valid_report(1, "PRIVATE_WEAK", "B3"); report.validate(1, "PRIVATE_WEAK", "B3")
        lines = trace_for(report)
        lines.pop(next(index for index, line in enumerate(lines) if line.endswith(" committed")))
        with self.assertRaises(mc.ReportError): mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        lines = trace_for(report); lines.append("RVLS attribution error")
        with self.assertRaises(mc.ReportError): mc.check_trace(iter(lines), report, 0x40, 0x80, EPOCH_START, EPOCH_END)

    def test_writes_raw_json_csv_and_trace_report(self):
        report = valid_report(1, "PRIVATE_WEAK", "B0"); report.validate(1, "PRIVATE_WEAK", "B0")
        trace = mc.check_trace(iter(trace_for(report)), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary); mc.write_outputs(report, path, trace)
            self.assertTrue((path / "samples.json").is_file())
            self.assertTrue((path / "samples.csv").is_file())
            self.assertTrue((path / "trace-report.json").is_file())


if __name__ == "__main__":
    unittest.main()
