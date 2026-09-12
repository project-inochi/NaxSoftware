#!/usr/bin/env python3
"""Run fail-fast dirty-epoch smoke gates or the deferred full campaign."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from run_dirtygen_epoch import (BLOCKS, IDENTIFIER, find_repo_root, now,
                                source_fingerprint)
from run_dirtygen_perf import write_metadata


SCHEMA = "shdlt-dirtygen-epoch-phase3-campaign-v1"
SINGLE = (("unique", 1), ("unique", 8), ("unique", 32),
          ("unique", 128), ("repeat", 1), ("repeat", 8),
          ("repeat", 128), ("repeat", 4096))
MC = tuple((harts, workload) for harts in (1, 2, 4) for workload in
           ("private-strong", "private-weak", "same-pte"))


@dataclasses.dataclass(frozen=True)
class Selection:
    gate: str
    profile: str
    workload: str
    value: int | None
    harts: int
    backend: str
    block: str
    mode: str

    @property
    def key(self) -> str:
        value = "none" if self.value is None else str(self.value)
        return (f"{self.gate}:{self.block}:{self.mode}:{self.profile}:h{self.harts}:"
                f"{self.workload}:{value}:{self.backend}")

    @property
    def slug(self) -> str:
        value = f"-{self.value}" if self.value is not None else ""
        return (f"{self.gate}-{self.block.lower()}-{self.mode}-{self.profile}-"
                f"h{self.harts}-{self.workload}{value}-{self.backend}")

    def record(self) -> dict[str, Any]:
        return dataclasses.asdict(self) | {"key": self.key}


def _pairs(gate: str, configs: list[tuple[str, str, int | None, int]],
           block: str, mode: str) -> list[Selection]:
    return [Selection(gate, profile, workload, value, harts, backend, block, mode)
            for profile, workload, value, harts in configs
            for backend in BLOCKS[block]]


def architecture_smoke_schedule() -> list[Selection]:
    configs = [("single", "unique", 1, 1),
               ("single", "unique", 128, 1),
               ("single", "repeat", 4096, 1)]
    return _pairs("architecture-smoke", configs, "E0", "architecture")


def rvls_smoke_schedule() -> list[Selection]:
    configs = [("single", "unique", 128, 1),
               ("single", "repeat", 4096, 1),
               ("mc", "private-weak", None, 2),
               ("mc", "private-weak", None, 4),
               ("mc", "same-pte", None, 2),
               ("mc", "same-pte", None, 4)]
    return _pairs("rvls-smoke", configs, "E0", "rvls")


def full_architecture_schedule() -> list[Selection]:
    configs = [("single", workload, value, 1) for workload, value in SINGLE]
    configs += [("mc", workload, None, harts) for harts, workload in MC]
    rows = []
    for block in ("E0", "E1"):
        rows += _pairs("full-architecture", configs, block, "architecture")
    return rows


def selected_schedule(phase: str) -> list[Selection]:
    if phase == "architecture-smoke":
        return architecture_smoke_schedule()
    if phase == "rvls-smoke":
        return rvls_smoke_schedule()
    if phase == "stage3":
        return architecture_smoke_schedule() + rvls_smoke_schedule()
    return full_architecture_schedule()


def command_for(repo: Path, selection: Selection, experiment: str, seed: int,
                output: Path, host_timeout_seconds: int) -> list[str]:
    command = [sys.executable, str(repo / "ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_epoch.py"),
               "--profile", selection.profile, "--workload", selection.workload,
               "--hart-count", str(selection.harts), "--backend", selection.backend,
               "--epoch-block-id", selection.block, "--experiment-id", experiment,
               "--mode", selection.mode, "--seed", str(seed),
               "--host-timeout-seconds", str(host_timeout_seconds),
               "--output-root", str(output)]
    if selection.value is not None:
        command += ["--value", str(selection.value)]
    return command


def compare_command(repo: Path, roots: list[Path], output: Path) -> list[str]:
    command = [sys.executable, str(repo / "ext/NaxSoftware/benchmarks/dirtygen/tools/dirtygen_epoch_compare.py")]
    for root in roots:
        command += ["--input", str(root)]
    return command + ["--output-dir", str(output)]


def ensure_comparison(repo: Path, roots: list[Path], output: Path) -> None:
    if not output.exists():
        subprocess.run(compare_command(repo, roots, output), cwd=repo, check=True)
        return
    result = json.loads((output / "comparison.json").read_text())
    expected = {str(path) for path in roots}
    observed = {row["root"] for row in result.get("sources", [])}
    if (result.get("schema") != "shdlt-dirtygen-epoch-comparison-v1" or
            result.get("status") != "PASS" or observed != expected):
        raise RuntimeError(f"resume rejected: stale comparison {output}")


def command_fingerprint(command: list[str], source: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"command": command,
        "source": source["digest"]}, sort_keys=True).encode()).hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("architecture-smoke", "rvls-smoke",
                        "stage3", "full-architecture"), default="stage3")
    parser.add_argument("--experiment-id", default="epoch-phase3-20260912")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--host-timeout-seconds", type=int, default=1800)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not IDENTIFIER.fullmatch(args.experiment_id) or len(args.experiment_id) > 64:
        parser.error("invalid experiment id")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.limit is not None and args.limit % 2:
        parser.error("--limit must preserve complete backend pairs")
    if args.host_timeout_seconds < 1:
        parser.error("--host-timeout-seconds must be positive")
    if args.start_index < 0 or args.start_index % 2:
        parser.error("--start-index must be a non-negative backend-pair boundary")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = find_repo_root(Path(__file__))
    full_schedule = selected_schedule(args.phase)
    if args.start_index >= len(full_schedule):
        raise RuntimeError("--start-index is outside the selected schedule")
    schedule = full_schedule[args.start_index:]
    if args.limit is not None:
        schedule = schedule[:args.limit]
    if args.dry_run:
        print(json.dumps({"schema": SCHEMA, "phase": args.phase,
            "start_index": args.start_index,
            "host_timeout_seconds": args.host_timeout_seconds,
            "selection_count": len(schedule), "raw_sample_count": len(schedule) * 6,
            "measured_sample_count": len(schedule) * 5,
            "selections": [item.record() for item in schedule]}, indent=2, sort_keys=True))
        return 0
    root = args.output_root or (repo / "ext/NaxSoftware/benchmarks/dirtygen/build/campaign/dirtygen-epoch-phase3" / args.experiment_id)
    manifest_path = root / "manifest.json"
    source = source_fingerprint(repo)
    if manifest_path.exists():
        if not args.resume:
            raise RuntimeError(f"campaign already exists: {root}")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema") != SCHEMA or manifest.get("phase") != args.phase or \
                manifest.get("seed") != args.seed or manifest.get("source_fingerprint") != source or \
                manifest.get("start_index") != args.start_index or \
                manifest.get("host_timeout_seconds") != args.host_timeout_seconds:
            raise RuntimeError("resume rejected: schema, phase, seed, schedule window, timeout, or source fingerprint changed")
    else:
        if root.exists():
            raise RuntimeError(f"output root exists without manifest: {root}")
        root.mkdir(parents=True)
        manifest = {"schema": SCHEMA, "status": "initialized", "phase": args.phase,
                    "experiment_id": args.experiment_id, "seed": args.seed,
                    "start_index": args.start_index,
                    "host_timeout_seconds": args.host_timeout_seconds,
                    "start_time": now(), "end_time": None,
                    "source_fingerprint": source,
                    "planned_selection_count": len(schedule),
                    "planned_raw_sample_count": len(schedule) * 6,
                    "planned_measured_sample_count": len(schedule) * 5,
                    "serial_execution": True,
                    "runs": [item.record() | {"status": "pending", "attempts": []}
                             for item in schedule], "comparisons": {}}
        write_metadata(manifest_path, manifest)
    rows = {row["key"]: row for row in manifest["runs"]}
    if set(rows) != {item.key for item in schedule}:
        raise RuntimeError("resume rejected: schedule changed")
    manifest["status"] = "running"; write_metadata(manifest_path, manifest)
    try:
        completed_roots: list[Path] = []
        current_gate = None
        gate_roots: list[Path] = []
        for index, selection in enumerate(schedule):
            row = rows[selection.key]
            if current_gate is not None and selection.gate != current_gate:
                output = root / f"{current_gate}-comparison"
                ensure_comparison(repo, gate_roots, output)
                manifest["comparisons"][current_gate] = str(output.relative_to(root))
                gate_roots = []
                write_metadata(manifest_path, manifest)
            current_gate = selection.gate
            if row["status"] == "passed":
                run_root = Path(row["attempts"][-1]["output"])
                completed_roots.append(run_root); gate_roots.append(run_root)
                continue
            attempt = len(row["attempts"]) + 1
            run_root = root / "runs" / f"{index:03d}-{selection.slug}" / f"attempt-{attempt}"
            command = command_for(repo, selection, args.experiment_id, args.seed,
                                  run_root, args.host_timeout_seconds)
            record = {"attempt": attempt, "start_time": now(), "end_time": None,
                      "output": str(run_root), "command": command,
                      "command_fingerprint": command_fingerprint(command, source),
                      "exit_code": None}
            row["status"] = "running"; row["attempts"].append(record)
            write_metadata(manifest_path, manifest)
            code = subprocess.run(command, cwd=repo, check=False).returncode
            record["exit_code"] = code; record["end_time"] = now()
            row["status"] = "passed" if code == 0 else "failed"
            write_metadata(manifest_path, manifest)
            if code:
                raise RuntimeError(f"fail-fast selection {selection.key} exited {code}")
            completed_roots.append(run_root); gate_roots.append(run_root)
        if gate_roots and current_gate is not None:
            output = root / f"{current_gate}-comparison"
            ensure_comparison(repo, gate_roots, output)
            manifest["comparisons"][current_gate] = str(output.relative_to(root))
        if len({item.gate for item in schedule}) > 1:
            output = root / "stage-comparison"
            ensure_comparison(repo, completed_roots, output)
            manifest["comparisons"]["stage"] = str(output.relative_to(root))
        manifest["status"] = "passed"; manifest["end_time"] = now()
        manifest.pop("failure", None); write_metadata(manifest_path, manifest)
        return 0
    except BaseException as error:
        manifest["status"] = "failed"; manifest["end_time"] = now()
        manifest["failure"] = str(error); write_metadata(manifest_path, manifest)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
