import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "perf_report.py"
SPEC = importlib.util.spec_from_file_location("perf_report", MODULE_PATH)
perf_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(perf_report)


def record(prefix, **fields):
    encoded = " ".join(
        f"{key}=0x{value:x}" if isinstance(value, int) else f"{key}={value}"
        for key, value in fields.items()
    )
    return f"{prefix} {encoded}\n"


def make_log(path, cpus=2, observers=True, bad_status=False, hpm=False,
             hpm_available=0xF, hpm_event_mask=0xF, hpm_time_running=100):
    lines = [record(
        "SHDLT_PERF_RUN", profile="baseline", cache="coherent_l1", seed=2,
        ready="1.01", latency=0,
    )]
    lines.append(record(
        "SHDLT_PERF_META", abi_version=1, cpus=cpus, suite=0, logger=1,
        order=0, phase_mode=1 if cpus > 1 else 0, scaling=0, warmup=5,
        measured=63,
    ))
    if hpm:
        lines.append(record(
            "SHDLT_HPM_META", abi_version=1, schema_version=1,
            backend=1, slots=4, event_mask=hpm_event_mask,
            event0=0x30, event1=0x31, event2=0x33, event3=0x34,
        ))
    for sample in range(68):
        for hart in range(cpus):
            if observers:
                lines.append(record(
                    "SHDLT_PERF_OBSERVER", case=0, sample=sample, phase=sample,
                    hart=hart, available_mask=0x3F, valid_mask=0x17,
                    first_d_update_cycles=20 + sample,
                    fault_detection_cycles=0, recovery_cycles=0,
                    retry_store_cycles=0, drain_cycles=0, store_issue=64,
                    store_commit=64, tlb_hit=0, tlb_miss=64, tlb_refill=64,
                    log_write=64, cas_attempt=64, cas_mismatch=0, cas_redo=hart,
                    cas_success=64, coherence_retry_count=hart, acquire=1,
                    probe=0, release=0, writeback=0, grant=1, grant_ack=1,
                    stall_a=0, stall_b=0, stall_c=0, stall_d=0, stall_e=0,
                    append_cycles_count=64, append_cycles_sum=640,
                    cas_attempt_cycles_count=64, cas_attempt_cycles_sum=1280,
                    cas_transaction_cycles_count=64,
                    cas_transaction_cycles_sum=1344,
                    store_to_log_cycles_count=64, store_to_log_cycles_sum=320,
                    log_to_cas_cycles_count=64, log_to_cas_cycles_sum=192,
                ))
            lines.append(record(
                "SHDLT_PERF_SAMPLE", abi_version=1, case=0, sample=sample,
                warmup=int(sample < 5), hart=hart, hart_mask=(1 << cpus) - 1,
                cpus=cpus, logger=1, order=0,
                phase_mode=1 if cpus > 1 else 0, scaling=0, pages=64,
                stores=1024, entries=64, faults=0,
                status=1 if bad_status and sample == 7 and hart == 0 else 0,
                cycles=1000 + sample + hart, instret=500 + sample,
                first_touch_cycles=200, first_touch_instret=100,
                steady_cycles=800 + sample + hart, guest_cycles=1000 + sample,
                service_cycles=0, freeze_cycles=0, drain_cycles=0,
                freeze_total_cycles=0, recovery_cycles=0,
                end_to_end_cycles=1100 + sample, expected_entries=64,
                unique=64, duplicates=0, missing=0, extra=0, data_errors=0,
                pte_errors=0, unexpected_traps=0, initial_index=0,
                final_index=64, observer_available_mask=0,
                observer_valid_mask=0,
            ))
            if hpm:
                lines.append(record(
                    "SHDLT_HPM_SAMPLE", abi_version=1, schema_version=1,
                    case=0, sample=sample, hart=hart, group=0,
                    event_mask=hpm_event_mask, available_mask=hpm_available,
                    time_enabled=120, time_running=hpm_time_running,
                    event0=0x30, value0=sample + 1,
                    event1=0x31, value1=sample + 2,
                    event2=0x33, value2=sample + 3,
                    event3=0x34, value3=sample + 4, status=0,
                ))
    lines.append(record(
        "SHDLT_PERF_RESULT", abi_version=1, cpus=cpus,
        failures=1 if bad_status else 0, status=1 if bad_status else 0,
    ))
    path.write_text("".join(lines), encoding="utf-8")


