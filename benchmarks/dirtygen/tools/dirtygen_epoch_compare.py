#!/usr/bin/env python3
"""Strictly pair PTE-scan and SHDLT-log dirty-epoch fresh processes."""

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


METADATA_SCHEMA = "shdlt-dirtygen-epoch-campaign-v1"
SAMPLES_SCHEMA = "shdlt-dirtygen-epoch-samples-v1"
TRACE_SCHEMA = "shdlt-dirtygen-epoch-trace-v1"
COMPARISON_SCHEMA = "shdlt-dirtygen-epoch-comparison-v1"
BLOCKS = {"E0": ("pte-scan-serial", "shdlt-log"),
          "E1": ("shdlt-log", "pte-scan-serial")}
METRICS = ("runtime_overhead", "harvest_saving", "pause_saving",
           "net_epoch_gain", "workload_speedup", "harvest_speedup",
           "pause_speedup", "epoch_speedup")


class ComparisonError(RuntimeError):
    pass


@dataclass
class Campaign:
    root: Path
    metadata: dict[str, Any]
    samples: dict[str, Any]
    trace: dict[str, Any]

    @property
    def backend(self) -> str:
        return str(self.metadata["backend"])

    @property
    def key(self) -> tuple[Any, ...]:
        return (self.metadata["mode"], self.metadata["experiment_id"],
                self.metadata["epoch_block_id"], self.metadata["profile"],
                self.metadata["hart_count"], self.metadata["workload"],
                self.metadata["value"], self.metadata["simulation_seed"])


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ComparisonError(f"{path} is not a JSON object")
    return value


def load_campaign(root: Path) -> Campaign:
    metadata = load_json(root / "metadata.json")
    samples = load_json(root / "report/samples.json")
    trace = load_json(root / "report/trace-report.json")
    if metadata.get("schema") != METADATA_SCHEMA or metadata.get("status") != "passed" or metadata.get("exit_code") != 0:
        raise ComparisonError(f"{root} campaign metadata is not a passing epoch run")
    if samples.get("schema") != SAMPLES_SCHEMA:
        raise ComparisonError(f"{root} has an unsupported samples schema")
    if trace.get("schema") != TRACE_SCHEMA or trace.get("status") != "PASS":
        raise ComparisonError(f"{root} has an invalid trace report")
    if samples.get("profile") != metadata.get("profile") or \
            trace.get("profile") != metadata.get("profile") or \
            trace.get("backend") != metadata.get("backend"):
        raise ComparisonError(f"{root} mixes profile/backend schemas")
    if metadata.get("backend") not in ("pte-scan-serial", "shdlt-log"):
        raise ComparisonError(f"{root} has an invalid backend")
    if metadata.get("epoch_block_id") not in BLOCKS:
        raise ComparisonError(f"{root} has an invalid epoch block")
    if (len(samples.get("samples", [])) != 6 or
            samples.get("end", {}).get("status") != 0 or
            len(trace.get("samples", [])) != 6):
        raise ComparisonError(f"{root} has incomplete firmware or trace samples")
    return Campaign(root, metadata, samples, trace)


def parse_time(value: Any, name: str) -> datetime.datetime:
    if not isinstance(value, str):
        raise ComparisonError(f"missing {name}")
    try:
        result = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        raise ComparisonError(f"invalid {name}") from error
    if result.tzinfo is None:
        raise ComparisonError(f"{name} lacks timezone")
    return result


def compatibility(campaign: Campaign) -> tuple[Any, ...]:
    metadata = campaign.metadata
    artifact = metadata.get("artifact", {})
    repos = metadata.get("repositories", {})
    heads = tuple((name, value.get("head")) for name, value in sorted(repos.items()))
    toolchain = metadata.get("toolchain", {})
    versions = tuple((name, value.get("path"), value.get("version"), value.get("sha256"))
                     for name, value in sorted(toolchain.items()) if isinstance(value, dict))
    return (metadata.get("profile"), metadata.get("hart_count"),
            metadata.get("workload"), metadata.get("value"),
            metadata.get("mode"), metadata.get("simulation_seed"),
            json.dumps(metadata.get("cpu_config"), sort_keys=True), heads, versions,
            artifact.get("workload_code_sha256"),
            artifact.get("timed_window_sha256"),
            metadata.get("source_fingerprint", {}).get("digest"),
            json.dumps(metadata.get("top_level_gitlinks"), sort_keys=True))


def measured(campaign: Campaign) -> dict[int, dict[str, Any]]:
    rows = {int(row["repetition"]): row for row in campaign.samples["samples"]
            if int(row["warmup"]) == 0}
    if set(rows) != set(range(5)):
        raise ComparisonError(f"{campaign.root} measured repetitions are incomplete")
    return rows


def functional_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    harts = tuple((hart["hart"], hart["operations"], hart["workload_instret"],
                   hart["scause"], hart["status"]) for hart in row.get("harts", []))
    return (row["canonical_bitmap0"], row["canonical_bitmap1"],
            row["expected_bitmap0"], row["expected_bitmap1"],
            row["canonical_dirty_pages"], row["missing"], row["extra"],
            row["rearm_pages"], row["pte_errors"], row["data_errors"],
            row["status"], row.get("workload_instret"), harts)


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def pair_metrics(scan: dict[str, Any], log: dict[str, Any]) -> dict[str, Any]:
    sw, lw = int(scan["workload_cycles"]), int(log["workload_cycles"])
    sh, lh = int(scan["harvest_cycles"]), int(log["harvest_cycles"])
    sp, lp = int(scan["pause_cycles"]), int(log["pause_cycles"])
    se, le = int(scan["epoch_cycles"]), int(log["epoch_cycles"])
    return {"runtime_overhead": lw - sw, "harvest_saving": sh - lh,
            "pause_saving": sp - lp, "net_epoch_gain": se - le,
            "workload_speedup": ratio(sw, lw),
            "harvest_speedup": ratio(sh, lh),
            "pause_speedup": ratio(sp, lp), "epoch_speedup": ratio(se, le)}


