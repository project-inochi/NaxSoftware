#!/usr/bin/env python3
"""Compare fresh-process dirtygen_perf_mc campaigns."""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import shutil
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dirtygen_perf_mc_report as mc_report


SAMPLES_SCHEMA = "shdlt-dirtygen-perf-mc-samples-v2"
TRACE_SCHEMA = "shdlt-dirtygen-perf-mc-trace-report-v2"
METADATA_SCHEMA = "shdlt-dirtygen-perf-mc-campaign-v2"
COMPARISON_SCHEMA = "shdlt-dirtygen-perf-mc-comparison-v2"
PREFILLED_COMPARISON_SCHEMA = "shdlt-dirtygen-perf-mc-prefilled-comparison-v2"
BASELINES = ("B0", "B1", "B2", "B3")
BLOCKS = {
    "I0": ("B0", "B1", "B3", "B2"),
    "I1": ("B1", "B2", "B0", "B3"),
    "I2": ("B2", "B3", "B1", "B0"),
    "I3": ("B3", "B0", "B2", "B1"),
}
DELTA_FIELDS = ("enable_cycles", "svadu_cycles", "log_cycles",
                "total_cycles", "active_total")
REPOSITORIES = ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")
CODE_HASHES = ("text_sha256", "text_init_sha256", "workload_code_sha256",
               "timed_window_sha256")


class ComparisonError(RuntimeError):
    pass


@dataclass
class Campaign:
    samples_path: Path
    metadata_path: Path
    trace_path: Path
    document: dict[str, Any]
    metadata: dict[str, Any]
    trace: dict[str, Any]

    @property
    def harts(self) -> int:
        return int(self.metadata["hart_count"])

    @property
    def workload(self) -> str:
        return str(self.metadata["workload"])

    @property
    def baseline(self) -> str:
        return str(self.metadata["baseline"])

    @property
    def block(self) -> str:
        return str(self.metadata["isolation_block_id"])

    @property
    def seed(self) -> int:
        return int(self.metadata["simulation_seed"])

    @property
    def mode(self) -> str:
        return str(self.metadata["mode"])

    @property
    def experiment(self) -> str:
        return str(self.metadata["experiment_id"])

    @property
    def prefilled(self) -> bool:
        return self.workload == "prefilled-same-pte"


