#!/usr/bin/env python3
"""Summarize the complete E0/E1 dirty-epoch architecture comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from dirtygen_epoch_compare import COMPARISON_SCHEMA, METRICS, stats


SCHEMA = "shdlt-dirtygen-epoch-phase4-summary-v1"
CYCLE_METRICS = ("workload_cycles", "harvest_cycles", "pause_cycles",
                 "epoch_cycles")


class SummaryError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def selection_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["mode"], row["profile"], row["hart_count"], row["workload"],
            row["value"], row["simulation_seed"])


def summary_document(comparison: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    if comparison.get("schema") != COMPARISON_SCHEMA or \
            comparison.get("status") != "PASS":
        raise SummaryError("input is not a passing dirty-epoch comparison")
    counts = comparison.get("counts", {})
    if counts != {"sources": 68, "groups": 34, "measured_pairings": 170}:
        raise SummaryError(f"complete campaign cardinality mismatch: {counts}")
    if {row.get("trace_status") for row in comparison.get("sources", [])} != \
            {"NOT_COLLECTED"}:
        raise SummaryError("full architecture sources must use the no-trace policy")

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in comparison.get("pairings", []):
        if row.get("mode") != "architecture" or row.get("epoch_block_id") not in \
                ("E0", "E1"):
            raise SummaryError("unexpected mode or block in full comparison")
        grouped[selection_key(row)].append(row)
    if len(grouped) != 17:
        raise SummaryError(f"expected 17 selections, got {len(grouped)}")

    selections = []
    for key, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        if len(rows) != 10 or {row["epoch_block_id"] for row in rows} != {"E0", "E1"}:
            raise SummaryError(f"selection {key} lacks five E0 and five E1 pairings")
        for block in ("E0", "E1"):
            if len([row for row in rows if row["epoch_block_id"] == block]) != 5:
                raise SummaryError(f"selection {key} block {block} cardinality differs")
        selections.append({"mode": key[0], "profile": key[1],
            "hart_count": key[2], "workload": key[3], "value": key[4],
            "simulation_seed": key[5], "measured_pairings": len(rows),
            "blocks": {block: len([row for row in rows
                                     if row["epoch_block_id"] == block])
                       for block in ("E0", "E1")},
            "cycles": {backend: {metric: stats([
                int(row["cycles"][backend][metric]) for row in rows])
                for metric in CYCLE_METRICS}
                for backend in ("pte-scan-serial", "shdlt-log")},
            "metrics": {metric: stats([row["metrics"][metric] for row in rows
                                         if row["metrics"][metric] is not None])
                        if any(row["metrics"][metric] is not None for row in rows)
                        else None for metric in METRICS}})
    return {"schema": SCHEMA, "status": "PASS",
            "source_comparison_sha256": source_sha256,
            "statistics": "median,min,max,MAD,inclusive-IQR over paired E0+E1 samples",
            "counts": {"sources": 68, "backend_groups": 34,
                       "selections": 17, "raw_samples": 408,
                       "measured_samples": 340, "measured_pairings": 170},
            "selections": selections}


def csv_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in document["selections"]:
        row = {name: item[name] for name in
               ("mode", "profile", "hart_count", "workload", "value",
                "simulation_seed", "measured_pairings")}
        for backend, metrics in item["cycles"].items():
            for metric, values in metrics.items():
                for statistic, value in values.items():
                    row[f"{backend}_{metric}_{statistic}"] = value
        for metric, values in item["metrics"].items():
            if values is not None:
                for statistic, value in values.items():
                    row[f"{metric}_{statistic}"] = value
        result.append(row)
    return result


def write_outputs(document: dict[str, Any], output: Path) -> None:
    if output.exists():
        raise SummaryError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        with (temporary / "summary.json").open("w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        rows = csv_rows(document)
        with (temporary / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        comparison = json.loads(args.comparison.read_text())
        document = summary_document(comparison, sha256_file(args.comparison))
        write_outputs(document, args.output_dir)
        print("dirtygen epoch phase4 summary: PASS selections=17 pairings=170")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, SummaryError) as error:
        print(f"dirtygen epoch phase4 summary: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