class PerfReportTest(unittest.TestCase):
    def test_robust_statistics_for_63_samples(self):
        values = list(range(1, 64))
        summary = perf_report.summarize(values)
        self.assertEqual(summary["count"], 63)
        self.assertEqual(summary["median"], 32)
        self.assertEqual(summary["p95"], 60)
        self.assertEqual(summary["mad"], 16)

    def test_strict_log_and_observer_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path)
            parsed = perf_report.load_log(path, require_observer=True)
            self.assertEqual(len(parsed["rows"]), 136)
            measured = [row for row in parsed["rows"] if row["warmup"] == 0]
            self.assertEqual(len(measured), 126)
            self.assertEqual(measured[0]["dirty_log_append_cycles"], 10)
            self.assertEqual(measured[1]["coherence_retry_count"], 1)
            summary = perf_report.aggregate([parsed])
            self.assertEqual(summary[0]["cycles"]["count"], 126)

    def test_missing_observer_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False)
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_observer=True)

    def test_firmware_failure_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, bad_status=True)
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path)

    def test_baseline_threshold(self):
        key_values = {
            key: value for key, value in zip(
                perf_report.CONFIG_KEYS,
                ("baseline", "l1", 2, 1, 0, 1, 0, 1, 0, 0, 0, 0, "off"),
            )
        }
        old = dict(key_values)
        new = dict(key_values)
        for metric in perf_report.GATE_METRICS:
            old[metric] = {"count": 63, "median": 100, "p95": 120}
            new[metric] = {"count": 63, "median": 111, "p95": 120}
        baseline = {"schema_version": 1, "summaries": [old]}
        current = {"schema_version": 1, "summaries": [new]}
        regressions = perf_report.compare_baseline(current, baseline, 10.0)
        self.assertTrue(any("median" in item for item in regressions))

    def test_architecture_only_does_not_require_hpm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=False)
            parsed = perf_report.load_log(path)
            self.assertFalse(parsed["hpm_enabled"])
            self.assertEqual(len(parsed["rows"]), 136)

    def test_complete_hpm_records_are_merged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=True)
            parsed = perf_report.load_log(path, require_hpm=True)
            self.assertTrue(parsed["hpm_enabled"])
            measured = [row for row in parsed["rows"] if row["warmup"] == 0]
            self.assertEqual(measured[0]["hpm_shdlt_d_transition"], 6)
            self.assertEqual(measured[0]["hpm_shdlt_log_append"], 7)
            summary = perf_report.aggregate([parsed])[0]
            self.assertEqual(summary["hpm_shdlt_d_transition"]["count"], 126)

    def test_require_hpm_rejects_missing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=False)
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)

    def test_hpm_mask_and_runtime_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=True, hpm_available=0x8)
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)
            path2 = Path(directory) / "runtime.log"
            make_log(path2, observers=False, hpm=True, hpm_time_running=0)
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path2, require_hpm=True)

    def test_optional_hpm_unavailable_is_explicit_not_zero_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unavailable.log"
            make_log(path, observers=False, hpm=True,
                     hpm_available=0, hpm_time_running=0)
            parsed = perf_report.load_log(path, require_hpm=False)
            self.assertTrue(parsed["hpm_enabled"])
            self.assertTrue(all(row["hpm_available_mask"] == 0
                                for row in parsed["rows"]))
            self.assertTrue(all(
                "hpm_shdlt_d_transition" not in row
                for row in parsed["rows"]))
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)

    def test_optional_hpm_partial_group_is_accepted_with_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.log"
            make_log(path, observers=False, hpm=True,
                     hpm_available=0x3, hpm_time_running=100)
            parsed = perf_report.load_log(path, require_hpm=False)
            self.assertEqual(parsed["rows"][0]["hpm_available_mask"], 0x3)
            self.assertIn("hpm_shdlt_d_transition", parsed["rows"][0])
            self.assertNotIn("hpm_shdlt_pte_cas_retry", parsed["rows"][0])
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)

    def test_hpm_duplicate_or_mismatched_key_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=True)
            original = path.read_text(encoding="utf-8")
            duplicate = next(line for line in original.splitlines(True)
                             if line.startswith("SHDLT_HPM_SAMPLE "))
            path.write_text(original + duplicate, encoding="utf-8")
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)

    def test_hpm_duplicate_metadata_event_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=True)
            text = path.read_text(encoding="utf-8").replace(
                "event1=0x31", "event1=0x30", 1)
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)

    def test_hpm_event_group_is_part_of_configuration_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.log"
            second = Path(directory) / "second.log"
            make_log(first, observers=False, hpm=True)
            text = first.read_text(encoding="utf-8")
            # Change both metadata and samples so the second stream remains a
            # valid group, but represents a different event in slot 1.
            text = text.replace("event1=0x31", "event1=0x36")
            second.write_text(text, encoding="utf-8")
            left = perf_report.load_log(first, require_hpm=True)
            right = perf_report.load_log(second, require_hpm=True)
            self.assertNotEqual(
                perf_report.config_key(left["rows"][0]),
                perf_report.config_key(right["rows"][0]),
            )

    def test_hpm_unknown_backend_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            make_log(path, observers=False, hpm=True)
            text = path.read_text(encoding="utf-8").replace(
                "backend=0x1", "backend=0x7", 1)
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(perf_report.ReportError):
                perf_report.load_log(path, require_hpm=True)


if __name__ == "__main__":
    unittest.main()
