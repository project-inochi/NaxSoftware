#!/usr/bin/env python3
"""Build strict paired B0--B3 comparisons for dirtygen_perf campaigns."""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dirtygen_perf_report


SAMPLES_SCHEMA = "shdlt-dirtygen-perf-samples-v1"
METADATA_SCHEMA = "shdlt-dirtygen-perf-campaign-v2"
COMPARISON_SCHEMA = "shdlt-dirtygen-perf-comparison-v1"
BASELINES = ("B0", "B1", "B2", "B3")
PAIR_KEY_FIELDS = (
    "pattern",
    "pages",
    "operations",
    "repetition",
    "schedule_id",
    "simulation_seed",
    "run_id",
)
DELTA_METRICS = (
    "enable_cycles",
    "svadu_cycles",
    "log_cycles",
    "total_cycles",
    "active_total",
)
NORMALIZED_METRICS = (
    "enable_cycles_per_operation",
    "svadu_cycles_per_distinct_dirty_page",
    "log_cycles_per_committed_log_entry",
    "total_cycles_per_distinct_dirty_page",
)
SUMMARY_METRICS = DELTA_METRICS + NORMALIZED_METRICS
class ComparisonError(RuntimeError):
    pass


@dataclass
class Campaign:
    samples_path: Path
    metadata_path: Path
    document: dict[str, Any]
    metadata: dict[str, Any]
    samples: list[dict[str, Any]]

    @property
    def run_id(self) -> str:
        return str(self.metadata["run_id"])

    @property
    def schedule_id(self) -> str:
        return str(self.metadata["schedule_id"])

    @property
    def seed(self) -> int:
        return int(self.metadata["simulation_seed"])

    @property
    def elf_sha256(self) -> str:
        return str(self.metadata["artifact"]["sha256"])