def median(values: list[int | float]) -> int | float:
    value = statistics.median(values)
    return int(value) if isinstance(value, float) and value.is_integer() else value


def stats(values: list[int | float]) -> dict[str, int | float]:
    if not values:
        raise ComparisonError("cannot summarize an empty metric")
    center = median(values)
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return {"median": center, "min": min(values), "max": max(values),
            "mad": median([abs(value - center) for value in values]),
            "q1": quartiles[0], "q3": quartiles[2],
            "iqr": quartiles[2] - quartiles[0]}


def comparison_document(campaigns: list[Campaign]) -> dict[str, Any]:
    if not campaigns:
        raise ComparisonError("no campaign inputs")
    run_ids = [item.metadata.get("process_run_id") for item in campaigns]
    if None in run_ids or len(run_ids) != len(set(run_ids)):
        raise ComparisonError("fresh process run ids are missing or duplicated")
    groups: dict[tuple[Any, ...], list[Campaign]] = defaultdict(list)
    for campaign in campaigns:
        groups[campaign.key].append(campaign)
    pairings, summaries = [], []
    for key, group in sorted(groups.items(), key=lambda item: str(item[0])):
        block = key[2]
        if len(group) != 2 or {item.backend for item in group} != set(BLOCKS[block]):
            raise ComparisonError(f"group {key} must contain exactly one of each backend")
        if len({compatibility(item) for item in group}) != 1:
            raise ComparisonError(f"group {key} CPU/HEAD/toolchain/code/config mismatch")
        ordered = sorted(group, key=lambda item: int(item.metadata["launch_position"]))
        if tuple(item.backend for item in ordered) != BLOCKS[block]:
            raise ComparisonError(f"group {key} launch order does not match {block}")
        if parse_time(ordered[0].metadata["end_time"], "end_time") > \
                parse_time(ordered[1].metadata["start_time"], "start_time"):
            raise ComparisonError(f"group {key} processes overlap or ran out of order")
        selected = {item.backend: item for item in group}
        rows = {backend: measured(item) for backend, item in selected.items()}
        group_pairs = []
        for repetition in range(5):
            scan, log = rows["pte-scan-serial"][repetition], rows["shdlt-log"][repetition]
            if functional_signature(scan) != functional_signature(log):
                raise ComparisonError(f"group {key} repetition {repetition} functional/instret mismatch")
            metrics = pair_metrics(scan, log)
            item = {"mode": key[0], "experiment_id": key[1],
                    "epoch_block_id": key[2], "profile": key[3],
                    "hart_count": key[4], "workload": key[5], "value": key[6],
                    "simulation_seed": key[7], "repetition": repetition,
                    "canonical_bitmap": [scan["canonical_bitmap0"], scan["canonical_bitmap1"]],
                    "workload_instret": scan.get("workload_instret"),
                    "per_hart_instret": [hart["workload_instret"] for hart in scan.get("harts", [])],
                    "cycles": {"pte-scan-serial": {name: scan[name] for name in
                                ("workload_cycles", "harvest_cycles", "pause_cycles", "epoch_cycles")},
                               "shdlt-log": {name: log[name] for name in
                                ("workload_cycles", "harvest_cycles", "pause_cycles", "epoch_cycles")}},
                    "metrics": metrics}
            pairings.append(item); group_pairs.append(item)
        summaries.append({"mode": key[0], "experiment_id": key[1],
                          "epoch_block_id": key[2], "profile": key[3],
                          "hart_count": key[4], "workload": key[5],
                          "value": key[6], "simulation_seed": key[7],
                          "measured_pairings": len(group_pairs),
                          "metrics": {metric: (stats([item["metrics"][metric]
                                                     for item in group_pairs
                                                     if item["metrics"][metric] is not None])
                                               if any(item["metrics"][metric] is not None
                                                      for item in group_pairs) else None)
                                      for metric in METRICS}})
    return {"schema": COMPARISON_SCHEMA, "status": "PASS",
            "pairing_method": "same repetition before aggregation",
            "statistics": "median,min,max,MAD,inclusive-IQR over measured samples",
            "counts": {"sources": len(campaigns), "groups": len(groups),
                       "measured_pairings": len(pairings)},
            "sources": [{"root": str(item.root),
                         "run_id": item.metadata["process_run_id"],
                         "backend": item.backend,
                         "elf_sha256": item.metadata["artifact"]["elf_sha256"]}
                        for item in campaigns],
            "pairings": pairings, "summaries": summaries}


def csv_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for summary in document["summaries"]:
        row = {name: summary[name] for name in
               ("mode", "experiment_id", "epoch_block_id", "profile",
                "hart_count", "workload", "value", "simulation_seed",
                "measured_pairings")}
        for metric, values in summary["metrics"].items():
            if values is not None:
                for statistic, value in values.items():
                    row[f"{metric}_{statistic}"] = value
        rows.append(row)
    return rows


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
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True,
                        help="fresh-process run directory; repeat for both backends")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        document = comparison_document([load_campaign(path) for path in args.input])
        write_outputs(document, args.output_dir)
        print(f"dirtygen epoch comparison: PASS sources={document['counts']['sources']} "
              f"pairings={document['counts']['measured_pairings']}")
        return 0
    except (ComparisonError, OSError, ValueError) as error:
        print(f"dirtygen epoch comparison: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