def load_json(path: Path, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonError(f"cannot read {kind} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ComparisonError(f"{kind} {path} is not a JSON object")
    return value


def require_keys(value: dict[str, Any], keys: tuple[str, ...], context: str) -> None:
    missing = sorted(set(keys) - set(value))
    if missing:
        raise ComparisonError(f"{context} missing fields {missing}")


def parse_time(value: Any, context: str) -> datetime.datetime:
    if not isinstance(value, str):
        raise ComparisonError(f"{context} is not a timestamp")
    try:
        result = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        raise ComparisonError(f"{context} is not an ISO timestamp") from error
    if result.tzinfo is None:
        raise ComparisonError(f"{context} has no timezone")
    return result


def sha256(value: Any, context: str) -> str:
    if (not isinstance(value, str) or len(value) != 64 or
            any(character not in "0123456789abcdefABCDEF" for character in value)):
        raise ComparisonError(f"{context} is not SHA256")
    return value.lower()


def argv_value(argv: Any, option: str) -> str:
    if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
        raise ComparisonError("metadata command argv is invalid")
    indexes = [index for index, item in enumerate(argv) if item == option]
    if len(indexes) != 1 or indexes[0] + 1 == len(argv):
        raise ComparisonError(f"metadata command must contain one {option}")
    return argv[indexes[0] + 1]


def report_from_document(document: dict[str, Any]) -> mc_report.McReport:
    require_keys(document, ("schema", "begin", "samples", "end"), "samples document")
    if document["schema"] != SAMPLES_SCHEMA:
        raise ComparisonError(f"samples schema must be {SAMPLES_SCHEMA}")
    if not isinstance(document["samples"], list):
        raise ComparisonError("samples must be an array")
    samples: list[dict[str, Any]] = []
    harts: list[dict[str, Any]] = []
    for item in document["samples"]:
        if not isinstance(item, dict) or not isinstance(item.get("harts"), list):
            raise ComparisonError("sample lacks hart records")
        sample = dict(item)
        harts.extend(sample.pop("harts"))
        samples.append(sample)
    return mc_report.McReport(begin=document["begin"], samples=samples,
                              harts=harts, end=document["end"])


def validate_metadata(metadata: dict[str, Any], path: Path) -> None:
    require_keys(metadata, ("schema", "status", "exit_code", "failure_stage",
                 "failure_message", "start_time", "end_time", "run_id",
                 "process_run_id", "experiment_id", "isolation_block_id",
                 "launch_order", "launch_position", "fresh_reset", "hart_count",
                 "workload", "baseline", "mode", "simulation_seed",
                 "trace_required", "trace_requested", "trace_generated",
                 "trace_path", "repositories", "toolchain", "cpu_config",
                 "commands", "artifact", "build_exit_code",
                 "simulation_exit_code", "report_exit_code"), f"metadata {path}")
    if metadata["schema"] != METADATA_SCHEMA:
        raise ComparisonError(f"metadata {path} has wrong schema")
    if metadata.get("counter_contract") != "abi-v2:5*N+5;CSR-I-fences":
        raise ComparisonError(f"metadata {path} has incompatible counter contract")
    if (metadata["status"] != "passed" or metadata["exit_code"] != 0 or
            metadata["failure_stage"] is not None or metadata["failure_message"] is not None):
        raise ComparisonError(f"metadata {path} is not a successful campaign")
    if any(metadata[field] != 0 for field in
           ("build_exit_code", "simulation_exit_code", "report_exit_code")):
        raise ComparisonError(f"metadata {path} has a failed command")
    if metadata["fresh_reset"] is not True:
        raise ComparisonError(f"metadata {path} is not fresh-reset")
    harts = metadata["hart_count"]
    workload = metadata["workload"]
    baseline = metadata["baseline"]
    if harts not in (1, 2, 4) or baseline not in BASELINES:
        raise ComparisonError(f"metadata {path} selection is invalid")
    if workload not in ("private-strong", "private-weak", "same-pte",
                         "prefilled-same-pte"):
        raise ComparisonError(f"metadata {path} workload is invalid")
    if workload == "prefilled-same-pte" and (harts not in (2, 4) or baseline not in ("B2", "B3")):
        raise ComparisonError(f"metadata {path} has invalid PREFILLED selection")
    block = metadata["isolation_block_id"]
    if block not in BLOCKS or metadata["launch_order"] != list(BLOCKS[block]):
        raise ComparisonError(f"metadata {path} has wrong launch order")
    if metadata["launch_position"] != BLOCKS[block].index(baseline):
        raise ComparisonError(f"metadata {path} has wrong launch position")
    if (not isinstance(metadata["run_id"], str) or not metadata["run_id"] or
            metadata["process_run_id"] != metadata["run_id"]):
        raise ComparisonError(f"metadata {path} has invalid process ID")
    seed = metadata["simulation_seed"]
    cpu = metadata["cpu_config"]
    if not isinstance(seed, int) or not isinstance(cpu, dict) or cpu.get("seed") != seed:
        raise ComparisonError(f"metadata {path} seed mismatch")
    if cpu.get("cpu_count") != harts:
        raise ComparisonError(f"metadata {path} hart/CPU mismatch")
    commands = metadata["commands"]
    if not isinstance(commands, dict):
        raise ComparisonError(f"metadata {path} commands are invalid")
    simulation = commands.get("simulation", {}).get("argv")
    report = commands.get("report", {}).get("argv")
    if int(argv_value(simulation, "--seed")) != seed or int(argv_value(simulation, "--cpu-count")) != harts:
        raise ComparisonError(f"metadata {path} simulation command mismatch")
    if (argv_value(report, "--hart-count") != str(harts) or
            argv_value(report, "--workload") != workload or
            argv_value(report, "--baseline") != baseline):
        raise ComparisonError(f"metadata {path} report command mismatch")
    mode = metadata["mode"]
    if mode not in ("architecture", "rvls"):
        raise ComparisonError(f"metadata {path} mode is invalid")
    if not all(metadata[name] is True for name in
               ("trace_required", "trace_requested", "trace_generated")):
        raise ComparisonError(f"metadata {path} lacks required raw trace")
    if metadata["trace_path"] != "tracer.log":
        raise ComparisonError(f"metadata {path} trace path is invalid")
    for name in REPOSITORIES:
        state = metadata["repositories"].get(name)
        if not isinstance(state, dict) or not isinstance(state.get("head"), str):
            raise ComparisonError(f"metadata {path} lacks {name} HEAD")
    if not isinstance(metadata["toolchain"], dict):
        raise ComparisonError(f"metadata {path} toolchain is invalid")
    artifact = metadata["artifact"]
    if not isinstance(artifact, dict):
        raise ComparisonError(f"metadata {path} artifact is invalid")
    for field in ("elf_sha256",) + CODE_HASHES:
        sha256(artifact.get(field), f"metadata {path} {field}")
    selection = artifact.get("selection")
    expected_workload = {"private-strong": 0, "private-weak": 1,
                         "same-pte": 2, "prefilled-same-pte": 3}[workload]
    if (not isinstance(selection, dict) or selection.get("hart_count") != harts or
            selection.get("abi_version") != mc_report.ABI_VERSION or
            selection.get("workload") != expected_workload or
            selection.get("baseline") != int(baseline[1:]) or selection.get("runs") != 6):
        raise ComparisonError(f"metadata {path} selection object mismatch")
    start = parse_time(metadata["start_time"], f"metadata {path} start_time")
    end = parse_time(metadata["end_time"], f"metadata {path} end_time")
    if end < start:
        raise ComparisonError(f"metadata {path} has negative run duration")


def validate_trace(trace: dict[str, Any], report: mc_report.McReport,
                   path: Path) -> None:
    require_keys(trace, ("schema", "status", "samples", "lifecycles", "totals"),
                 f"trace report {path}")
    if trace["schema"] != TRACE_SCHEMA or trace["status"] != "PASS":
        raise ComparisonError(f"trace report {path} did not pass")
    rows = trace["samples"]
    if (not isinstance(rows, list) or len(rows) != 6 or
            [row.get("sample") for row in rows] != list(range(6))):
        raise ComparisonError(f"trace report {path} sample set is invalid")
    numeric = ("physical_attempts", "committed", "superseded", "errors",
               "architectural_stores", "cas_attempts")
    for row in rows:
        if any(not isinstance(row.get(field), int) or row[field] < 0 for field in numeric):
            raise ComparisonError(f"trace report {path} has invalid counts")
        if row["errors"] != 0:
            raise ComparisonError(f"trace report {path} contains logger error")
        if row["physical_attempts"] != row["committed"] + row["superseded"]:
            raise ComparisonError(f"trace report {path} lifecycle count mismatch")
    totals = trace["totals"]
    for field in ("physical_attempts", "committed", "superseded", "errors",
                  "architectural_stores"):
        if totals.get(field) != sum(row[field] for row in rows):
            raise ComparisonError(f"trace report {path} total {field} mismatch")
    lifecycle = trace["lifecycles"]
    if not isinstance(lifecycle, list) or len(lifecycle) != totals["physical_attempts"]:
        raise ComparisonError(f"trace report {path} lifecycle list mismatch")
    for event in lifecycle:
        states = event.get("states")
        if states not in (["pending", "committed"], ["pending", "superseded"]):
            raise ComparisonError(f"trace report {path} has open/error lifecycle")
        if event.get("terminal_state") != states[-1] or event.get("error") != 0:
            raise ComparisonError(f"trace report {path} lifecycle terminal mismatch")
    by_sample = {int(sample["sample"]): sample for sample in report.samples}
    for row in rows:
        sample = by_sample[row["sample"]]
        if row["cas_attempts"] != sample["pte_cas_attempts"]:
            raise ComparisonError(f"trace report {path} CAS count mismatch")


def load_campaign(samples_path: Path, metadata_path: Path) -> Campaign:
    document = load_json(samples_path, "samples")
    metadata = load_json(metadata_path, "metadata")
    trace_path = samples_path.parent / "trace-report.json"
    trace = load_json(trace_path, "trace report")
    validate_metadata(metadata, metadata_path)
    report = report_from_document(document)
    workload = str(metadata["workload"]).replace("-", "_").upper()
    try:
        report.validate(int(metadata["hart_count"]), workload, str(metadata["baseline"]))
    except mc_report.ReportError as error:
        raise ComparisonError(f"samples {samples_path}: {error}") from error
    validate_trace(trace, report, trace_path)
    if document["begin"].get("workload") != workload:
        raise ComparisonError(f"samples {samples_path} workload mismatch")
    return Campaign(samples_path, metadata_path, trace_path, document, metadata, trace)


def common_signature(campaign: Campaign) -> dict[str, Any]:
    return {
        "seed": campaign.seed,
        "cpu": campaign.metadata["cpu_config"],
        "repositories": {name: campaign.metadata["repositories"][name]["head"]
                         for name in REPOSITORIES},
        "toolchain": campaign.metadata["toolchain"],
        "code": {field: campaign.metadata["artifact"][field] for field in CODE_HASHES},
    }


def compatibility_signature(campaign: Campaign) -> dict[str, Any]:
    signature = common_signature(campaign)
    cpu = dict(signature["cpu"])
    cpu.pop("cpu_count", None)
    cpu.pop("lsu_l1_coherency", None)
    signature["cpu"] = cpu
    return signature


def validate_campaign_set(campaigns: list[Campaign]) -> None:
    if not campaigns:
        raise ComparisonError("at least one campaign is required")
    for campaign in campaigns:
        validate_metadata(campaign.metadata, campaign.metadata_path)
        report = report_from_document(campaign.document)
        workload = campaign.workload.replace("-", "_").upper()
        try:
            report.validate(campaign.harts, workload, campaign.baseline)
        except mc_report.ReportError as error:
            raise ComparisonError(f"samples {campaign.samples_path}: {error}") from error
        validate_trace(campaign.trace, report, campaign.trace_path)
    run_ids = [campaign.metadata["run_id"] for campaign in campaigns]
    if len(run_ids) != len(set(run_ids)):
        raise ComparisonError("duplicate run/process ID")
    prefilled = {campaign.prefilled for campaign in campaigns}
    if len(prefilled) != 1:
        raise ComparisonError("ordinary and PREFILLED inputs cannot be mixed")
    reference = compatibility_signature(campaigns[0])
    for campaign in campaigns[1:]:
        if compatibility_signature(campaign) != reference:
            raise ComparisonError("campaign CPU, HEAD, toolchain, seed, or code hashes differ")
    elf_by_selection: dict[tuple[int, str, str], str] = {}
    for campaign in campaigns:
        key = (campaign.harts, campaign.workload, campaign.baseline)
        elf = campaign.metadata["artifact"]["elf_sha256"]
        old = elf_by_selection.setdefault(key, elf)
        if old != elf:
            raise ComparisonError(f"ELF hash changed for selection {key}")


def measured(campaign: Campaign) -> dict[int, dict[str, Any]]:
    rows = {int(row["repetition"]): row for row in campaign.document["samples"]
            if int(row["warmup"]) == 0}
    if set(rows) != set(range(5)):
        raise ComparisonError(f"{campaign.samples_path} measured repetitions are incomplete")
    return rows


def median(values: list[float | int]) -> float | int:
    result = statistics.median(values)
    return int(result) if isinstance(result, float) and result.is_integer() else result


def stats(values: list[float | int]) -> dict[str, float | int]:
    center = median(values)
    deviations = [abs(value - center) for value in values]
    return {"median": center, "mad": median(deviations), "min": min(values),
            "max": max(values)}


def deltas(rows: dict[str, dict[str, Any]]) -> dict[str, int]:
    cycles = {baseline: int(row["completion_cycles"]) for baseline, row in rows.items()}
    return {"enable_cycles": cycles["B1"] - cycles["B0"],
            "svadu_cycles": cycles["B2"] - cycles["B0"],
            "log_cycles": cycles["B3"] - cycles["B2"],
            "total_cycles": cycles["B3"] - cycles["B0"],
            "active_total": cycles["B3"] - cycles["B1"]}


def require_serial_group(group: list[Campaign], baselines: tuple[str, ...]) -> None:
    if {item.baseline for item in group} != set(baselines) or len(group) != len(baselines):
        raise ComparisonError(f"group must contain exactly {baselines}")
    ordered = sorted(group, key=lambda item: int(item.metadata["launch_position"]))
    if tuple(item.baseline for item in ordered) != tuple(
            baseline for baseline in BLOCKS[group[0].block] if baseline in baselines):
        raise ComparisonError("campaign launch order is inconsistent")
    for previous, current in zip(ordered, ordered[1:]):
        if parse_time(previous.metadata["end_time"], "end_time") > parse_time(
                current.metadata["start_time"], "start_time"):
            raise ComparisonError("campaign processes overlap or ran out of order")


def sample_metrics(row: dict[str, Any]) -> dict[str, Any]:
    completion = int(row["completion_cycles"])
    total_ops = int(row["total_operations"])
    dirty = int(row["distinct_dirty_pages"])
    return {"completion_cycles": completion,
            "aggregate_ops_per_cycle": total_ops / completion,
            "dirty_page_throughput": dirty / completion}


def trace_sample(campaign: Campaign, sample_id: int) -> dict[str, Any]:
    rows = [row for row in campaign.trace["samples"] if row["sample"] == sample_id]
    if len(rows) != 1:
        raise ComparisonError("trace report has duplicate/missing sample")
    return rows[0]


def ordinary_document(campaigns: list[Campaign]) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], list[Campaign]] = defaultdict(list)
    for campaign in campaigns:
        if campaign.prefilled:
            raise ComparisonError("PREFILLED input in ordinary comparison")
        groups[(campaign.experiment, campaign.block, campaign.harts,
                campaign.workload, campaign.mode, campaign.seed)].append(campaign)
    pairings: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        require_serial_group(group, BASELINES)
        rows_by_baseline = {item.baseline: measured(item) for item in group}
        trace_by_baseline = {item.baseline: item for item in group}
        for repetition in range(5):
            rows = {baseline: values[repetition]
                    for baseline, values in rows_by_baseline.items()}
            instret = {baseline: tuple(int(hart["workload_instret"])
                       for hart in row["harts"]) for baseline, row in rows.items()}
            operations = {baseline: tuple(int(hart["operations"])
                           for hart in row["harts"]) for baseline, row in rows.items()}
            if len(set(instret.values())) != 1 or len(set(operations.values())) != 1:
                raise ComparisonError(f"B0-B3 hart instret/operations mismatch for {key} repetition {repetition}")
            item = {"experiment_id": key[0], "isolation_block_id": key[1],
                    "hart_count": key[2], "workload": key[3], "mode": key[4],
                    "simulation_seed": key[5], "repetition": repetition,
                    "per_hart_instret": list(next(iter(instret.values()))),
                    "baselines": {baseline: sample_metrics(row)
                                  for baseline, row in rows.items()}, **deltas(rows)}
            if key[3] == "same-pte":
                item["physical_logger"] = {
                    baseline: {name: trace_sample(trace_by_baseline[baseline], repetition + 1)[name]
                               for name in ("physical_attempts", "committed", "superseded",
                                            "append_amplification", "superseded_ratio")}
                    for baseline in BASELINES}
            pairings.append(item)
        group_pairings = [item for item in pairings if all(
            item[field] == value for field, value in zip(
                ("experiment_id", "isolation_block_id", "hart_count", "workload",
                 "mode", "simulation_seed"), key))]
        summary = {"experiment_id": key[0], "isolation_block_id": key[1],
                   "hart_count": key[2], "workload": key[3], "mode": key[4],
                   "simulation_seed": key[5], "measured_pairings": len(group_pairings),
                   "deltas": {field: stats([item[field] for item in group_pairings])
                              for field in DELTA_FIELDS},
                   "baselines": {baseline: {
                       metric: stats([item["baselines"][baseline][metric]
                                      for item in group_pairings])
                       for metric in ("completion_cycles", "aggregate_ops_per_cycle",
                                      "dirty_page_throughput")}
                       for baseline in BASELINES}}
        if key[3] == "same-pte":
            summary["physical_logger"] = {baseline: {
                field: stats([item["physical_logger"][baseline][field]
                              for item in group_pairings
                              if item["physical_logger"][baseline][field] is not None])
                if any(item["physical_logger"][baseline][field] is not None
                       for item in group_pairings) else None
                for field in ("physical_attempts", "committed", "superseded",
                              "append_amplification", "superseded_ratio")}
                for baseline in BASELINES}
        summaries.append(summary)

    # H1/I0 is the reference for strong/weak scaling, not a main distribution.
    references = {(item["experiment_id"], item["workload"], item["mode"],
                   item["simulation_seed"], item["repetition"]): item
                  for item in pairings if item["hart_count"] == 1 and
                  item["isolation_block_id"] == "I0"}
    for item in pairings:
        if item["hart_count"] == 1 or item["workload"] not in ("private-strong", "private-weak"):
            continue
        reference = references.get((item["experiment_id"], item["workload"],
                                    item["mode"], item["simulation_seed"],
                                    item["repetition"]))
        if reference is None:
            raise ComparisonError(f"missing H1 reference for {item['workload']}")
        item["scaling"] = {}
        for baseline in BASELINES:
            t1 = reference["baselines"][baseline]["completion_cycles"]
            th = item["baselines"][baseline]["completion_cycles"]
            speedup = t1 / th
            item["scaling"][baseline] = {"speedup": speedup,
                                          "efficiency": speedup / item["hart_count"]}
    for summary in summaries:
        matching = [item for item in pairings if item.get("scaling") and
                    item["experiment_id"] == summary["experiment_id"] and
                    item["isolation_block_id"] == summary["isolation_block_id"] and
                    item["hart_count"] == summary["hart_count"] and
                    item["workload"] == summary["workload"]]
        if matching:
            summary["scaling"] = {baseline: {
                metric: stats([item["scaling"][baseline][metric] for item in matching])
                for metric in ("speedup", "efficiency")}
                for baseline in BASELINES}

    distributions = []
    distribution_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for summary in summaries:
        if summary["hart_count"] in (2, 4):
            distribution_groups[(summary["experiment_id"], summary["hart_count"],
                                 summary["workload"], summary["mode"],
                                 summary["simulation_seed"])].append(summary)
    for key, group in sorted(distribution_groups.items()):
        if {item["isolation_block_id"] for item in group} != set(BLOCKS) or len(group) != 4:
            raise ComparisonError(f"main distribution {key} lacks I0-I3")
        distributions.append({"experiment_id": key[0], "hart_count": key[1],
                              "workload": key[2], "mode": key[3],
                              "simulation_seed": key[4],
                              "block_medians": {field: {
                                  item["isolation_block_id"]: item["deltas"][field]["median"]
                                  for item in group} for field in DELTA_FIELDS}})
    return {"schema": COMPARISON_SCHEMA, "status": "PASS",
            "sources": source_rows(campaigns),
            "counts": {"sources": len(campaigns),
                       "reference_pairings": sum(item["hart_count"] == 1 for item in pairings),
                       "main_pairings": sum(item["hart_count"] in (2, 4) for item in pairings),
                       "summaries": len(summaries), "main_summaries": sum(
                           item["hart_count"] in (2, 4) for item in summaries),
                       "distributions": len(distributions)},
            "pairings": pairings, "summaries": summaries,
            "cross_block_distributions": distributions}


