#!/usr/bin/env python3
"""Run isolated, safely resumable SHDLT multi-hart phase-3 campaigns."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import hashlib
import json
import os
import signal
import statistics
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from run_dirtygen_perf import elf_fingerprints as legacy_elf_fingerprints
from run_dirtygen_perf import repository_states
from run_dirtygen_perf_mc import (BLOCKS, IDENTIFIER, elf_path,
                                  find_repo_root)


SCHEMA = "shdlt-dirtygen-perf-mc-phase3-campaign-v1"
GATE_SCHEMA = "shdlt-dirtygen-perf-mc-phase3-rvls-gate-v1"
ORDINARY = ("private-strong", "private-weak", "same-pte")
GATE_WORKLOADS = ("private-weak", "same-pte", "prefilled-same-pte")
MC_TIMED_WINDOW_SHA256 = (
    "43350c303f71381027e8f379d5197cf6cce61c2a7ace927f493c980348e75761"
)
H1_LEGACY = {
    "private-strong": (12, 128, "UNIQUE/128"),
    "private-weak": (8, 32, "UNIQUE/32"),
    "same-pte": (0, 1, "UNIQUE/1"),
}
ORCHESTRATOR_UPGRADE_PATHS = {
    "NaxSoftware:benchmarks/dirtygen/README.md",
    "NaxSoftware:benchmarks/dirtygen/tests/test_dirtygen_perf_mc_phase3.py",
    "NaxSoftware:benchmarks/dirtygen/tools/run_dirtygen_perf_mc_phase3.py",
}


@dataclasses.dataclass(frozen=True)
class Selection:
    phase: str
    harts: int
    workload: str
    baseline: str
    block: str
    mode: str

    @property
    def key(self) -> str:
        return (f"{self.phase}:{self.block}:h{self.harts}:{self.workload}:"
                f"{self.baseline}:{self.mode}")

    @property
    def slug(self) -> str:
        return (f"{self.phase}-{self.block.lower()}-h{self.harts}-"
                f"{self.workload}-{self.baseline.lower()}-{self.mode}")

    def record(self) -> dict[str, Any]:
        return dataclasses.asdict(self) | {"key": self.key}


def rvls_gate_schedule() -> list[Selection]:
    rows = []
    for harts in (2, 4):
        for workload in GATE_WORKLOADS:
            for baseline in ("B3", "B2"):
                for mode in ("architecture", "rvls"):
                    rows.append(Selection("rvls-gate", harts, workload,
                                          baseline, "I0", mode))
    return rows


def architecture_schedule() -> list[Selection]:
    rows = []
    for block, baselines in BLOCKS.items():
        harts_set = (1, 2, 4) if block == "I0" else (2, 4)
        for harts in harts_set:
            for workload in ORDINARY:
                for baseline in baselines:
                    rows.append(Selection("architecture", harts, workload,
                                          baseline, block, "architecture"))
    return rows


def selected_schedule(phase: str) -> list[Selection]:
    if phase == "rvls-gate":
        return rvls_gate_schedule()
    if phase == "architecture":
        return architecture_schedule()
    return rvls_gate_schedule() + architecture_schedule()


def execution_stages(phase: str) -> list[list[Selection]]:
    """Keep the RVLS gate and each isolation block as fail-fast barriers."""
    stages: list[list[Selection]] = []
    if phase in ("rvls-gate", "all"):
        stages.append(rvls_gate_schedule())
    if phase in ("architecture", "all"):
        architecture = architecture_schedule()
        for block in BLOCKS:
            stages.append([row for row in architecture if row.block == block])
    return stages


def parallel_groups(stage: list[Selection]) -> list[list[Selection]]:
    """Return groups that may run in parallel without sharing an ELF build."""
    groups: dict[tuple[Any, ...], list[Selection]] = {}
    for row in stage:
        if row.phase == "rvls-gate":
            # Preserve B3 architecture/RVLS then B2 architecture/RVLS.
            key = (row.phase, row.harts, row.workload)
        else:
            # Preserve the declared baseline order inside each isolation block.
            key = (row.phase, row.block, row.harts, row.workload)
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_fingerprint(root: Path) -> dict[str, Any]:
    scopes = {
        "VexiiRiscv": (root, (
            "src/main/scala/vexiiriscv/test/VexiiRiscvProbe.scala",
            "src/main/scala/vexiiriscv/test/WhiteboxerPlugin.scala",
        )),
        "NaxSoftware": (root / "ext" / "NaxSoftware", (
            "benchmarks/dirtygen",
        )),
        "Spike": (root / "ext" / "riscv-isa-sim", (
            "riscv/mmu.cc", "riscv/mmu.h", "riscv/simif.h",
        )),
        "RVLS": (root / "ext" / "rvls", ("src", "bindings")),
    }
    repositories = repository_states(root)
    result: dict[str, Any] = {}
    for name, (repository, relative_scopes) in scopes.items():
        files: list[Path] = []
        for relative in relative_scopes:
            candidate = repository / relative
            if candidate.is_file():
                files.append(candidate)
            elif candidate.is_dir():
                files.extend(path for path in candidate.rglob("*") if path.is_file() and
                             "build" not in path.relative_to(repository).parts and
                             "__pycache__" not in path.relative_to(repository).parts and
                             path.suffix != ".pyc")
        file_rows = [{"path": str(path.relative_to(repository)),
                      "sha256": sha256_file(path)} for path in sorted(set(files))]
        result[name] = {
            "head": repositories[name]["head"],
            "branch": repositories[name]["branch"],
            "files": file_rows,
            "digest": sha256_bytes(json.dumps(file_rows, sort_keys=True).encode()),
        }
    result["digest"] = sha256_bytes(json.dumps(result, sort_keys=True).encode())
    return result


def fingerprint_changes(previous: dict[str, Any],
                        current: dict[str, Any]) -> set[str]:
    """List changed source paths, rejecting repository identity changes."""
    changes: set[str] = set()
    repositories = (set(previous) | set(current)) - {"digest"}
    for repository in repositories:
        before = previous.get(repository)
        after = current.get(repository)
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise RuntimeError("orchestrator upgrade changed fingerprint repositories")
        if ((before.get("head"), before.get("branch")) !=
                (after.get("head"), after.get("branch"))):
            raise RuntimeError(
                f"orchestrator upgrade changed {repository} HEAD or branch")
        before_files = {row["path"]: row["sha256"]
                        for row in before.get("files", [])}
        after_files = {row["path"]: row["sha256"]
                       for row in after.get("files", [])}
        for path in set(before_files) | set(after_files):
            if before_files.get(path) != after_files.get(path):
                changes.add(f"{repository}:{path}")
    return changes


def adopt_orchestrator_upgrade(manifest: dict[str, Any],
                               current: dict[str, Any]) -> set[str]:
    """Adopt only this driver/tests/docs change while retaining provenance."""
    previous = manifest.get("source_fingerprint")
    if not isinstance(previous, dict):
        raise RuntimeError("campaign lacks its previous source fingerprint")
    changes = fingerprint_changes(previous, current)
    if not changes or not changes <= ORCHESTRATOR_UPGRADE_PATHS:
        unexpected = sorted(changes - ORCHESTRATOR_UPGRADE_PATHS)
        raise RuntimeError(
            f"orchestrator upgrade includes disallowed source changes: {unexpected}")
    manifest.setdefault("source_fingerprint_history", []).append({
        "adopted_at": now(),
        "reason": "parallel phase-3 runner upgrade",
        "previous_digest": previous.get("digest"),
        "current_digest": current.get("digest"),
        "changed_files": sorted(changes),
    })
    manifest["source_fingerprint"] = current
    return changes


def legacy_h1_input(root: Path) -> dict[str, Any]:
    dirtygen = root / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen"
    audit_path = dirtygen / "audit" / "shdlt_validation_inputs.json"
    audit = load_json(audit_path)
    artifact = next((item for item in audit["hashes"]["artifacts"]
                     if item[0] == "perf-full-S0"), None)
    if artifact is None:
        raise RuntimeError("frozen audit lacks the perf-full-S0 artifact")
    elf = root / artifact[1]
    expected_elf_sha = artifact[2]
    if not elf.is_file() or sha256_file(elf) != expected_elf_sha:
        raise RuntimeError("frozen perf-full-S0 ELF does not match its audit hash")

    run = (dirtygen / "build" / "campaign" / "dirtygen-perf" /
           "phase5-clean-full-architecture-s0-seed2")
    metadata_path = run / "metadata.json"
    samples_path = run / "report" / "samples.json"
    metadata = load_json(metadata_path)
    samples = load_json(samples_path)
    expected_metadata = {
        "status": "passed", "exit_code": 0, "suite": "full",
        "mode": "architecture", "schedule_id": "S0",
        "simulation_seed": 2,
    }
    for key, value in expected_metadata.items():
        if metadata.get(key) != value:
            raise RuntimeError(
                f"frozen single-hart metadata {key}={metadata.get(key)!r}, "
                f"expected {value!r}")
    if metadata["artifact"].get("elf_sha256",
                                metadata["artifact"].get("sha256")) != expected_elf_sha:
        raise RuntimeError("frozen single-hart metadata has the wrong ELF hash")
    if samples.get("schema") != "shdlt-dirtygen-perf-samples-v1":
        raise RuntimeError("frozen single-hart samples have the wrong schema")

    fingerprint = legacy_elf_fingerprints(elf)
    return {
        "audit": {"path": str(audit_path.relative_to(root)),
                  "sha256": sha256_file(audit_path)},
        "metadata": {"path": str(metadata_path.relative_to(root)),
                     "sha256": sha256_file(metadata_path)},
        "samples": {"path": str(samples_path.relative_to(root)),
                    "sha256": sha256_file(samples_path)},
        "elf": {"path": str(elf.relative_to(root)),
                "sha256": expected_elf_sha},
        "workload_code_sha256": fingerprint["workload_code_sha256"],
        "workload_symbol_range": fingerprint["workload_symbol_range"],
    }


def measured_by_baseline(samples: list[dict[str, Any]], cycle_field: str,
                         context: str) -> dict[str, dict[int, int]]:
    result: dict[str, dict[int, int]] = {}
    for sample in samples:
        if sample.get("warmup") != 0:
            continue
        baseline = sample.get("baseline")
        repetition = sample.get("repetition")
        cycles = sample.get(cycle_field)
        if baseline not in ("B0", "B1", "B2", "B3"):
            raise RuntimeError(f"{context} has an invalid baseline")
        if not isinstance(repetition, int) or not isinstance(cycles, int):
            raise RuntimeError(f"{context} has malformed measured samples")
        slot = result.setdefault(baseline, {})
        if repetition in slot:
            raise RuntimeError(f"{context} has a duplicate measured sample")
        slot[repetition] = cycles
    expected = set(range(5))
    if set(result) != {"B0", "B1", "B2", "B3"} or any(
            set(values) != expected for values in result.values()):
        raise RuntimeError(f"{context} lacks a complete five-repetition baseline set")
    return result


def cycle_deltas(samples: list[dict[str, Any]], cycle_field: str,
                 context: str) -> dict[str, Any]:
    values = measured_by_baseline(samples, cycle_field, context)
    pairs = {"B1-B0": ("B1", "B0"), "B2-B0": ("B2", "B0"),
             "B3-B2": ("B3", "B2")}
    return {
        name: {
            "values": [values[left][rep] - values[right][rep]
                       for rep in range(5)],
            "median": statistics.median(
                values[left][rep] - values[right][rep] for rep in range(5)),
        }
        for name, (left, right) in pairs.items()
    }


def h1_compatibility_document(repo: Path, campaign_root: Path,
                              rows: dict[str, dict[str, Any]],
                              legacy_input: dict[str, Any]) -> dict[str, Any]:
    legacy_samples_path = repo / legacy_input["samples"]["path"]
    if sha256_file(legacy_samples_path) != legacy_input["samples"]["sha256"]:
        raise RuntimeError("frozen single-hart samples changed during the campaign")
    legacy_document = load_json(legacy_samples_path)
    results = []
    for workload, (config_base, operations, legacy_name) in H1_LEGACY.items():
        legacy_samples = [sample for sample in legacy_document["samples"]
                          if config_base <= sample.get("config", -1) < config_base + 4]
        if len(legacy_samples) != 24:
            raise RuntimeError(f"{legacy_name} does not have 24 frozen samples")
        for sample in legacy_samples:
            if (sample.get("pattern") != "UNIQUE" or
                    sample.get("operations") != operations or
                    sample.get("pages") != operations or
                    sample.get("status") != 0 or
                    sample.get("workload_instret") != 5 * operations + 4):
                raise RuntimeError(f"{legacy_name} violates its frozen ABI-v1 contract")

        mc_samples: list[dict[str, Any]] = []
        mc_windows = set()
        mc_layouts = set()
        for baseline in ("B0", "B1", "B2", "B3"):
            selection = Selection("architecture", 1, workload, baseline,
                                  "I0", "architecture")
            run = campaign_root / rows[selection.key]["run_path"]
            metadata = load_json(run / "metadata.json")
            document = load_json(run / "report" / "samples.json")
            mc_windows.add(metadata["artifact"]["timed_window_sha256"])
            symbol_range = metadata["artifact"]["workload_symbol_range"]
            timed_bytes = (int(symbol_range["timed_end_address"], 16) -
                           int(symbol_range["timed_start_address"], 16))
            mc_layouts.add((symbol_range["size"], timed_bytes))
            if len(document.get("samples", [])) != 6:
                raise RuntimeError(f"{selection.key} does not have six samples")
            for sample in document["samples"]:
                if (sample.get("hart_count") != 1 or
                        sample.get("workload") != workload.upper().replace("-", "_") or
                        sample.get("baseline") != baseline or
                        sample.get("total_operations") != operations or
                        sample.get("status") != 0 or
                        len(sample.get("harts", [])) != 1 or
                        sample["harts"][0].get("operations") != operations or
                        sample["harts"][0].get("workload_instret") != 5 * operations + 5):
                    raise RuntimeError(f"{selection.key} violates its ABI-v2 contract")
                mc_samples.append(sample)
        if mc_windows != {MC_TIMED_WINDOW_SHA256} or mc_layouts != {(148, 48)}:
            raise RuntimeError(f"H1 {workload} has an unexpected timed window or layout")
        results.append({
            "workload": workload, "operations": operations,
            "legacy_workload": legacy_name,
            "legacy_instret": 5 * operations + 4,
            "mc_instret": 5 * operations + 5,
            "legacy_deltas": cycle_deltas(
                legacy_samples, "workload_cycles", legacy_name),
            "mc_deltas": cycle_deltas(
                mc_samples, "completion_cycles", f"H1 {workload}"),
            "numeric_verdict": ("REPORT_ONLY_ORDER_SENSITIVE"
                                if operations == 128 else
                                "DESCRIPTIVE_CURRENT_PAIR"),
            "status": "PASS",
        })
    return {
        "schema": "shdlt-dirtygen-perf-mc-h1-compatibility-v1",
        "status": "PASS", "numeric_threshold_applied": False,
        "mc_timed_window_sha256": MC_TIMED_WINDOW_SHA256,
        "mc_timed_window_bytes": 48,
        "legacy_input": legacy_input,
        "workloads": results,
    }


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} does not contain a JSON object")
    return value


def run_directory(root: Path, ordinal: int, selection: Selection,
                  manifest_row: dict[str, Any], resume: bool) -> Path:
    base = root / "runs" / f"{ordinal:03d}-{selection.slug}"
    attempts = manifest_row.setdefault("attempts", [])
    if attempts:
        latest = root / attempts[-1]["path"]
        metadata_path = latest / "metadata.json"
        if metadata_path.is_file():
            metadata = load_json(metadata_path)
            if (metadata.get("status") == "passed" and
                    (latest / "report" / "samples.json").is_file() and
                    (latest / "report" / "trace-report.json").is_file()):
                manifest_row["status"] = "passed"
                manifest_row["run_path"] = str(latest.relative_to(root))
                return latest
        if not resume:
            raise RuntimeError(f"selection has an incomplete existing attempt: {selection.key}")
    candidate = base
    retry = 0
    while candidate.exists():
        retry += 1
        candidate = base.with_name(f"{base.name}-retry{retry}")
    attempts.append({"path": str(candidate.relative_to(root)),
                     "start_time": now(), "end_time": None,
                     "exit_code": None, "status": "running"})
    manifest_row["status"] = "running"
    manifest_row["run_path"] = str(candidate.relative_to(root))
    return candidate


def runner_command(repo: Path, selection: Selection, experiment: str,
                   seed: int, output: Path) -> list[str]:
    script = (repo / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen" /
              "tools" / "run_dirtygen_perf_mc.py")
    return [sys.executable, str(script),
            "--hart-count", str(selection.harts),
            "--workload", selection.workload,
            "--baseline", selection.baseline,
            "--isolation-block-id", selection.block,
            "--experiment-id", experiment,
            "--mode", selection.mode,
            "--seed", str(seed),
            "--output-root", str(output)]


class CampaignExecutor:
    """Run isolated selection groups while serializing manifest publication."""

    def __init__(self, repo: Path, root: Path, manifest_path: Path,
                 manifest: dict[str, Any], rows: dict[str, dict[str, Any]],
                 schedule: list[Selection], fingerprint: dict[str, Any],
                 experiment: str, seed: int, resume: bool, jobs: int):
        self.repo = repo
        self.root = root
        self.manifest_path = manifest_path
        self.manifest = manifest
        self.rows = rows
        self.ordinals = {row.key: ordinal
                         for ordinal, row in enumerate(schedule)}
        self.fingerprint = fingerprint
        self.experiment = experiment
        self.seed = seed
        self.resume = resume
        self.jobs = jobs
        self.manifest_lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.clone_lock = threading.Lock()
        self.stop = threading.Event()
        self.processes: set[subprocess.Popen[Any]] = set()

    def write_manifest(self) -> None:
        write_json(self.manifest_path, self.manifest)

    def group_environment(self, group: list[Selection]) -> dict[str, str]:
        first = group[0]
        if first.phase == "rvls-gate":
            slug = f"gate-h{first.harts}-{first.workload}"
        else:
            slug = f"architecture-{first.block.lower()}-h{first.harts}-{first.workload}"
        environment = os.environ.copy()
        environment["SPINALSIM_WORKSPACE"] = str(
            self.root / "parallel-workspaces" / slug)
        clone_parent = self.root / "parallel-mill-out-v3"
        clone = clone_parent / slug
        marker = clone / ".phase3-reflink-complete.json"
        with self.clone_lock:
            clone_parent.mkdir(parents=True, exist_ok=True)
            if clone.exists() and not marker.is_file():
                retry = 1
                while clone.with_name(f"{clone.name}-retry{retry}").exists():
                    retry += 1
                clone = clone.with_name(f"{clone.name}-retry{retry}")
                marker = clone / ".phase3-reflink-complete.json"
            if not clone.exists():
                source = self.repo / "out"
                if not (source / "mill-launcher").is_dir():
                    raise RuntimeError("cannot clone an incomplete Mill output cache")
                subprocess.run(
                    ["cp", "-a", "--reflink=always", str(source), str(clone)],
                    cwd=self.repo, check=True)
                write_json(marker, {
                    "schema": "shdlt-phase3-mill-reflink-v1",
                    "created_at": now(),
                    "source": str(source),
                })
        environment["MILL_OUTPUT_DIR"] = str(clone)
        return environment

    def terminate_active(self) -> None:
        self.stop.set()
        with self.process_lock:
            processes = list(self.processes)
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)

    def run_process(self, command: list[str], environment: dict[str, str]) -> int:
        if self.stop.is_set():
            raise RuntimeError("campaign stopped before launching another selection")
        process = subprocess.Popen(command, cwd=self.repo, env=environment)
        with self.process_lock:
            self.processes.add(process)
        try:
            return process.wait()
        finally:
            with self.process_lock:
                self.processes.discard(process)

    def run_selection(self, selection: Selection,
                      environment: dict[str, str]) -> None:
        row = self.rows[selection.key]
        with self.manifest_lock:
            output = run_directory(
                self.root, self.ordinals[selection.key], selection, row,
                self.resume)
            command = runner_command(self.repo, selection, self.experiment,
                                     self.seed, output)
            command_document = {
                "argv": command,
                "sha256": sha256_bytes(json.dumps(command).encode()),
            }
            already_passed = row["status"] == "passed"
            if already_passed:
                if row["attempts"][-1].get("command") != command_document:
                    raise RuntimeError(
                        f"resume rejected: command changed for {selection.key}")
            else:
                attempt = row["attempts"][-1]
                attempt["command"] = command_document
                attempt["execution_environment"] = {
                    "SPINALSIM_WORKSPACE": environment["SPINALSIM_WORKSPACE"],
                    "MILL_OUTPUT_DIR": environment.get("MILL_OUTPUT_DIR"),
                }
                self.write_manifest()

        if already_passed:
            validate_passed_run(output, selection, self.seed)
        else:
            code = self.run_process(command, environment)
            with self.manifest_lock:
                attempt = row["attempts"][-1]
                attempt["end_time"] = now()
                attempt["exit_code"] = code
                attempt["status"] = "passed" if code == 0 else "failed"
                row["status"] = attempt["status"]
                self.write_manifest()
            if code:
                raise RuntimeError(
                    f"selection failed ({code}): {selection.key}")
            validate_passed_run(output, selection, self.seed)
            if source_fingerprint(self.repo) != self.fingerprint:
                raise RuntimeError("source fingerprint changed during campaign")

        if selection.phase == "rvls-gate" and selection.mode == "rvls":
            architecture = dataclasses.replace(selection, mode="architecture")
            architecture_row = self.rows.get(architecture.key)
            if (architecture_row is None or
                    architecture_row["status"] != "passed"):
                raise RuntimeError(
                    f"RVLS pair lacks a passed architecture run: {selection.key}")
            pair = gate_pair_document(
                self.root / architecture_row["run_path"], output,
                architecture)
            with self.manifest_lock:
                row["pair_status"] = "passed"
                row["pair"] = pair
                self.write_manifest()

    def run_group(self, group: list[Selection]) -> None:
        environment = self.group_environment(group)
        for selection in group:
            if self.stop.is_set():
                return
            self.run_selection(selection, environment)

    def run_stage(self, stage: list[Selection]) -> None:
        groups = parallel_groups(stage)
        first_error: BaseException | None = None
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self.jobs, len(groups)),
            thread_name_prefix="phase3")
        futures = [executor.submit(self.run_group, group) for group in groups]
        try:
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except BaseException as error:
                    first_error = error
                    self.terminate_active()
                    for pending in futures:
                        pending.cancel()
                    break
        except BaseException:
            self.terminate_active()
            for future in futures:
                future.cancel()
            raise
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        if first_error is not None:
            raise first_error


def validate_passed_run(output: Path, selection: Selection, seed: int) -> None:
    metadata = load_json(output / "metadata.json")
    expected = {
        "status": "passed", "hart_count": selection.harts,
        "workload": selection.workload, "baseline": selection.baseline,
        "isolation_block_id": selection.block, "mode": selection.mode,
        "simulation_seed": seed,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise RuntimeError(f"{output} metadata {key}={metadata.get(key)!r}, expected {value!r}")
    if metadata.get("exit_code") != 0:
        raise RuntimeError(f"{output} has a nonzero recorded exit code")
    repo = find_repo_root(output)
    current_elf = elf_path(repo, selection.harts, selection.workload,
                           selection.baseline)
    if not current_elf.is_file():
        raise RuntimeError(f"current ELF is missing: {current_elf}")
    if metadata["artifact"].get("elf_sha256") != sha256_file(current_elf):
        raise RuntimeError(f"{output} no longer matches the current ELF")


def gate_pair_document(architecture: Path, rvls: Path,
                       selection: Selection) -> dict[str, Any]:
    arch_meta = load_json(architecture / "metadata.json")
    rvls_meta = load_json(rvls / "metadata.json")
    for field in ("elf_sha256", "text_sha256", "text_init_sha256",
                  "workload_code_sha256", "timed_window_sha256",
                  "selection_sha256", "selection"):
        if arch_meta["artifact"][field] != rvls_meta["artifact"][field]:
            raise RuntimeError(f"RVLS gate artifact mismatch {selection.key}: {field}")
    arch_cpu = dict(arch_meta["cpu_config"])
    rvls_cpu = dict(rvls_meta["cpu_config"])
    if arch_cpu != rvls_cpu:
        raise RuntimeError(f"RVLS gate CPU configuration mismatch {selection.key}")
    arch_samples = load_json(architecture / "report" / "samples.json")
    rvls_samples = load_json(rvls / "report" / "samples.json")
    if arch_samples != rvls_samples:
        raise RuntimeError(f"RVLS gate firmware/DUT-cycle mismatch {selection.key}")
    arch_trace = load_json(architecture / "report" / "trace-report.json")
    rvls_trace = load_json(rvls / "report" / "trace-report.json")
    if arch_trace != rvls_trace:
        raise RuntimeError(f"RVLS gate physical lifecycle mismatch {selection.key}")
    return {
        "hart_count": selection.harts, "workload": selection.workload,
        "baseline": selection.baseline, "block": selection.block,
        "architecture": str(architecture), "rvls": str(rvls),
        "elf_sha256": arch_meta["artifact"]["elf_sha256"],
        "raw_samples": len(arch_samples["samples"]), "status": "PASS",
    }


def validate_rvls_gate(root: Path, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    for harts in (2, 4):
        for workload in GATE_WORKLOADS:
            for baseline in ("B3", "B2"):
                arch = Selection("rvls-gate", harts, workload, baseline,
                                 "I0", "architecture")
                rvls = dataclasses.replace(arch, mode="rvls")
                arch_path = root / rows[arch.key]["run_path"]
                rvls_path = root / rows[rvls.key]["run_path"]
                pairs.append(gate_pair_document(arch_path, rvls_path, arch))
    return {"schema": GATE_SCHEMA, "status": "PASS", "pair_count": len(pairs),
            "process_count": len(pairs) * 2,
            "raw_sample_count": sum(row["raw_samples"] * 2 for row in pairs),
            "forced_cas_required": False, "pairs": pairs}


def run_main_comparison(repo: Path, root: Path,
                        rows: dict[str, dict[str, Any]]) -> Path:
    output = root / "architecture-comparison"
    if output.exists():
        document = load_json(output / "comparison.json")
        if document.get("status") != "PASS":
            raise RuntimeError("existing architecture comparison is not PASS")
        return output
    script = (repo / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen" /
              "tools" / "dirtygen_perf_mc_compare.py")
    command = [sys.executable, str(script)]
    for selection in architecture_schedule():
        run = root / rows[selection.key]["run_path"]
        command.extend(("--input", str(run / "report" / "samples.json"),
                        str(run / "metadata.json")))
    command.extend(("--output-dir", str(output)))
    subprocess.run(command, cwd=repo, check=True)
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("rvls-gate", "architecture", "all"),
                        default="all")
    parser.add_argument("--experiment-id", default="phase3-20260908")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--jobs", type=int, default=1,
                        help="parallel isolated selection groups")
    parser.add_argument("--adopt-orchestrator-upgrade", action="store_true",
                        help="adopt only the audited parallel-runner source update")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.jobs < 1 or args.jobs > 16:
        parser.error("--jobs must be between 1 and 16")
    if args.adopt_orchestrator_upgrade and not args.resume:
        parser.error("--adopt-orchestrator-upgrade requires --resume")
    if not IDENTIFIER.fullmatch(args.experiment_id):
        parser.error("--experiment-id must be a simple identifier")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = find_repo_root(Path(__file__))
    root = args.output_root or (repo / "ext" / "NaxSoftware" /
        "benchmarks" / "dirtygen" / "build" / "campaign" /
        "dirtygen-perf-mc-phase3" / args.experiment_id)
    schedule = selected_schedule(args.phase)
    if args.limit is not None:
        schedule = schedule[:args.limit]
    selected_keys = {row.key for row in schedule}
    stages = [[row for row in stage if row.key in selected_keys]
              for stage in execution_stages(args.phase)]
    stages = [stage for stage in stages if stage]
    if args.dry_run:
        print(json.dumps({"schema": SCHEMA, "phase": args.phase,
                          "selection_count": len(schedule),
                          "raw_sample_count": len(schedule) * 6,
                          "selections": [row.record() for row in schedule]},
                         indent=2, sort_keys=True))
        return 0

    manifest_path = root / "manifest.json"
    fingerprint = source_fingerprint(repo)
    legacy_input = (legacy_h1_input(repo)
                    if args.phase in ("architecture", "all") else None)
    if manifest_path.exists():
        if not args.resume:
            raise RuntimeError(f"campaign already exists: {root}")
        manifest = load_json(manifest_path)
        if manifest.get("schema") != SCHEMA:
            raise RuntimeError("resume rejected: campaign schema changed")
        if manifest.get("source_fingerprint") != fingerprint:
            if not args.adopt_orchestrator_upgrade:
                raise RuntimeError("resume rejected: source fingerprint changed")
            changed = adopt_orchestrator_upgrade(manifest, fingerprint)
            print("adopted parallel orchestrator upgrade: " +
                  ", ".join(sorted(changed)))
            write_json(manifest_path, manifest)
        if manifest.get("legacy_h1_input") != legacy_input:
            raise RuntimeError("resume rejected: frozen H1 input changed")
    else:
        if root.exists():
            raise RuntimeError(f"output root exists without a manifest: {root}")
        root.mkdir(parents=True)
        manifest = {
            "schema": SCHEMA, "status": "initialized", "phase": args.phase,
            "experiment_id": args.experiment_id, "seed": args.seed,
            "start_time": now(), "end_time": None,
            "source_fingerprint": fingerprint,
            "legacy_h1_input": legacy_input,
            "forced_cas_required": False,
            "planned_selection_count": len(schedule),
            "planned_raw_sample_count": len(schedule) * 6,
            "maximum_parallel_jobs": args.jobs,
            "runs": [row.record() | {"status": "pending", "attempts": []}
                     for row in schedule],
            "rvls_gate": None, "h1_compatibility": None,
            "architecture_comparison": None,
        }
        write_json(manifest_path, manifest)

    rows = {row["key"]: row for row in manifest["runs"]}
    if set(rows) != {selection.key for selection in schedule}:
        raise RuntimeError("resume rejected: schedule changed")
    manifest["status"] = "running"
    manifest["maximum_parallel_jobs"] = max(
        int(manifest.get("maximum_parallel_jobs", 1)), args.jobs)
    write_json(manifest_path, manifest)
    campaign: CampaignExecutor | None = None
    try:
        campaign = CampaignExecutor(
            repo, root, manifest_path, manifest, rows, schedule, fingerprint,
            args.experiment_id, args.seed, args.resume, args.jobs)
        for stage in stages:
            campaign.run_stage(stage)

            complete_gate = all(
                item.key in rows and rows[item.key]["status"] == "passed"
                for item in rvls_gate_schedule())
            if complete_gate:
                gate = validate_rvls_gate(root, rows)
                gate_path = root / "rvls-gate.json"
                if gate_path.exists() and load_json(gate_path) != gate:
                    raise RuntimeError("existing RVLS gate result differs")
                if not gate_path.exists():
                    write_json(gate_path, gate)
                manifest["rvls_gate"] = str(gate_path.relative_to(root))
                write_json(manifest_path, manifest)

            h1_selections = [item for item in architecture_schedule()
                             if item.harts == 1]
            complete_h1 = (legacy_input is not None and all(
                item.key in rows and rows[item.key]["status"] == "passed"
                for item in h1_selections))
            if complete_h1:
                h1 = h1_compatibility_document(repo, root, rows, legacy_input)
                h1_path = root / "h1-compatibility.json"
                if h1_path.exists() and load_json(h1_path) != h1:
                    raise RuntimeError("existing H1 compatibility result differs")
                if not h1_path.exists():
                    write_json(h1_path, h1)
                manifest["h1_compatibility"] = str(h1_path.relative_to(root))
                write_json(manifest_path, manifest)

        complete_gate = all(
            item.key in rows and rows[item.key]["status"] == "passed"
            for item in rvls_gate_schedule())
        if complete_gate:
            gate = validate_rvls_gate(root, rows)
            gate_path = root / "rvls-gate.json"
            if gate_path.exists() and load_json(gate_path) != gate:
                raise RuntimeError("existing RVLS gate result differs")
            if not gate_path.exists():
                write_json(gate_path, gate)
            manifest["rvls_gate"] = str(gate_path.relative_to(root))

        complete_architecture = all(
            item.key in rows and rows[item.key]["status"] == "passed"
            for item in architecture_schedule())
        if complete_architecture:
            comparison = run_main_comparison(repo, root, rows)
            manifest["architecture_comparison"] = str(comparison.relative_to(root))

        manifest["status"] = "passed"
        manifest["end_time"] = now()
        manifest.pop("failure", None)
        write_json(manifest_path, manifest)
        return 0
    except BaseException as error:
        if campaign is not None:
            campaign.terminate_active()
        manifest["status"] = "failed"
        manifest["end_time"] = now()
        manifest["failure"] = str(error)
        write_json(manifest_path, manifest)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
