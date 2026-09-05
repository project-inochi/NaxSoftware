import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import dirtygen_perf_report


UNIQUE_PAGES = (1, 8, 32, 128)
REPEAT_OPERATIONS = (1, 8, 128, 4096)


def bitmap(pages):
    first = (1 << min(pages, 64)) - 1 if pages else 0
    second_pages = max(0, pages - 64)
    second = (1 << second_pages) - 1 if second_pages else 0
    return first, second


def expected_fields(config):
    pattern_id = config // 16
    size_index = (config // 4) & 3
    baseline_id = config & 3
    pages = 1 if pattern_id else UNIQUE_PAGES[size_index]
    operations = REPEAT_OPERATIONS[size_index] if pattern_id else pages
    initial_d = int(baseline_id < 2)
    dirty_pages = 128 if initial_d else pages
    log_entries = pages if baseline_id == 3 else 0
    pte = bitmap(dirty_pages)
    log = bitmap(log_entries)
    return {
        "baseline": f"B{baseline_id}",
        "pattern": "REPEAT" if pattern_id else "UNIQUE",
        "pages": pages,
        "operations": operations,
        "buffer_capacity": 512,
        "logger_enabled": baseline_id & 1,
        "initial_d": initial_d,
        "expected_cause": 10,
        "actual_cause": 10,
        "expected_dirty_pages": dirty_pages,
        "actual_dirty_pages": dirty_pages,
        "expected_d_transitions": 0 if initial_d else pages,
        "actual_d_transitions": 0 if initial_d else pages,
        "expected_log_entries": log_entries,
        "idx_before": 0,
        "idx_after": log_entries,
        "valid_log_entries": log_entries,
        "unique": log_entries,
        "missing": 0,
        "extra": 0,
        "duplicates": 0,
        "expected_pte_bitmap0": pte[0],
        "expected_pte_bitmap1": pte[1],
        "actual_pte_bitmap0": pte[0],
        "actual_pte_bitmap1": pte[1],
        "expected_log_bitmap0": log[0],
        "expected_log_bitmap1": log[1],
        "actual_log_bitmap0": log[0],
        "actual_log_bitmap1": log[1],
    }


def sample(config, warmup, repetition):
    row = {
        "config": config,
        "warmup": warmup,
        "repetition": repetition,
    }
    row.update(expected_fields(config))
    row.update(
        {
            "workload_cycles": 100 + config + repetition,
            "workload_instret": 50 + repetition,
            "prepare_cycles": 200 + repetition,
            "collect_cycles": 30 + repetition,
            "epoch_cycles": 400 + repetition,
            "initial_pte_errors": 0,
            "pte_errors": 0,
            "pte_missing": 0,
            "pte_extra": 0,
            "data_errors": 0,
            "buffer_errors": 0,
            "control_errors": 0,
            "unexpected_traps": 0,
            "status": 0,
        }
    )
    return row


def record(prefix, fields):
    tokens = []
    for key, value in fields.items():
        tokens.append(
            f"{key}=0x{value:x}" if isinstance(value, int) else f"{key}={value}"
        )
    return f"{prefix} {' '.join(tokens)}\n"


def valid_log(suite):
    configs = (
        range(32)
        if suite == "full"
        else (*range(4, 8), *range(24, 28))
    )
    configs = tuple(configs)
    rows = []
    for config in configs:
        rows.append(sample(config, 1, 0))
        for repetition in range(5):
            rows.append(sample(config, 0, repetition))
    lines = ["unrelated Mill output\n"]
    lines.append(
        record(
            "SHDLT_DIRTYGEN_PERF_BEGIN",
            {"abi": 1, "configs": len(configs), "samples": len(rows)},
        )
    )
    lines.extend(record("SHDLT_DIRTYGEN_PERF_SAMPLE", row) for row in rows)
    lines.append(
        record(
            "SHDLT_DIRTYGEN_PERF_END",
            {
                "configs": len(configs),
                "samples": len(rows),
                "failures": 0,
                "status": 0,
            },
        )
    )
    return "".join(lines)


def parse_valid(suite="smoke"):
    report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log(suite)))
    report.validate(suite)
    return report


class DirtygenPerfReportTest(unittest.TestCase):
    def test_valid_smoke_report(self):
        report = parse_valid("smoke")
        self.assertEqual(len(report.samples), 48)
        self.assertEqual(len(report.measured_samples()), 40)

    def test_valid_full_report(self):
        report = parse_valid("full")
        self.assertEqual(len(report.samples), 192)
        self.assertEqual(len(report.measured_samples()), 160)

    def test_missing_and_duplicate_samples_are_rejected(self):
        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples.pop()
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "expected 48"):
            report.validate("smoke")

        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[-1] = dict(report.samples[0])
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "duplicate sample key"):
            report.validate("smoke")

    def test_invalid_warmup_key_is_rejected(self):
        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[0]["warmup"] = 2
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "invalid sample key"):
            report.validate("smoke")

    def test_wrong_config_mapping_is_rejected(self):
        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[0]["baseline"] = "B1"
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "baseline"):
            report.validate("smoke")

        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[0]["operations"] = 9
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "operations"):
            report.validate("smoke")

    def test_wrong_cause_pte_and_log_oracles_are_rejected(self):
        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[0]["actual_cause"] = 23
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "actual_cause"):
            report.validate("smoke")

        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[0]["actual_pte_bitmap0"] ^= 1
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "actual_pte_bitmap0"):
            report.validate("smoke")

        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        b3 = next(row for row in report.samples if row["config"] == 7)
        b3["idx_after"] = 0
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "idx_after"):
            report.validate("smoke")

    def test_nonzero_error_and_bad_end_are_rejected(self):
        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.samples[0]["buffer_errors"] = 1
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "buffer_errors"):
            report.validate("smoke")

        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        report.end["failures"] = 1
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "END failures"):
            report.validate("smoke")

    def test_cycles_are_not_correctness_predicates(self):
        report = dirtygen_perf_report.parse_lines(io.StringIO(valid_log("smoke")))
        for row in report.samples:
            for metric in dirtygen_perf_report.TIME_METRICS:
                row[metric] = 0
        report.validate("smoke")

    def test_firmware_error_record_is_rejected(self):
        text = valid_log("smoke") + record(
            "SHDLT_DIRTYGEN_PERF_ERROR",
            {"config": 4, "scause": 23},
        )
        report = dirtygen_perf_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(dirtygen_perf_report.ReportError, "firmware emitted"):
            report.validate("smoke")

    def test_outputs_include_raw_and_measured_summary(self):
        report = parse_valid("smoke")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            dirtygen_perf_report.write_outputs(report, output)
            samples = json.loads((output / "samples.json").read_text())
            summary = json.loads((output / "summary.json").read_text())
            with (output / "samples.csv").open(newline="") as stream:
                csv_rows = list(csv.DictReader(stream))
            self.assertEqual(len(samples["samples"]), 48)
            self.assertEqual(len(csv_rows), 48)
            self.assertEqual(len(summary["configs"]), 8)
            self.assertTrue(summary["warmup_samples_excluded"])
            self.assertEqual(
                summary["configs"][0]["workload_cycles"]["count"], 5
            )
            self.assertEqual(
                summary["configs"][0]["workload_cycles"]["median"], 106
            )


if __name__ == "__main__":
    unittest.main()