def prefilled_signature(trace: dict[str, Any]) -> tuple[Any, ...]:
    return (trace["cas_attempts"], tuple(trace["attempting_harts"]),
            trace["winner_hart"])


def architectural_sample(row: dict[str, Any]) -> dict[str, Any]:
    return row


def prefilled_document(campaigns: list[Campaign]) -> dict[str, Any]:
    groups: dict[tuple[int, str], list[Campaign]] = defaultdict(list)
    for campaign in campaigns:
        if not campaign.prefilled:
            raise ComparisonError("ordinary input in PREFILLED comparison")
        groups[(campaign.harts, campaign.mode)].append(campaign)
    observations: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    by_selection: dict[tuple[int, str], Campaign] = {}
    for key, group in sorted(groups.items()):
        require_serial_group(group, ("B3", "B2"))
        selected = {item.baseline: item for item in group}
        by_selection[(key[0], "B2", key[1])] = selected["B2"]
        by_selection[(key[0], "B3", key[1])] = selected["B3"]
        rows = {baseline: measured(campaign) for baseline, campaign in selected.items()}
        completion_deltas: list[int] = []
        for repetition in range(5):
            b2_trace = trace_sample(selected["B2"], repetition + 1)
            b3_trace = trace_sample(selected["B3"], repetition + 1)
            b2 = rows["B2"][repetition]
            b3 = rows["B3"][repetition]
            b2_sig, b3_sig = prefilled_signature(b2_trace), prefilled_signature(b3_trace)
            matched = b2_sig == b3_sig
            if matched:
                if tuple(int(h["workload_instret"]) for h in b2["harts"]) != tuple(
                        int(h["workload_instret"]) for h in b3["harts"]):
                    raise ComparisonError("PREFILLED B2/B3 instret mismatch")
                completion_deltas.append(int(b3["completion_cycles"]) - int(b2["completion_cycles"]))
            observations.append({"hart_count": key[0], "mode": key[1],
                "repetition": repetition,
                "B2": prefilled_observation(b2_trace),
                "B3": prefilled_observation(b3_trace),
                "signature_matched": matched,
                "unpaired_reason": None if matched else "CAS participant/winner signature differs",
                "completion_cycles_B3_minus_B2": (int(b3["completion_cycles"]) -
                    int(b2["completion_cycles"])) if matched else None,
                "per_hart_cycles_B3_minus_B2": [int(h3["workload_cycles"]) -
                    int(h2["workload_cycles"]) for h2, h3 in zip(b2["harts"], b3["harts"])]
                    if matched else None})
        summaries.append({"hart_count": key[0], "mode": key[1],
                          "matched_pairings": len(completion_deltas),
                          "unmatched_pairings": 5 - len(completion_deltas),
                          "completion_cycles_B3_minus_B2": stats(completion_deltas)
                          if completion_deltas else None})

    modes = {campaign.mode for campaign in campaigns}
    if modes == {"architecture", "rvls"}:
        for harts in sorted({campaign.harts for campaign in campaigns}):
            for baseline in ("B2", "B3"):
                architecture = by_selection.get((harts, baseline, "architecture"))
                rvls = by_selection.get((harts, baseline, "rvls"))
                if architecture is None or rvls is None:
                    raise ComparisonError(f"missing cross-mode PREFILLED selection H{harts}/{baseline}")
                if common_signature(architecture) != common_signature(rvls):
                    raise ComparisonError(f"cross-mode configuration mismatch H{harts}/{baseline}")
                if architecture.document != rvls.document:
                    raise ComparisonError(f"architecture/RVLS samples differ H{harts}/{baseline}")
    elif len(modes) != 1:
        raise ComparisonError("PREFILLED mode set is incomplete")
    return {"schema": PREFILLED_COMPARISON_SCHEMA, "status": "PASS",
            "sources": source_rows(campaigns),
            "counts": {"sources": len(campaigns), "observations": len(observations),
                       "summaries": len(summaries)},
            "observations": observations, "summaries": summaries,
            "cross_mode_equal": modes == {"architecture", "rvls"}}


