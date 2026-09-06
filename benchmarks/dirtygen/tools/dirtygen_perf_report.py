#!/usr/bin/env python3
"""Strict validator and raw/summary exporter for dirtygen_perf ABI v1."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


PREFIX = "SHDLT_DIRTYGEN_PERF"
ABI_VERSION = 1
RUNS_PER_CONFIG = 6
MEASURED_REPETITIONS = 5
BUFFER_CAPACITY = 512
FULL_CONFIGS = tuple(range(32))
SMOKE_CONFIGS = tuple(range(4, 8)) + tuple(range(24, 28))
SENSITIVITY_CONFIGS = tuple(range(12, 16)) + tuple(range(28, 32))
SUITE_CONFIGS = {
    "full": FULL_CONFIGS,
    "smoke": SMOKE_CONFIGS,
    "sensitivity": SENSITIVITY_CONFIGS,
}
SUITES = (*SUITE_CONFIGS, "isolated")
SCHEDULE_BASELINES = {
    "legacy": (0, 1, 2, 3),
    "S0": (0, 1, 3, 2),
    "S1": (1, 2, 0, 3),
    "S2": (2, 3, 1, 0),
    "S3": (3, 0, 2, 1),
}
UNIQUE_PAGES = (1, 8, 32, 128)
REPEAT_OPERATIONS = (1, 8, 128, 4096)
TIME_METRICS = (
    "workload_cycles",
    "workload_instret",
    "prepare_cycles",
    "collect_cycles",
    "epoch_cycles",
)
ERROR_FIELDS = (
    "initial_pte_errors",
    "pte_errors",
    "pte_missing",
    "pte_extra",
    "data_errors",
    "buffer_errors",
    "control_errors",
    "unexpected_traps",
    "status",
)
SAMPLE_FIELDS = (
    "config",
    "warmup",
    "repetition",
    "baseline",
    "pattern",
    "pages",
    "operations",
    "buffer_capacity",
    "logger_enabled",
    "initial_d",
    "workload_cycles",
    "workload_instret",
    "prepare_cycles",
    "collect_cycles",
    "epoch_cycles",
    "expected_cause",
    "actual_cause",
    "expected_dirty_pages",
    "actual_dirty_pages",
    "expected_d_transitions",
    "actual_d_transitions",
    "expected_log_entries",
    "idx_before",
    "idx_after",
    "valid_log_entries",
    "unique",
    "missing",
    "extra",
    "duplicates",
    "expected_pte_bitmap0",
    "expected_pte_bitmap1",
    "actual_pte_bitmap0",
    "actual_pte_bitmap1",
    "expected_log_bitmap0",
    "expected_log_bitmap1",
    "actual_log_bitmap0",
    "actual_log_bitmap1",
) + ERROR_FIELDS
STRING_FIELDS = {"baseline", "pattern"}


class ReportError(RuntimeError):
    pass


def parse_value(value: str) -> int | str:
    try:
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError:
        return value


def parse_fields(tokens: list[str], kind: str) -> dict[str, int | str]:
    result: dict[str, int | str] = {}
    for token in tokens:
        if "=" not in token:
            raise ReportError(f"malformed {kind} token: {token!r}")
        key, value = token.split("=", 1)
        if not key or not value:
            raise ReportError(f"malformed {kind} token: {token!r}")
        if key in result:
            raise ReportError(f"duplicate {kind} field: {key}")
        result[key] = parse_value(value)
    return result


def required_int(record: dict[str, Any], key: str, context: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise ReportError(f"{context} is missing numeric field {key}")
    if value < 0:
        raise ReportError(f"{context} has negative field {key}")
    return value


def require_exact_fields(
    record: dict[str, Any], expected: tuple[str, ...], context: str
) -> None:
    actual = set(record)
    wanted = set(expected)
    missing = sorted(wanted - actual)
    extra = sorted(actual - wanted)
    if missing:
        raise ReportError(f"{context} missing field(s): {', '.join(missing)}")
    if extra:
        raise ReportError(f"{context} has unknown field(s): {', '.join(extra)}")


def bitmap_for_pages(pages: int) -> tuple[int, int]:
    if pages < 0 or pages > 128:
        raise ReportError(f"invalid page count {pages}")
    first = (1 << min(pages, 64)) - 1 if pages else 0
    second_pages = max(0, pages - 64)
    second = (1 << second_pages) - 1 if second_pages else 0
    return first, second


def expected_config(config: int) -> dict[str, int | str | tuple[int, int]]:
    if config < 0 or config >= 32:
        raise ReportError(f"invalid config id {config}")
    pattern_id = config // 16
    size_index = (config // 4) & 3
    baseline_id = config & 3
    pattern = "REPEAT" if pattern_id else "UNIQUE"
    pages = 1 if pattern_id else UNIQUE_PAGES[size_index]
    operations = REPEAT_OPERATIONS[size_index] if pattern_id else pages
    initial_d = int(baseline_id < 2)
    logger_enabled = baseline_id & 1
    dirty_pages = 128 if initial_d else pages
    transitions = 0 if initial_d else pages
    log_entries = pages if baseline_id == 3 else 0
    pte_bitmap = bitmap_for_pages(dirty_pages)
    log_bitmap = bitmap_for_pages(log_entries)
    return {
        "baseline": f"B{baseline_id}",
        "pattern": pattern,
        "pages": pages,
        "operations": operations,
        "buffer_capacity": BUFFER_CAPACITY,
        "logger_enabled": logger_enabled,
        "initial_d": initial_d,
        "expected_cause": 10,
        "actual_cause": 10,
        "expected_dirty_pages": dirty_pages,
        "actual_dirty_pages": dirty_pages,
        "expected_d_transitions": transitions,
        "actual_d_transitions": transitions,
        "expected_log_entries": log_entries,
        "idx_before": 0,
        "idx_after": log_entries,
        "valid_log_entries": log_entries,
        "unique": log_entries,
        "missing": 0,
        "extra": 0,
        "duplicates": 0,
        "expected_pte_bitmap0": pte_bitmap[0],
        "expected_pte_bitmap1": pte_bitmap[1],
        "actual_pte_bitmap0": pte_bitmap[0],
        "actual_pte_bitmap1": pte_bitmap[1],
        "expected_log_bitmap0": log_bitmap[0],
        "expected_log_bitmap1": log_bitmap[1],
        "actual_log_bitmap0": log_bitmap[0],
        "actual_log_bitmap1": log_bitmap[1],
    }


def selected_configs(suite: str, config_id: int | None = None) -> tuple[int, ...]:
    if suite == "isolated":
        if config_id is None:
            raise ReportError("isolated suite requires a config id")
        expected_config(config_id)
        return (config_id,)
    if suite not in SUITE_CONFIGS:
        raise ReportError(f"unknown suite {suite!r}")
    if config_id is not None:
        raise ReportError(f"suite {suite!r} does not accept a config id")
    return SUITE_CONFIGS[suite]


def ordered_configs(
    suite: str, schedule_id: str = "legacy", config_id: int | None = None
) -> tuple[int, ...]:
    enabled_configs = selected_configs(suite, config_id)
    if suite == "isolated":
        if schedule_id != "isolated":
            raise ReportError("isolated suite requires schedule 'isolated'")
        return enabled_configs
    if suite not in SUITE_CONFIGS:
        raise ReportError(f"unknown suite {suite!r}")
    if schedule_id not in SCHEDULE_BASELINES:
        raise ReportError(f"unknown schedule {schedule_id!r}")
    enabled = set(enabled_configs)
    groups = sorted(config // 4 for config in enabled if config % 4 == 0)
    return tuple(
        group * 4 + baseline
        for group in groups
        for baseline in SCHEDULE_BASELINES[schedule_id]
        if group * 4 + baseline in enabled
    )


@dataclass
class DirtygenPerfReport:
    begin: dict[str, int | str] | None = None
    samples: list[dict[str, int | str]] = field(default_factory=list)
    end: dict[str, int | str] | None = None
    errors: list[dict[str, int | str]] = field(default_factory=list)
    suite: str | None = None
    schedule_id: str | None = None
    config_id: int | None = None

    def validate(
        self, suite: str, schedule_id: str = "legacy",
        config_id: int | None = None,
    ) -> None:
        expected_order = ordered_configs(suite, schedule_id, config_id)
        expected_configs = selected_configs(suite, config_id)
        expected_count = len(expected_configs) * RUNS_PER_CONFIG
        if self.begin is None:
            raise ReportError(f"missing {PREFIX}_BEGIN")
        if self.end is None:
            raise ReportError(f"missing {PREFIX}_END")
        if self.errors:
            raise ReportError(f"firmware emitted {PREFIX}_ERROR")
        require_exact_fields(self.begin, ("abi", "configs", "samples"), "BEGIN")
        require_exact_fields(
            self.end, ("configs", "samples", "failures", "status"), "END"
        )
        for key, expected in (
            ("abi", ABI_VERSION),
            ("configs", len(expected_configs)),
            ("samples", expected_count),
        ):
            actual = required_int(self.begin, key, "BEGIN")
            if actual != expected:
                raise ReportError(f"BEGIN {key}={actual}, expected {expected}")
        for key, expected in (
            ("configs", len(expected_configs)),
            ("samples", expected_count),
            ("failures", 0),
            ("status", 0),
        ):
            actual = required_int(self.end, key, "END")
            if actual != expected:
                raise ReportError(f"END {key}={actual}, expected {expected}")
        if len(self.samples) != expected_count:
            raise ReportError(
                f"expected {expected_count} samples, found {len(self.samples)}"
            )

        seen: set[tuple[int, int, int]] = set()
        for ordinal, sample in enumerate(self.samples):
            context = f"sample {ordinal}"
            require_exact_fields(sample, SAMPLE_FIELDS, context)
            for key in SAMPLE_FIELDS:
                if key not in STRING_FIELDS:
                    required_int(sample, key, context)
            config = required_int(sample, "config", context)
            warmup = required_int(sample, "warmup", context)
            repetition = required_int(sample, "repetition", context)
            key = (config, warmup, repetition)
            if key in seen:
                raise ReportError(f"duplicate sample key {key}")
            seen.add(key)
            if config not in expected_configs:
                raise ReportError(f"unexpected config {config} for {suite}")
            if (warmup, repetition) not in (
                (1, 0),
                (0, 0),
                (0, 1),
                (0, 2),
                (0, 3),
                (0, 4),
            ):
                raise ReportError(f"invalid sample key {key}")

            expected = expected_config(config)
            for field_name, expected_value in expected.items():
                actual = sample[field_name]
                if actual != expected_value:
                    raise ReportError(
                        f"config {config} {field_name}={actual!r}, "
                        f"expected {expected_value!r}"
                    )
            for error_field in ERROR_FIELDS:
                actual = required_int(sample, error_field, context)
                if actual != 0:
                    raise ReportError(
                        f"config {config} {error_field}={actual}, expected 0"
                    )

        expected_keys = {
            (config, 1, 0) for config in expected_configs
        } | {
            (config, 0, repetition)
            for config in expected_configs
            for repetition in range(MEASURED_REPETITIONS)
        }
        missing_keys = sorted(expected_keys - seen)
        extra_keys = sorted(seen - expected_keys)
        if missing_keys:
            raise ReportError(f"missing sample key(s): {missing_keys}")
        if extra_keys:
            raise ReportError(f"unexpected sample key(s): {extra_keys}")
        expected_sample_order = [
            key
            for config in expected_order
            for key in (
                (config, 1, 0),
                *((config, 0, repetition)
                  for repetition in range(MEASURED_REPETITIONS)),
            )
        ]
        actual_sample_order = [
            (
                int(sample["config"]),
                int(sample["warmup"]),
                int(sample["repetition"]),
            )
            for sample in self.samples
        ]
        if actual_sample_order != expected_sample_order:
            mismatch = next(
                index
                for index, (actual, expected) in enumerate(
                    zip(actual_sample_order, expected_sample_order)
                )
                if actual != expected
            )
            raise ReportError(
                f"sample order does not match schedule {schedule_id}: "
                f"sample {mismatch} is {actual_sample_order[mismatch]}, "
                f"expected {expected_sample_order[mismatch]}"
            )
        self.suite = suite
        self.schedule_id = schedule_id
        self.config_id = config_id

    def measured_samples(self) -> list[dict[str, int | str]]:
        if self.suite is None:
            raise ReportError("report must be validated before aggregation")
        return [sample for sample in self.samples if sample["warmup"] == 0]


def parse_lines(stream: TextIO) -> DirtygenPerfReport:
    report = DirtygenPerfReport()
    for line in stream:
        start = line.find(PREFIX)
        if start < 0:
            continue
        tokens = line[start:].strip().split()
        tag = tokens[0]
        fields = parse_fields(tokens[1:], tag)
        if tag == f"{PREFIX}_BEGIN":
            if report.begin is not None:
                raise ReportError(f"duplicate {PREFIX}_BEGIN")
            report.begin = fields
        elif tag == f"{PREFIX}_SAMPLE":
            report.samples.append(fields)
        elif tag == f"{PREFIX}_END":
            if report.end is not None:
                raise ReportError(f"duplicate {PREFIX}_END")
            report.end = fields
        elif tag == f"{PREFIX}_ERROR":
            report.errors.append(fields)
        else:
            raise ReportError(f"unknown {PREFIX} record {tag!r}")
    return report


def summarize_values(values: list[int]) -> dict[str, int | float]:
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    return {
        "count": len(values),
        "min": min(values),
        "median": median,
        "max": max(values),
        "mad": statistics.median(deviations),
    }


def aggregate(report: DirtygenPerfReport) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, int | str]]] = {}
    for sample in report.measured_samples():
        config = int(sample["config"])
        groups.setdefault(config, []).append(sample)

    result: list[dict[str, Any]] = []
    for config in sorted(groups):
        rows = groups[config]
        if len(rows) != MEASURED_REPETITIONS:
            raise ReportError(
                f"config {config} has {len(rows)} measured samples, expected 5"
            )
        item: dict[str, Any] = {
            "config": config,
            "baseline": rows[0]["baseline"],
            "pattern": rows[0]["pattern"],
            "pages": rows[0]["pages"],
            "operations": rows[0]["operations"],
            "sample_count": len(rows),
        }
        for metric in TIME_METRICS:
            item[metric] = summarize_values(
                [int(row[metric]) for row in rows]
            )
        result.append(item)
    return result


def report_document(report: DirtygenPerfReport) -> dict[str, Any]:
    return {
        "schema": "shdlt-dirtygen-perf-samples-v1",
        "suite": report.suite,
        "begin": report.begin,
        "samples": report.samples,
        "end": report.end,
    }


def summary_document(report: DirtygenPerfReport) -> dict[str, Any]:
    return {
        "schema": "shdlt-dirtygen-perf-summary-v1",
        "suite": report.suite,
        "warmup_samples_excluded": True,
        "configs": aggregate(report),
    }


def emit_csv(report: DirtygenPerfReport, output: TextIO) -> None:
    writer = csv.DictWriter(output, fieldnames=SAMPLE_FIELDS)
    writer.writeheader()
    writer.writerows(report.samples)


def emit_summary_csv(report: DirtygenPerfReport, output: TextIO) -> None:
    rows: list[dict[str, Any]] = []
    for item in aggregate(report):
        row = {
            key: item[key]
            for key in (
                "config",
                "baseline",
                "pattern",
                "pages",
                "operations",
                "sample_count",
            )
        }
        for metric in TIME_METRICS:
            for statistic_name, value in item[metric].items():
                row[f"{metric}_{statistic_name}"] = value
        rows.append(row)
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(report: DirtygenPerfReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "samples.json").write_text(
        json.dumps(report_document(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "samples.csv").open("w", newline="", encoding="utf-8") as stream:
        emit_csv(report, stream)
    (output_dir / "summary.json").write_text(
        json.dumps(summary_document(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        emit_summary_csv(report, stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and summarize SHDLT dirtygen performance output"
    )
    parser.add_argument("log", type=Path)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument(
        "--schedule-id", choices=tuple(SCHEDULE_BASELINES)
    )
    parser.add_argument("--config-id", type=int)
    parser.add_argument("--format", choices=("table", "json", "csv"), default="table")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    if args.suite == "isolated":
        if args.schedule_id is not None:
            parser.error("--suite isolated does not accept --schedule-id")
        if args.config_id is None:
            parser.error("--suite isolated requires --config-id")
        schedule_id = "isolated"
    else:
        if args.config_id is not None:
            parser.error("--config-id is only valid with --suite isolated")
        schedule_id = args.schedule_id or "legacy"

    try:
        with args.log.open(encoding="utf-8", errors="replace") as stream:
            report = parse_lines(stream)
        report.validate(args.suite, schedule_id, args.config_id)
        if args.output_dir is not None:
            write_outputs(report, args.output_dir)
        if args.format == "json":
            json.dump(report_document(report), sys.stdout, indent=2, sort_keys=True)
            print()
        elif args.format == "csv":
            emit_csv(report, sys.stdout)
        else:
            print(
                f"dirtygen perf: PASS suite={args.suite} "
                f"schedule={schedule_id} "
                f"configs={len(selected_configs(args.suite, args.config_id))} "
                f"samples={len(report.samples)} measured={len(report.measured_samples())}"
            )
        return 0
    except (OSError, ReportError, ValueError) as error:
        print(f"dirtygen perf report error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
