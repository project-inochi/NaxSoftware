#!/usr/bin/env python3
"""Aggregate one JSON result per selected RTL-directed simulation."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--text", required=True, type=Path)
    args = parser.parse_args()

    expected = [line.strip() for line in args.expected.read_text().splitlines()
                if line.strip()]
    if len(expected) != len(set(expected)):
        raise SystemExit("campaign expected list contains duplicate run IDs")
    missing = [run_id for run_id in expected
               if not (args.results / f"{run_id}.json").is_file()]
    if missing:
        raise SystemExit(f"campaign results missing: {missing}")
    missing_invariants = [run_id for run_id in expected
                          if not (args.results / f"{run_id}.invariants.json").is_file()]
    if missing_invariants:
        raise SystemExit(f"campaign invariant reports missing: {missing_invariants}")
    # Family-specific parsers write <run>.arch.json beside the campaign result.
    # Those are supporting evidence, not independent campaign runs.
    extra = sorted(path.stem for path in args.results.glob("*.json")
                   if not path.name.endswith(".arch.json") and
                   not path.name.endswith(".invariants.json") and
                   path.stem not in set(expected))
    records = []
    for run_id in expected:
        record = json.loads((args.results / f"{run_id}.json").read_text())
        if record.get("status") != "PASS":
            raise SystemExit(f"campaign run did not pass: {run_id}")
        invariant = json.loads(
            (args.results / f"{run_id}.invariants.json").read_text())
        if invariant.get("status") != "PASS":
            raise SystemExit(f"campaign invariant check failed: {run_id}")
        record["run_id"] = run_id
        record["invariants"] = invariant
        records.append(record)
    totals = {
        "runs": len(records),
        # A missing RVLS trace is valid for architecture-only/hardware-style
        # runs, but it must remain visible in the aggregate rather than being
        # mistaken for a trace containing zero events.
        "trace_available_runs": sum(
            bool(r.get("trace_available", r.get("trace", {}).get("available", True)))
            for r in records),
        "trace_unavailable_runs": sum(
            not bool(r.get("trace_available", r.get("trace", {}).get("available", True)))
            for r in records),
        "mmu_stores": sum(r["trace"]["mmu_stores"] for r in records),
        "appends": sum(r["trace"]["appends"] for r in records),
        "pte_updates": sum(r["trace"]["pte_updates"] for r in records),
        "traps": sum(r["trace"]["traps"] for r in records),
        "dirty_log_faults": sum(r["trace"]["dirty_log_faults"] for r in records),
        "attribution_errors": sum(r["trace"]["attribution_errors"] for r in records),
        "invariant_failures": sum(
            sum(not passed for passed in r["invariants"]["checks"].values())
            for r in records),
        "architecture_evidence": dict(Counter(
            r["invariants"].get("architecture_evidence", "unknown")
            for r in records)),
    }
    summary = {
        "abi": 1, "status": "PASS", "totals": totals,
        "expected": expected, "extra_ignored": extra, "records": records,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = [
        "SHDLT RTL directed campaign: PASS",
        f"runs={totals['runs']} mmu_stores={totals['mmu_stores']} "
        f"appends={totals['appends']} pte_updates={totals['pte_updates']}",
        f"traps={totals['traps']} dirty_log_faults={totals['dirty_log_faults']} "
        f"attribution_errors={totals['attribution_errors']} "
        f"invariant_failures={totals['invariant_failures']} "
        f"trace_unavailable={totals['trace_unavailable_runs']} "
        f"architecture_evidence={','.join(sorted(totals['architecture_evidence']))}",
    ]
    lines.extend(f"PASS {run_id}" for run_id in expected)
    args.text.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