def prefilled_observation(row: dict[str, Any]) -> dict[str, Any]:
    return {"A": row["cas_attempts"], "attempting_harts": row["attempting_harts"],
            "winner_hart": row["winner_hart"], "loser_harts": row["loser_harts"],
            "observer_harts": row["observer_harts"],
            "physical_append_attempts": row["physical_attempts"],
            "committed_appends": row["committed"],
            "superseded_appends": row["superseded"],
            "append_amplification": row["append_amplification"],
            "superseded_ratio": row["superseded_ratio"]}


def source_rows(campaigns: list[Campaign]) -> list[dict[str, Any]]:
    return [{"samples": str(item.samples_path), "metadata": str(item.metadata_path),
             "trace_report": str(item.trace_path), "run_id": item.metadata["run_id"],
             "experiment_id": item.experiment, "block": item.block,
             "hart_count": item.harts, "workload": item.workload,
             "baseline": item.baseline, "mode": item.mode, "seed": item.seed,
             "elf_sha256": item.metadata["artifact"]["elf_sha256"]}
            for item in sorted(campaigns, key=lambda value: (
                value.harts, value.workload, value.block,
                value.metadata["launch_position"], value.mode))]


def comparison_document(campaigns: list[Campaign]) -> dict[str, Any]:
    validate_campaign_set(campaigns)
    return prefilled_document(campaigns) if campaigns[0].prefilled else ordinary_document(campaigns)