def load_json(path: Path, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonError(f"could not read {kind} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ComparisonError(f"{kind} {path} must contain a JSON object")
    return value


def require_keys(document: dict[str, Any], keys: tuple[str, ...], kind: str) -> None:
    missing = [key for key in keys if key not in document]
    if missing:
        raise ComparisonError(f"{kind} missing field(s): {', '.join(missing)}")


def argv_option(argv: Any, option: str) -> str:
    if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
        raise ComparisonError("metadata simulation argv is invalid")
    positions = [index for index, item in enumerate(argv) if item == option]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise ComparisonError(f"metadata simulation argv must contain one {option}")
    return argv[positions[0] + 1]


def validate_metadata(metadata: dict[str, Any], path: Path) -> None:
    require_keys(
        metadata,
        (
            "schema",
            "run_id",
            "schedule_id",
            "suite",
            "mode",
            "status",
            "exit_code",
            "failure_stage",
            "failure_message",
            "start_time",
            "end_time",
            "trace_required",
            "trace_requested",
            "trace_generated",
            "trace_path",
            "simulation_seed",
            "repositories",
            "top_level_gitlinks",
            "toolchain",
            "cpu_config",
            "commands",
            "artifact",
            "build_exit_code",
            "simulation_exit_code",
            "report_exit_code",
        ),
        f"metadata {path}",
    )
    if metadata["schema"] != METADATA_SCHEMA:
        raise ComparisonError(
            f"metadata {path} schema={metadata['schema']!r}, "
            f"expected {METADATA_SCHEMA!r}"
        )
    if not isinstance(metadata["run_id"], str) or not metadata["run_id"]:
        raise ComparisonError(f"metadata {path} has an invalid run_id")
    schedule_id = metadata["schedule_id"]
    if schedule_id not in dirtygen_perf_report.SCHEDULE_BASELINES:
        raise ComparisonError(f"metadata {path} has an invalid schedule_id")
    if metadata["status"] != "passed" or metadata["exit_code"] != 0:
        raise ComparisonError(f"metadata {path} does not describe a passed campaign")
    if metadata["failure_stage"] is not None or metadata["failure_message"] is not None:
        raise ComparisonError(
            f"metadata {path} has failure details for a passed campaign"
        )
    if not isinstance(metadata["start_time"], str) or not metadata["start_time"]:
        raise ComparisonError(f"metadata {path} has an invalid start_time")
    if not isinstance(metadata["end_time"], str) or not metadata["end_time"]:
        raise ComparisonError(f"metadata {path} has an invalid end_time")
    for field in ("build_exit_code", "simulation_exit_code", "report_exit_code"):
        if metadata[field] != 0:
            raise ComparisonError(f"metadata {path} has {field}={metadata[field]!r}")
    if metadata["suite"] not in dirtygen_perf_report.SUITE_CONFIGS:
        raise ComparisonError(f"metadata {path} has an invalid suite")
    if metadata["mode"] not in ("architecture", "rvls"):
        raise ComparisonError(f"metadata {path} has an invalid mode")

    seed = metadata["simulation_seed"]
    cpu_config = metadata["cpu_config"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ComparisonError(f"metadata {path} has an invalid simulation_seed")
    if not isinstance(cpu_config, dict) or cpu_config.get("seed") != seed:
        raise ComparisonError(
            f"metadata {path} CPU seed does not match simulation_seed"
        )
    commands = metadata["commands"]
    if (
        not isinstance(commands, dict)
        or not isinstance(commands.get("simulation"), dict)
        or not isinstance(commands.get("report"), dict)
    ):
        raise ComparisonError(f"metadata {path} has invalid command records")
    mill_seed = argv_option(commands["simulation"].get("argv"), "--seed")
    mill_argv = commands["simulation"]["argv"]
    try:
        parsed_mill_seed = int(mill_seed)
    except ValueError as error:
        raise ComparisonError(f"metadata {path} has a non-numeric Mill seed") from error
    if parsed_mill_seed != seed:
        raise ComparisonError(
            f"metadata {path} Mill seed does not match simulation_seed"
        )
    report_schedule = argv_option(
        commands["report"].get("argv"), "--schedule-id"
    )
    if report_schedule != schedule_id:
        raise ComparisonError(
            f"metadata {path} report schedule does not match schedule_id"
        )

    trace_required = metadata["mode"] == "rvls"
    trace_requested = "--with-rvls-log" in mill_argv
    if metadata["trace_required"] is not trace_required:
        raise ComparisonError(f"metadata {path} has inconsistent trace_required")
    if metadata["trace_requested"] is not trace_requested:
        raise ComparisonError(f"metadata {path} has inconsistent trace_requested")
    if not isinstance(metadata["trace_generated"], bool):
        raise ComparisonError(f"metadata {path} has invalid trace_generated")
    if trace_required:
        if not metadata["trace_requested"] or not metadata["trace_generated"]:
            raise ComparisonError(f"metadata {path} is missing its required RVLS trace")
        if not isinstance(metadata["trace_path"], str) or not metadata["trace_path"]:
            raise ComparisonError(f"metadata {path} has an invalid RVLS trace_path")
    elif metadata["trace_generated"] or metadata["trace_path"] is not None:
        raise ComparisonError(f"metadata {path} claims a trace in architecture mode")

    artifact = metadata["artifact"]
    sha = artifact.get("sha256") if isinstance(artifact, dict) else None
    if (
        not isinstance(sha, str)
        or len(sha) != 64
        or any(character not in "0123456789abcdef" for character in sha.lower())
    ):
        raise ComparisonError(f"metadata {path} has an invalid ELF SHA256")
    repositories = metadata["repositories"]
    if not isinstance(repositories, dict):
        raise ComparisonError(f"metadata {path} has invalid repository states")
    for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS"):
        state = repositories.get(name)
        if not isinstance(state, dict) or not isinstance(state.get("head"), str):
            raise ComparisonError(f"metadata {path} is missing {name} HEAD")
    gitlinks = metadata["top_level_gitlinks"]
    expected_gitlinks = {"NaxSoftware", "Spike", "RVLS"}
    if not isinstance(gitlinks, dict) or set(gitlinks) != expected_gitlinks:
        raise ComparisonError(f"metadata {path} has invalid top-level gitlinks")
    if not isinstance(metadata["toolchain"], dict):
        raise ComparisonError(f"metadata {path} has invalid toolchain information")


def validate_samples_document(document: dict[str, Any], metadata: dict[str, Any],
                              path: Path) -> list[dict[str, Any]]:
    expected_fields = {"schema", "suite", "begin", "samples", "end"}
    if set(document) != expected_fields:
        missing = sorted(expected_fields - set(document))
        extra = sorted(set(document) - expected_fields)
        raise ComparisonError(
            f"samples {path} fields differ: missing={missing} extra={extra}"
        )
    if document["schema"] != SAMPLES_SCHEMA:
        raise ComparisonError(f"samples {path} has an unsupported schema")
    if document["suite"] != metadata["suite"]:
        raise ComparisonError(f"samples {path} suite does not match metadata")
    if not isinstance(document["samples"], list):
        raise ComparisonError(f"samples {path} has a non-list samples field")
    report = dirtygen_perf_report.DirtygenPerfReport(
        begin=document["begin"],
        samples=document["samples"],
        end=document["end"],
    )
    report.validate(str(document["suite"]), str(metadata["schedule_id"]))
    return [dict(sample) for sample in report.samples]


def load_campaign(samples_path: Path, metadata_path: Path) -> Campaign:
    metadata = load_json(metadata_path, "metadata")
    validate_metadata(metadata, metadata_path)
    document = load_json(samples_path, "samples")
    samples = validate_samples_document(document, metadata, samples_path)
    return Campaign(samples_path, metadata_path, document, metadata, samples)


def compatibility_value(campaign: Campaign) -> dict[str, Any]:
    cpu_config = dict(campaign.metadata["cpu_config"])
    cpu_config.pop("seed", None)
    return {
        "suite": campaign.metadata["suite"],
        "mode": campaign.metadata["mode"],
        "cpu_config_without_seed": cpu_config,
        "repository_heads": {
            name: state["head"]
            for name, state in campaign.metadata["repositories"].items()
        },
        "toolchain": campaign.metadata["toolchain"],
        "begin": campaign.document["begin"],
        "end": campaign.document["end"],
    }


def validate_compatibility(campaigns: list[Campaign]) -> None:
    if not campaigns:
        raise ComparisonError("at least one campaign input is required")
    run_ids: set[str] = set()
    expected = compatibility_value(campaigns[0])
    schedule_hashes: dict[str, str] = {}
    for campaign in campaigns:
        if campaign.run_id in run_ids:
            raise ComparisonError(f"duplicate run_id {campaign.run_id!r}")
        run_ids.add(campaign.run_id)
        if compatibility_value(campaign) != expected:
            raise ComparisonError(
                f"campaign {campaign.run_id!r} has incompatible experiment metadata"
            )
        schedule_key = str(campaign.schedule_id)
        old_hash = schedule_hashes.setdefault(schedule_key, campaign.elf_sha256)
        if old_hash != campaign.elf_sha256:
            raise ComparisonError(
                f"schedule {schedule_key!r} uses multiple ELF SHA256 values"
            )


def safe_divide(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def pairing_key(campaign: Campaign, sample: dict[str, Any]) -> tuple[Any, ...]:
    return (
        sample["pattern"],
        sample["pages"],
        sample["operations"],
        sample["repetition"],
        campaign.schedule_id,
        campaign.seed,
        campaign.run_id,
    )


def build_pairings(campaigns: list[Campaign]) -> list[dict[str, Any]]:
    grouped: dict[
        tuple[Any, ...], list[tuple[Campaign, dict[str, Any]]]
    ] = defaultdict(list)
    for campaign in campaigns:
        for sample in campaign.samples:
            if sample["warmup"] == 0:
                grouped[pairing_key(campaign, sample)].append((campaign, sample))

    pairings: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: tuple(str(value) for value in item)):
        rows = grouped[key]
        by_baseline: dict[str, tuple[Campaign, dict[str, Any]]] = {}
        for campaign, sample in rows:
            baseline = str(sample["baseline"])
            if baseline in by_baseline:
                raise ComparisonError(f"pair {key!r} has duplicate baseline {baseline}")
            by_baseline[baseline] = campaign, sample
        if set(by_baseline) != set(BASELINES):
            raise ComparisonError(
                f"pair {key!r} baseline set {sorted(by_baseline)} != {list(BASELINES)}"
            )
        campaign = rows[0][0]
        if any(row_campaign.run_id != campaign.run_id for row_campaign, _ in rows):
            raise ComparisonError(f"pair {key!r} spans multiple campaigns")
        instret = {
            int(sample["workload_instret"])
            for _, sample in by_baseline.values()
        }
        if len(instret) != 1:
            values = {
                baseline: sample["workload_instret"]
                for baseline, (_, sample) in by_baseline.items()
            }
            raise ComparisonError(f"pair {key!r} workload_instret differs: {values}")

        cycles = {
            baseline: int(by_baseline[baseline][1]["workload_cycles"])
            for baseline in BASELINES
        }
        b3 = by_baseline["B3"][1]
        distinct = int(b3["expected_d_transitions"])
        committed = int(b3["expected_log_entries"])
        operations = int(b3["operations"])
        enable = cycles["B1"] - cycles["B0"]
        svadu = cycles["B2"] - cycles["B0"]
        log = cycles["B3"] - cycles["B2"]
        total = cycles["B3"] - cycles["B0"]
        item: dict[str, Any] = dict(zip(PAIR_KEY_FIELDS, key))
        item.update(
            {
                "elf_sha256": campaign.elf_sha256,
                "workload_instret": instret.pop(),
                "distinct_dirty_pages": distinct,
                "committed_log_entries": committed,
                "b0_workload_cycles": cycles["B0"],
                "b1_workload_cycles": cycles["B1"],
                "b2_workload_cycles": cycles["B2"],
                "b3_workload_cycles": cycles["B3"],
                "enable_cycles": enable,
                "svadu_cycles": svadu,
                "log_cycles": log,
                "total_cycles": total,
                "active_total": cycles["B3"] - cycles["B1"],
                "enable_cycles_per_operation": safe_divide(enable, operations),
                "svadu_cycles_per_distinct_dirty_page": safe_divide(svadu, distinct),
                "log_cycles_per_committed_log_entry": safe_divide(log, committed),
                "total_cycles_per_distinct_dirty_page": safe_divide(total, distinct),
            }
        )
        pairings.append(item)
    return pairings


def summarize(values: list[int | float | None]) -> dict[str, int | float | None]:
    present = [value for value in values if value is not None]
    if not present:
        return {"count": 0, "min": None, "median": None, "max": None, "mad": None}
    median = statistics.median(present)
    return {
        "count": len(present),
        "min": min(present),
        "median": median,
        "max": max(present),
        "mad": statistics.median(abs(value - median) for value in present),
    }


def build_summaries(pairings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_fields = (
        "pattern",
        "pages",
        "operations",
        "schedule_id",
        "simulation_seed",
        "run_id",
        "elf_sha256",
    )
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for pairing in pairings:
        grouped[tuple(pairing[field] for field in group_fields)].append(pairing)
    result: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: tuple(str(value) for value in item)):
        rows = grouped[key]
        repetitions = [int(row["repetition"]) for row in rows]
        expected = list(range(dirtygen_perf_report.MEASURED_REPETITIONS))
        if sorted(repetitions) != expected:
            raise ComparisonError(
                f"summary group {key!r} has repetitions {repetitions}"
            )
        item = dict(zip(group_fields, key))
        item["pair_count"] = len(rows)
        item["metrics"] = {
            metric: summarize([row[metric] for row in rows])
            for metric in SUMMARY_METRICS
        }
        result.append(item)
    return result


def build_schedule_distributions(
    summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    group_fields = ("pattern", "pages", "operations", "simulation_seed")
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for summary in summaries:
        grouped[tuple(summary[field] for field in group_fields)].append(summary)
    result: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: tuple(str(value) for value in item)):
        rows = grouped[key]
        entries = []
        ordered = sorted(
            rows,
            key=lambda item: (str(item["schedule_id"]), item["run_id"]),
        )
        for row in ordered:
            entries.append(
                {
                    "schedule_id": row["schedule_id"],
                    "run_id": row["run_id"],
                    "elf_sha256": row["elf_sha256"],
                    "medians": {
                        metric: row["metrics"][metric]["median"]
                        for metric in SUMMARY_METRICS
                    },
                }
            )
        item = dict(zip(group_fields, key))
        item["runs"] = entries
        item["median_distributions"] = {
            metric: summarize(
                [row["metrics"][metric]["median"] for row in ordered]
            )
            for metric in SUMMARY_METRICS
        }
        result.append(item)
    return result


def comparison_document(campaigns: list[Campaign]) -> dict[str, Any]:
    validate_compatibility(campaigns)
    pairings = build_pairings(campaigns)
    summaries = build_summaries(pairings)
    return {
        "schema": COMPARISON_SCHEMA,
        "status": "PASS",
        "suite": campaigns[0].metadata["suite"],
        "mode": campaigns[0].metadata["mode"],
        "pair_key_fields": list(PAIR_KEY_FIELDS),
        "warmup_samples_excluded": True,
        "cycle_deltas_are_descriptive_only": True,
        "sources": [
            {
                "samples_path": str(campaign.samples_path),
                "metadata_path": str(campaign.metadata_path),
                "run_id": campaign.run_id,
                "schedule_id": campaign.schedule_id,
                "simulation_seed": campaign.seed,
                "elf_sha256": campaign.elf_sha256,
            }
            for campaign in campaigns
        ],
        "pairings": pairings,
        "summaries": summaries,
        "schedule_distributions": build_schedule_distributions(summaries),
    }


def flatten_summary(summary: dict[str, Any]) -> dict[str, Any]:
    row = {
        field: summary[field]
        for field in (
            "pattern",
            "pages",
            "operations",
            "schedule_id",
            "simulation_seed",
            "run_id",
            "elf_sha256",
            "pair_count",
        )
    }
    for metric in SUMMARY_METRICS:
        for statistic, value in summary["metrics"][metric].items():
            row[f"{metric}_{statistic}"] = value
    return row


def csv_text(summaries: list[dict[str, Any]]) -> str:
    import io

    output = io.StringIO(newline="")
    rows = [flatten_summary(summary) for summary in summaries]
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output.getvalue()


def atomic_write(path: Path, payload: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_outputs(document: dict[str, Any], output_dir: Path) -> None:
    json_path = output_dir / "comparison.json"
    csv_path = output_dir / "comparison.csv"
    if json_path.exists() or csv_path.exists():
        raise ComparisonError(f"comparison output already exists in {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_payload = csv_text(document["summaries"])
    json_payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    atomic_write(csv_path, csv_payload)
    try:
        atomic_write(json_path, json_payload)
    except BaseException:
        csv_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate strict paired SHDLT dirtygen performance comparisons"
    )
    parser.add_argument(
        "--input",
        action="append",
        nargs=2,
        metavar=("SAMPLES_JSON", "METADATA_JSON"),
        required=True,
        type=Path,
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        campaigns = [
            load_campaign(samples_path, metadata_path)
            for samples_path, metadata_path in args.input
        ]
        document = comparison_document(campaigns)
        write_outputs(document, args.output_dir)
        print(
            f"dirtygen perf comparison: PASS runs={len(campaigns)} "
            f"pairs={len(document['pairings'])} summaries={len(document['summaries'])}"
        )
        return 0
    except (
        OSError,
        ValueError,
        ComparisonError,
        dirtygen_perf_report.ReportError,
    ) as error:
        print(f"dirtygen perf comparison error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
