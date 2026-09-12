#!/usr/bin/env python3
"""Run the complete trace-on-failure dirty-epoch architecture campaign."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from run_dirtygen_epoch import (BLOCKS, IDENTIFIER, build_command, elf_path,
                                fingerprints, find_repo_root, now,
                                source_fingerprint, validate_selection)
from run_dirtygen_perf import write_metadata


SCHEMA = "shdlt-dirtygen-epoch-phase4-campaign-v1"
TRACE_POLICY = "on-failure"


@dataclasses.dataclass(frozen=True)
class Config:
    profile: str
    workload: str
    value: int | None
    harts: int

    @property
    def key(self) -> str:
        value = "none" if self.value is None else str(self.value)
        return f"{self.profile}:h{self.harts}:{self.workload}:{value}"

    @property
    def slug(self) -> str:
        value = f"-{self.value}" if self.value is not None else ""
        return f"{self.profile}-h{self.harts}-{self.workload}{value}"


@dataclasses.dataclass(frozen=True)
class Selection:
    config: Config
    backend: str
    block: str

    @property
    def key(self) -> str:
        return f"{self.block}:{self.config.key}:{self.backend}"

    def record(self) -> dict[str, Any]:
        return dataclasses.asdict(self.config) | {
            "key": self.key, "backend": self.backend, "block": self.block}


@dataclasses.dataclass(frozen=True)
class Pair:
    ordinal: int
    config: Config
    block: str

    @property
    def key(self) -> str:
        return f"{self.block}:{self.config.key}"

    @property
    def selections(self) -> tuple[Selection, Selection]:
        return tuple(Selection(self.config, backend, self.block)
                     for backend in BLOCKS[self.block])  # type: ignore[return-value]

    def record(self) -> dict[str, Any]:
        return {"key": self.key, "ordinal": self.ordinal,
                "block": self.block, **dataclasses.asdict(self.config),
                "launch_order": list(BLOCKS[self.block]), "status": "pending",
                "selections": [selection.record() | {"status": "pending",
                                                       "attempts": []}
                               for selection in self.selections]}


def configurations() -> list[Config]:
    single = [Config("single", workload, value, 1)
              for workload, values in (("unique", (1, 8, 32, 128)),
                                       ("repeat", (1, 8, 128, 4096)))
              for value in values]
    mc = [Config("mc", workload, None, harts) for harts in (1, 2, 4)
          for workload in ("private-strong", "private-weak", "same-pte")]
    return single + mc


def priority(config: Config) -> tuple[Any, ...]:
    # Fresh processes do not share DUT state. Longest-first minimizes the block tail.
    return (-config.harts, config.profile != "mc", config.workload,
            -1 if config.value is None else config.value)


def pair_schedule() -> list[Pair]:
    configs = configurations()
    canary = next(config for config in configs
                  if config.profile == "single" and config.workload == "unique" and
                  config.value == 1)
    pairs: list[Pair] = []
    ordinal = 0
    for block in ("E0", "E1"):
        ordered = sorted(configs, key=priority)
        if block == "E0":
            ordered.remove(canary); ordered.insert(0, canary)
        for config in ordered:
            pairs.append(Pair(ordinal, config, block)); ordinal += 1
    return pairs


def artifact_key(config: Config, backend: str) -> str:
    return f"{config.key}:{backend}"


def run_command(repo: Path, selection: Selection, experiment: str, seed: int,
                timeout: int, output: Path, artifact: dict[str, Any],
                source_digest: str, trace_mode: str) -> list[str]:
    command = [sys.executable, str(repo / "ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_epoch.py"),
               "--profile", selection.config.profile, "--workload",
               selection.config.workload, "--hart-count", str(selection.config.harts),
               "--backend", selection.backend, "--epoch-block-id", selection.block,
               "--experiment-id", experiment, "--mode", "architecture",
               "--trace-mode", trace_mode, "--seed", str(seed),
               "--host-timeout-seconds", str(timeout), "--output-root", str(output),
               "--prebuilt-elf-sha256", artifact["elf_sha256"],
               "--expected-source-fingerprint", source_digest]
    if selection.config.value is not None:
        command += ["--value", str(selection.config.value)]
    return command


def compare_command(repo: Path, roots: list[Path], output: Path) -> list[str]:
    command = [sys.executable, str(repo / "ext/NaxSoftware/benchmarks/dirtygen/tools/dirtygen_epoch_compare.py")]
    for root in roots:
        command += ["--input", str(root)]
    return command + ["--output-dir", str(output)]


def group_environment(repo: Path, root: Path, config: Config,
                      clone_lock: threading.Lock) -> dict[str, str]:
    """Give every concurrently executable config private Sim and Mill state."""
    environment = os.environ.copy()
    environment["SPINALSIM_WORKSPACE"] = str(
        root / "parallel-workspaces" / config.slug)
    clone_parent = root / "parallel-mill-out-v1"
    clone = clone_parent / config.slug
    marker = clone / ".phase4-reflink-complete.json"
    with clone_lock:
        clone_parent.mkdir(parents=True, exist_ok=True)
        if clone.exists() and not marker.is_file():
            raise RuntimeError(f"incomplete Mill output clone: {clone}")
        if not clone.exists():
            source = repo / "out"
            if not (source / "mill-launcher").is_dir():
                raise RuntimeError("cannot clone an incomplete Mill output cache")
            subprocess.run(["cp", "-a", "--reflink=always", str(source), str(clone)],
                           cwd=repo, check=True)
            write_metadata(marker, {"schema": "shdlt-phase4-mill-reflink-v1",
                                    "created_at": now(), "source": str(source)})
    environment["MILL_OUTPUT_DIR"] = str(clone)
    return environment


def prebuild(repo: Path, root: Path, manifest: dict[str, Any],
             save: Any) -> None:
    if manifest["artifacts"]:
        for key, artifact in manifest["artifacts"].items():
            path = Path(artifact["path"])
            if not path.is_file() or fingerprints(path, artifact["profile"],
                                                   artifact["workload"]) != \
                    artifact["fingerprints"]:
                raise RuntimeError(f"prebuilt artifact changed: {key}")
        return
    directory = root / "prebuild"
    directory.mkdir()
    artifacts = {}
    for config in configurations():
        for backend in ("pte-scan-serial", "shdlt-log"):
            key = artifact_key(config, backend)
            command = build_command(repo, config.profile, config.workload,
                                    config.value, config.harts, backend)
            log = directory / (key.replace(":", "-") + ".log")
            with log.open("w", encoding="utf-8") as stream:
                code = subprocess.run(command, cwd=repo, stdout=stream,
                                      stderr=subprocess.STDOUT, check=False).returncode
            if code:
                raise RuntimeError(f"prebuild {key} exited {code}")
            path = elf_path(repo, config.profile, config.workload, config.value,
                            config.harts, backend)
            if not path.is_file():
                raise RuntimeError(f"prebuild {key} did not produce {path}")
            artifact = fingerprints(path, config.profile, config.workload)
            validate_selection(artifact, config.profile, config.workload,
                               config.value, config.harts, backend)
            artifacts[key] = {"path": str(path), "profile": config.profile,
                              "workload": config.workload,
                              "fingerprints": artifact, **artifact}
    for config in configurations():
        scan = artifacts[artifact_key(config, "pte-scan-serial")]
        log = artifacts[artifact_key(config, "shdlt-log")]
        for name in ("workload_code_sha256", "timed_window_sha256"):
            if scan[name] != log[name]:
                raise RuntimeError(f"{config.key} backend {name} differs")
    manifest["artifacts"] = artifacts
    manifest["prebuild_end_time"] = now()
    save()


def metadata_passed(path: Path, trace_mode: str) -> bool:
    try:
        data = json.loads((path / "metadata.json").read_text())
        trace = json.loads((path / "report/trace-report.json").read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    expected_trace = "PASS" if trace_mode == "required" else "NOT_COLLECTED"
    return data.get("status") == "passed" and data.get("exit_code") == 0 and \
        data.get("trace_mode") == trace_mode and trace.get("status") == expected_trace


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", default="epoch-phase4-20260913-full")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--host-timeout-seconds", type=int, default=5400)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not IDENTIFIER.fullmatch(args.experiment_id) or len(args.experiment_id) > 64:
        parser.error("invalid experiment id")
    if args.jobs < 1 or args.jobs > 4:
        parser.error("--jobs must be in 1..4")
    if args.host_timeout_seconds < 1:
        parser.error("--host-timeout-seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = find_repo_root(Path(__file__))
    pairs = pair_schedule()
    if args.dry_run:
        print(json.dumps({"schema": SCHEMA, "trace_policy": TRACE_POLICY,
            "jobs": args.jobs, "host_timeout_seconds": args.host_timeout_seconds,
            "pair_count": len(pairs), "selection_count": len(pairs) * 2,
            "raw_sample_count": len(pairs) * 12,
            "measured_sample_count": len(pairs) * 10,
            "measured_pairing_count": len(pairs) * 5,
            "pairs": [pair.record() for pair in pairs]}, indent=2, sort_keys=True))
        return 0

    root = args.output_root or (repo / "ext/NaxSoftware/benchmarks/dirtygen/build/campaign/dirtygen-epoch-phase4" / args.experiment_id)
    manifest_path = root / "manifest.json"
    source = source_fingerprint(repo)
    lock = threading.RLock()
    if manifest_path.exists():
        if not args.resume:
            raise RuntimeError(f"campaign already exists: {root}")
        manifest = json.loads(manifest_path.read_text())
        fixed = (manifest.get("schema") == SCHEMA and manifest.get("seed") == args.seed and
                 manifest.get("jobs") == args.jobs and
                 manifest.get("host_timeout_seconds") == args.host_timeout_seconds and
                 manifest.get("trace_policy") == TRACE_POLICY and
                 manifest.get("source_fingerprint") == source)
        selection_states = [selection.get("status")
                            for pair in manifest.get("pairs", [])
                            for selection in pair.get("selections", [])]
        if not fixed or manifest.get("status") in ("failed", "passed") or \
                "running" in selection_states:
            raise RuntimeError("resume rejected: fingerprint/config changed or campaign failed")
    else:
        if root.exists():
            raise RuntimeError(f"output root exists without manifest: {root}")
        root.mkdir(parents=True)
        manifest = {"schema": SCHEMA, "status": "initialized",
            "experiment_id": args.experiment_id, "seed": args.seed,
            "jobs": args.jobs, "host_timeout_seconds": args.host_timeout_seconds,
            "trace_policy": TRACE_POLICY, "start_time": now(), "end_time": None,
            "source_fingerprint": source, "prebuild_end_time": None,
            "artifacts": {}, "pair_count": 34, "selection_count": 68,
            "raw_sample_count": 408, "measured_sample_count": 340,
            "measured_pairing_count": 170, "canary": pairs[0].key,
            "blocks_serial": True, "pair_serial": True,
            "comparisons": {}, "summary": None, "diagnostic": None,
            "pairs": [pair.record() for pair in pairs]}
        write_metadata(manifest_path, manifest)

    def save() -> None:
        with lock:
            write_metadata(manifest_path, manifest)

    try:
        manifest["status"] = "prebuilding"; save()
        prebuild(repo, root, manifest, save)
    except BaseException as error:
        manifest["status"] = "failed"; manifest["end_time"] = now()
        manifest["failure"] = {"stage": "prebuild", "internal_error": repr(error)}
        save(); raise
    rows = {row["key"]: row for row in manifest["pairs"]}
    if set(rows) != {pair.key for pair in pairs}:
        raise RuntimeError("resume rejected: pair schedule changed")
    stop = threading.Event()
    first_failure: list[dict[str, Any]] = []
    clone_lock = threading.Lock()

    def run_pair(pair: Pair) -> None:
        environment = group_environment(repo, root, pair.config, clone_lock)
        pair_row = rows[pair.key]
        if pair_row["status"] == "passed":
            return
        with lock:
            pair_row["status"] = "running"; save()
        selection_rows = {row["key"]: row for row in pair_row["selections"]}
        for selection in pair.selections:
            row = selection_rows[selection.key]
            if row["status"] == "passed":
                if not metadata_passed(Path(row["attempts"][-1]["output"]), "disabled"):
                    raise RuntimeError(f"passing output became invalid: {selection.key}")
                continue
            if stop.is_set():
                with lock:
                    row["status"] = "stopped"
                    pair_row["status"] = "stopped"; save()
                return
            attempt = len(row["attempts"]) + 1
            output = root / "runs" / f"{pair.ordinal:02d}-{pair.block.lower()}-{pair.config.slug}" / selection.backend / f"attempt-{attempt}"
            artifact = manifest["artifacts"][artifact_key(pair.config, selection.backend)]
            command = run_command(repo, selection, args.experiment_id, args.seed,
                                  args.host_timeout_seconds, output, artifact,
                                  source["digest"], "disabled")
            record = {"attempt": attempt, "start_time": now(), "end_time": None,
                      "output": str(output), "command": command, "exit_code": None}
            with lock:
                row["status"] = "running"; row["attempts"].append(record)
                record["execution_environment"] = {
                    "SPINALSIM_WORKSPACE": environment["SPINALSIM_WORKSPACE"],
                    "MILL_OUTPUT_DIR": environment["MILL_OUTPUT_DIR"]}
                save()
            code = subprocess.run(command, cwd=repo, env=environment,
                                  check=False).returncode
            with lock:
                record["exit_code"] = code; record["end_time"] = now()
                row["status"] = "passed" if code == 0 else "failed"
                if code:
                    pair_row["status"] = "failed"; stop.set()
                    if not first_failure:
                        first_failure.append({"selection": selection.record(),
                                              "output": str(output), "exit_code": code})
                    save()
                else:
                    save()
            if code:
                return
        with lock:
            pair_row["status"] = "passed"; save()

    def run_batch(batch: list[Pair], jobs: int) -> None:
        pending = iter(batch)
        active: dict[concurrent.futures.Future[None], Pair] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            def launch() -> None:
                while not stop.is_set() and len(active) < jobs:
                    try:
                        pair = next(pending)
                    except StopIteration:
                        return
                    active[pool.submit(run_pair, pair)] = pair
            launch()
            while active:
                done, _ = concurrent.futures.wait(active,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    pair = active.pop(future)
                    try:
                        future.result()
                    except BaseException as error:
                        stop.set()
                        with lock:
                            rows[pair.key]["status"] = "failed"
                            if not first_failure:
                                first_failure.append({"selection": None,
                                    "output": None, "exit_code": 1,
                                    "internal_error": repr(error)})
                            save()
                launch()

    def passing_roots(block: str | None = None) -> list[Path]:
        roots = []
        for pair in pairs:
            if block is not None and pair.block != block:
                continue
            row = rows[pair.key]
            if row["status"] != "passed":
                continue
            for selection in row["selections"]:
                roots.append(Path(selection["attempts"][-1]["output"]))
        return roots

    def compare(block: str | None) -> None:
        label = block.lower() if block is not None else "complete"
        output = root / "comparison" / label
        roots = passing_roots(block)
        expected = 34 if block is not None else 68
        if len(roots) != expected:
            raise RuntimeError(f"{label} comparison has {len(roots)} of {expected} sources")
        if output.exists():
            document = json.loads((output / "comparison.json").read_text())
            observed = {row["root"] for row in document.get("sources", [])}
            if document.get("status") != "PASS" or observed != {str(path) for path in roots}:
                raise RuntimeError(f"stale {label} comparison")
        else:
            code = subprocess.run(compare_command(repo, roots, output), cwd=repo,
                                  check=False).returncode
            if code:
                raise RuntimeError(f"{label} comparison exited {code}")
        manifest["comparisons"][label] = str(output.relative_to(root)); save()

    try:
        manifest["status"] = "running"; save()
        canary = pairs[0]
        if rows[canary.key]["status"] != "passed":
            run_batch([canary], 1)
        if not stop.is_set():
            run_batch([pair for pair in pairs if pair.block == "E0" and pair != canary],
                      args.jobs)
        if not stop.is_set():
            compare("E0")
            run_batch([pair for pair in pairs if pair.block == "E1"], args.jobs)
        if not stop.is_set():
            compare("E1"); compare(None)
            comparison = root / manifest["comparisons"]["complete"] / "comparison.json"
            output = root / "summary"
            command = [sys.executable, str(repo / "ext/NaxSoftware/benchmarks/dirtygen/tools/collect_dirtygen_epoch_phase4.py"),
                       "--comparison", str(comparison), "--output-dir", str(output)]
            if subprocess.run(command, cwd=repo, check=False).returncode:
                raise RuntimeError("phase4 summary failed")
            manifest["summary"] = str(output.relative_to(root))
            manifest["status"] = "passed"; manifest["end_time"] = now(); save()
            return 0

        failure = first_failure[0]
        if failure.get("selection") is not None:
            selection_data = failure["selection"]
            config = Config(selection_data["profile"], selection_data["workload"],
                            selection_data["value"], selection_data["harts"])
            selection = Selection(config, selection_data["backend"],
                                  selection_data["block"])
            artifact = manifest["artifacts"][artifact_key(config, selection.backend)]
            output = root / "diagnostics" / selection.key.replace(":", "-") / "attempt-1"
            command = run_command(repo, selection, args.experiment_id, args.seed,
                                  args.host_timeout_seconds, output, artifact,
                                  source["digest"], "required")
            environment = group_environment(repo, root, config, clone_lock)
            code = subprocess.run(command, cwd=repo, env=environment,
                                  check=False).returncode
            manifest["diagnostic"] = {"selection": selection.record(),
                                      "output": str(output), "command": command,
                                      "exit_code": code, "trace_requested": True,
                                      "execution_environment": {
                                          "SPINALSIM_WORKSPACE":
                                              environment["SPINALSIM_WORKSPACE"],
                                          "MILL_OUTPUT_DIR":
                                              environment["MILL_OUTPUT_DIR"]}}
        manifest["status"] = "failed"; manifest["end_time"] = now()
        manifest["failure"] = failure; save()
        return int(failure.get("exit_code") or 1)
    except BaseException as error:
        manifest["status"] = "failed"; manifest["end_time"] = now()
        manifest["failure"] = {"internal_error": repr(error)}; save()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