def csv_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    if document["schema"] == COMPARISON_SCHEMA:
        rows = []
        for summary in document["summaries"]:
            row = {field: summary[field] for field in
                   ("experiment_id", "isolation_block_id", "hart_count",
                    "workload", "mode", "simulation_seed", "measured_pairings")}
            for metric, values in summary["deltas"].items():
                for statistic, value in values.items():
                    row[f"{metric}_{statistic}"] = value
            for baseline, values in summary["baselines"].items():
                for metric, result in values.items():
                    row[f"{baseline}_{metric}_median"] = result["median"]
            rows.append(row)
        return rows
    return [{"hart_count": item["hart_count"], "mode": item["mode"],
             "matched_pairings": item["matched_pairings"],
             "unmatched_pairings": item["unmatched_pairings"],
             "completion_delta_median": (item["completion_cycles_B3_minus_B2"] or {}).get("median")}
            for item in document["summaries"]]


def write_outputs(document: dict[str, Any], output: Path) -> None:
    if output.exists():
        raise ComparisonError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        with (temporary / "comparison.json").open("w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        rows = csv_rows(document)
        with (temporary / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs=2, action="append", metavar=("SAMPLES", "METADATA"),
                        required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        campaigns = [load_campaign(Path(samples), Path(metadata))
                     for samples, metadata in args.input]
        document = comparison_document(campaigns)
        write_outputs(document, args.output_dir)
        counts = document["counts"]
        print(f"dirtygen perf mc comparison: PASS schema={document['schema']} "
              f"sources={counts['sources']}")
        return 0
    except (ComparisonError, OSError, ValueError) as error:
        print(f"dirtygen perf mc comparison: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
