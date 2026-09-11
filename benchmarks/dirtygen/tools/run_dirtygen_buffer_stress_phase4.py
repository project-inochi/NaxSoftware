#!/usr/bin/env python3
"""Run the serial, paired SHDLT Phase-4 buffer stress campaign."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from run_dirtygen_buffer_boundary_phase4 import (
    artifact_fingerprint, normative_fingerprints,
)
from run_dirtygen_perf import (
    command_record, find_repo_root, now, repository_states,
    toolchain_information, top_level_gitlinks,
)


SCHEMA = "shdlt-buffer-boundary-phase4-stress-campaign-v1"
RESULT_SCHEMA = "shdlt-buffer-boundary-phase4-stress-results-v1"
PROFILE = 3
HOST_TIMEOUT = 1800
FAIL_AFTER = 2_000_000_000
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclasses.dataclass(frozen=True)
class LoadProfile:
    name: str
    ready: str
    latency: int
    seed: int


@dataclasses.dataclass(frozen=True)
class Selection:
    harts: int
    load: LoadProfile
    mode: str

    @property
    def key(self) -> str:
        return f"h{self.harts}:{self.load.name}:{self.mode}"

    @property
    def slug(self) -> str:
        return f"h{self.harts}-{self.load.name}-{self.mode}"

    def record(self) -> dict[str, Any]:
        return {
            "key": self.key, "hart_count": self.harts,
            "load_profile": self.load.name,
            "dbus_ready_factor": self.load.ready,
            "memory_latency": self.load.latency,
            "seed": self.load.seed, "mode": self.mode,
        }


LOADS = (
    LoadProfile("p0-ready1p01-lat0-seed2", "1.01", 0, 2),
    LoadProfile("p1-ready0p70-lat17-seed3", "0.70", 17, 3),
    LoadProfile("p2-ready0p35-lat53-seed7", "0.35", 53, 7),
)


def campaign_schedule() -> list[Selection]:
    return [
        Selection(harts, load, mode)
        for harts in (1, 2, 4)
        for load in LOADS
        for mode in ("architecture", "rvls")
    ]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        document = json.load(stream)
    if not isinstance(document, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return document


def dirtygen_dir(root: Path) -> Path:
    return root / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen"


def elf_path(root: Path, harts: int) -> Path:
    return (dirtygen_dir(root) / "build" /
            f"buffer-boundary-stress-v2-h{harts}" /
            "dirtygen_buffer_boundary_mc.elf")


def build_command(root: Path, harts: int) -> list[str]:
    return ["make", "-C", str(dirtygen_dir(root)),
            "buffer-boundary-stress", f"BOUNDARY_MC_HARTS={harts}"]


def source_paths() -> tuple[str, ...]:
    return (
        "ext/NaxSoftware/benchmarks/dirtygen/Makefile",
        "ext/NaxSoftware/benchmarks/dirtygen/linker_buffer_boundary_mc.ld",
        "ext/NaxSoftware/benchmarks/dirtygen/include/dirtygen_buffer_boundary_mc.h",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_boundary_mc.c",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_boundary_mc_page_table.c",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_boundary_mc_startup.S",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_boundary_mc_guest.S",
        "ext/NaxSoftware/benchmarks/dirtygen/tools/dirtygen_buffer_boundary_report.py",
        "ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_buffer_stress_phase4.py",
        "src/main/scala/vexiiriscv/memory/PteUpdatePlugin.scala",
        "src/test/scala/vexiiriscv/memory/DirtyLogCapacityTester.scala",
        "ext/riscv-isa-sim/riscv/mmu.cc",
        "ext/riscv-isa-sim/riscv/mmu.h",
        "ext/riscv-isa-sim/riscv/simif.h",
        "ext/rvls/src/hart.cpp",
        "ext/rvls/src/hart.hpp",
    )


def file_fingerprints(root: Path, paths: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{"path": path, "sha256": sha256_file(root / path)} for path in paths]


def protected_paths() -> tuple[str, ...]:
    return (
        "ext/NaxSoftware/benchmarks/dirtygen/SHDLT_ISA_CONSISTENCY_AUDIT.md",
        "ext/NaxSoftware/benchmarks/dirtygen/SHDLT_DIRTYGEN_PERF_MC_REPORT.md",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_isa_consistency_inputs.json",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_isa_consistency_results.json",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_dirtygen_perf_mc_phase3_inputs.json",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_dirtygen_perf_mc_phase3_results.json",
        "ext/NaxSoftware/benchmarks/dirtygen/build/dirtygen.elf",
        "ext/NaxSoftware/benchmarks/dirtygen/build/phase1/dirtygen_phase1.elf",
    )


def input_fingerprint(root: Path, artifacts: dict[int, dict[str, Any]],
                      schedule: list[Selection]) -> dict[str, Any]:
    repositories = repository_states(root)
    document = {
        "repositories": repositories,
        "top_level_gitlinks": top_level_gitlinks(root, repositories),
        "sources": file_fingerprints(root, source_paths()),
        "protected": file_fingerprints(root, protected_paths()),
        "artifacts": {str(key): value for key, value in artifacts.items()},
        "schedule": [row.record() for row in schedule],
        "normative": normative_fingerprints(),
    }
    document["digest"] = sha256_bytes(
        json.dumps(document, sort_keys=True).encode())
    return document


def simulation_name(experiment: str, selection: Selection,
                    run_id: str) -> str:
    return f"shdlt_buffer_stress_{experiment}_{selection.slug}_{run_id}"


def cpu_config(selection: Selection) -> dict[str, Any]:
    return {
        "xlen": 64, "cpu_count": selection.harts, "physical_width": 32,
        "pmp_size": 2, "reset_vector": "0x80000000",
        "isa": "h,m,a,c,svadu,shdlt,zicntr", "fetch_l1": True,
        "lsu_l1": True, "lsu_l1_coherency": selection.harts != 1,
        "performance_counters": 4, "pass_policy": "all",
        "fail_policy": "any", "fail_after": FAIL_AFTER,
        "dbus_ready_factor": selection.load.ready,
        "memory_latency": selection.load.latency,
        "seed": selection.load.seed, "stdin": False,
        "raw_physical_trace": True,
    }


def simulation_command(root: Path, experiment: str, selection: Selection,
                       run_id: str) -> tuple[list[str], str]:
    mill = shutil.which("mill")
    if mill is None:
        raise RuntimeError("mill was not found in PATH")
    name = simulation_name(experiment, selection, run_id)
    config = cpu_config(selection)
    command = [
        "/bin/sh", mill, "--no-server", "Test[2.13.12].runMain",
        "vexiiriscv.tester.TestBench", "--xlen", "64",
        "--cpu-count", str(selection.harts), "--physical-width", "32",
        "--pmp-size", "2", "--reset-vector", "0x80000000",
        "--with-isa", config["isa"], "--with-fetch-l1", "--with-lsu-l1",
    ]
    if selection.harts != 1:
        command.append("--lsu-l1-coherency")
    command.extend([
        "--performance-counters", "4", "--load-elf",
        str(elf_path(root, selection.harts)), "--pass-symbol", "pass",
        "--fail-symbol", "fail", "--pass-policy", "all", "--fail-policy", "any",
        "--fail-after", str(FAIL_AFTER), "--dbus-ready-factor",
        selection.load.ready, "--memory-latency", str(selection.load.latency),
        "--seed", str(selection.load.seed), "--name", name, "--with-rvls-log",
    ])
    if selection.mode == "architecture":
        command.append("--no-rvls-check")
    command.append("--no-stdin")
    return command, name


def raw_trace_path(root: Path, name: str) -> Path:
    workspace = Path(os.environ.get("SPINALSIM_WORKSPACE", "simWorkspace"))
    if not workspace.is_absolute():
        workspace = root / workspace
    return workspace / "TestBenchDut" / name / "tracer.log"


def generated_rtl_path(root: Path) -> Path:
    workspace = Path(os.environ.get("SPINALSIM_WORKSPACE", "simWorkspace"))
    if not workspace.is_absolute():
        workspace = root / workspace
    return workspace / "TestBenchDut" / "rtl" / "TestBenchDut.v"


def report_command(root: Path, run: Path, selection: Selection) -> list[str]:
    return [
        sys.executable,
        str(dirtygen_dir(root) / "tools" /
            "dirtygen_buffer_boundary_report.py"),
        str(run / "console.log"), "--output-dir", str(run / "report"),
        "--hart-count", str(selection.harts), "--profile", str(PROFILE),
        "--tracer", str(run / "tracer.log"), "--elf",
        str(elf_path(root, selection.harts)),
    ]


def run_logged(command: list[str], cwd: Path, log: Path,
               timeout: int | None = None) -> int:
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=stream,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            stream.write(f"\nHOST_TIMEOUT {timeout}s: verification incomplete\n")
            return 124
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise


def validate_passed_run(run: Path, selection: Selection,
                        artifact: dict[str, Any]) -> None:
    metadata = load_json(run / "metadata.json")
    if metadata.get("status") != "passed" or metadata.get("exit_code") != 0:
        raise RuntimeError(f"run is not passed: {run}")
    if metadata.get("selection") != selection.record():
        raise RuntimeError(f"selection metadata changed: {run}")
    if metadata.get("artifact") != artifact:
        raise RuntimeError(f"ELF fingerprint changed: {run}")
    verdict = load_json(run / "report" / "verdict.json")
    if verdict.get("status") != "PASS" or verdict.get("trace_status") != "PASS":
        raise RuntimeError(f"firmware/trace verdict is not PASS: {run}")
    samples = load_json(run / "report" / "samples.json")
    expected = 18 if selection.harts == 1 else 24
    if len(samples.get("samples", [])) != expected:
        raise RuntimeError(f"wrong raw sample count in {run}")
    performance = load_json(run / "report" / "performance.json")
    if len(performance.get("samples", [])) != expected:
        raise RuntimeError(f"wrong performance sample count in {run}")
    for required in ("console.log", "tracer.log", "TestBenchDut.generated.v"):
        if not (run / required).is_file():
            raise RuntimeError(f"missing {required} in {run}")


def run_selection(root: Path, campaign: Path, experiment: str,
                  ordinal: int, selection: Selection,
                  artifact: dict[str, Any], fingerprint: dict[str, Any],
                  row: dict[str, Any], resume: bool) -> Path:
    attempts = row.setdefault("attempts", [])
    if row.get("status") == "passed" and attempts:
        run = campaign / attempts[-1]["path"]
        validate_passed_run(run, selection, artifact)
        return run
    if attempts and not resume:
        raise RuntimeError(f"incomplete prior attempt for {selection.key}")
    base = campaign / "runs" / f"{ordinal:02d}-{selection.slug}"
    run = base
    retry = 0
    while run.exists():
        retry += 1
        run = base.with_name(f"{base.name}-retry{retry}")
    run.mkdir(parents=True)
    run_id = uuid.uuid4().hex
    simulation, name = simulation_command(root, experiment, selection, run_id)
    report = report_command(root, run, selection)
    attempt = {
        "path": str(run.relative_to(campaign)), "run_id": run_id,
        "start_time": now(), "end_time": None, "status": "running",
        "exit_code": None, "simulation": command_record(simulation),
        "report": command_record(report),
    }
    attempts.append(attempt)
    row["status"] = "running"
    metadata = {
        "schema": "shdlt-buffer-boundary-phase4-stress-run-v1",
        "status": "running", "exit_code": None, "start_time": now(),
        "end_time": None, "selection": selection.record(),
        "artifact": artifact, "input_digest": fingerprint["digest"],
        "cpu_config": cpu_config(selection), "simulation_name": name,
        "commands": {"simulation": command_record(simulation),
                     "report": command_record(report)},
        "host_timeout_seconds": HOST_TIMEOUT,
    }
    write_json(run / "metadata.json", metadata)
    simulation_code = run_logged(simulation, root, run / "console.log", HOST_TIMEOUT)
    trace = raw_trace_path(root, name)
    rtl = generated_rtl_path(root)
    if trace.is_file():
        shutil.copy2(trace, run / "tracer.log")
    if rtl.is_file():
        shutil.copy2(rtl, run / "TestBenchDut.generated.v")
    report_code = (run_logged(report, root, run / "report.log")
                   if (run / "tracer.log").is_file() else 1)
    metadata.update({
        "simulation_exit_code": simulation_code,
        "report_exit_code": report_code,
        "trace_sha256": (sha256_file(run / "tracer.log")
                         if (run / "tracer.log").is_file() else None),
        "generated_rtl_sha256": (
            sha256_file(run / "TestBenchDut.generated.v")
            if (run / "TestBenchDut.generated.v").is_file() else None),
        "end_time": now(),
    })
    current_sources = file_fingerprints(root, source_paths())
    current_protected = file_fingerprints(root, protected_paths())
    metadata["source_after_matches"] = current_sources == fingerprint["sources"]
    metadata["protected_after_matches"] = current_protected == fingerprint["protected"]
    code = simulation_code or report_code
    if (code == 0 and (not metadata["source_after_matches"] or
                      not metadata["protected_after_matches"])):
        code = 1
        metadata["failure"] = "source or protected input changed during run"
    metadata["status"] = "passed" if code == 0 else "failed"
    metadata["exit_code"] = code
    write_json(run / "metadata.json", metadata)
    attempt.update({"end_time": now(), "status": metadata["status"],
                    "exit_code": code})
    row["status"] = metadata["status"]
    if code:
        raise RuntimeError(
            f"{selection.key} failed: simulation={simulation_code} report={report_code}")
    validate_passed_run(run, selection, artifact)
    return run


def pair_document(architecture: Path, rvls: Path,
                  selection: Selection) -> dict[str, Any]:
    arch_meta = load_json(architecture / "metadata.json")
    rvls_meta = load_json(rvls / "metadata.json")
    if arch_meta["artifact"] != rvls_meta["artifact"]:
        raise RuntimeError(f"pair ELF mismatch: {selection.key}")
    if arch_meta["cpu_config"] != rvls_meta["cpu_config"]:
        raise RuntimeError(f"pair CPU configuration mismatch: {selection.key}")
    compared = ("samples.json", "trace-report.json", "performance.json")
    hashes: dict[str, str] = {}
    for name in compared:
        arch_file = architecture / "report" / name
        rvls_file = rvls / "report" / name
        if arch_file.read_bytes() != rvls_file.read_bytes():
            raise RuntimeError(f"pair {name} mismatch: {selection.key}")
        hashes[name] = sha256_file(arch_file)
    for name in ("tracer.log", "TestBenchDut.generated.v"):
        if (architecture / name).read_bytes() != (rvls / name).read_bytes():
            raise RuntimeError(f"pair {name} mismatch: {selection.key}")
        hashes[name] = sha256_file(architecture / name)
    raw_samples = len(load_json(architecture / "report" / "samples.json")["samples"])
    return {
        "status": "PASS", "hart_count": selection.harts,
        "load_profile": selection.load.name,
        "architecture": str(architecture), "rvls": str(rvls),
        "raw_samples_per_mode": raw_samples,
        "hashes": hashes,
    }


def collect_results(campaign: Path, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    architecture_results = []
    for harts in (1, 2, 4):
        for load in LOADS:
            arch_selection = Selection(harts, load, "architecture")
            rvls_selection = Selection(harts, load, "rvls")
            architecture = campaign / rows[arch_selection.key]["run_path"]
            rvls = campaign / rows[rvls_selection.key]["run_path"]
            pair = pair_document(architecture, rvls, arch_selection)
            pairs.append(pair)
            architecture_results.append({
                "hart_count": harts, "load_profile": load.name,
                "dbus_ready_factor": load.ready, "memory_latency": load.latency,
                "seed": load.seed,
                "summary": load_json(
                    architecture / "report" / "performance.json")["summary"],
            })
    raw_samples = sum(pair["raw_samples_per_mode"] * 2 for pair in pairs)
    if len(pairs) != 9 or raw_samples != 396:
        raise RuntimeError(
            f"campaign cardinality mismatch pairs={len(pairs)} samples={raw_samples}")
    return {
        "schema": RESULT_SCHEMA, "status": "PASS",
        "process_count": 18, "pair_count": 9,
        "raw_sample_count": raw_samples,
        "absolute_cycle_threshold_applied": False,
        "pairs": pairs, "architecture_performance": architecture_results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", default="phase4-stress-20260910")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not IDENTIFIER.fullmatch(args.experiment_id) or len(args.experiment_id) > 64:
        parser.error("invalid experiment id")
    if args.limit is not None and not 1 <= args.limit <= 18:
        parser.error("--limit must be between 1 and 18")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = find_repo_root(Path(__file__))
    campaign = args.output_root or (
        dirtygen_dir(root) / "build" / "campaign" /
        "dirtygen-buffer-boundary-phase4" / args.experiment_id)
    schedule = campaign_schedule()
    if args.limit is not None:
        schedule = schedule[:args.limit]
    if args.dry_run:
        print(json.dumps({
            "schema": SCHEMA, "process_count": len(schedule),
            "raw_sample_count": sum(
                18 if row.harts == 1 else 24 for row in schedule),
            "serial": True, "selections": [row.record() for row in schedule],
        }, indent=2, sort_keys=True))
        return 0

    if campaign.exists() and not (campaign / "manifest.json").is_file():
        raise RuntimeError(f"output exists without manifest: {campaign}")
    campaign.mkdir(parents=True, exist_ok=True)
    build_dir = campaign / "build"
    build_dir.mkdir(exist_ok=True)
    artifacts: dict[int, dict[str, Any]] = {}
    for harts in (1, 2, 4):
        command = build_command(root, harts)
        code = run_logged(command, root, build_dir / f"h{harts}.log")
        if code:
            raise RuntimeError(f"H{harts} stress ELF build failed ({code})")
        artifacts[harts] = artifact_fingerprint(elf_path(root, harts))
        shutil.copy2(elf_path(root, harts).with_suffix(".asm"),
                     build_dir / f"dirtygen_buffer_boundary_mc.h{harts}.asm")

    fingerprint = input_fingerprint(root, artifacts, schedule)
    manifest_path = campaign / "manifest.json"
    if manifest_path.is_file():
        if not args.resume:
            raise RuntimeError(f"campaign already exists: {campaign}")
        manifest = load_json(manifest_path)
        if (manifest.get("schema") != SCHEMA or
                manifest.get("input_fingerprint") != fingerprint):
            raise RuntimeError("resume rejected: campaign input fingerprint changed")
    else:
        manifest = {
            "schema": SCHEMA, "status": "initialized",
            "experiment_id": args.experiment_id, "serial": True,
            "start_time": now(), "end_time": None,
            "planned_process_count": len(schedule),
            "planned_raw_sample_count": sum(
                18 if row.harts == 1 else 24 for row in schedule),
            "input_fingerprint": fingerprint,
            "runs": [row.record() | {"status": "pending", "attempts": []}
                     for row in schedule],
            "pairs": [], "results": None,
        }
        write_json(manifest_path, manifest)
    rows = {row["key"]: row for row in manifest["runs"]}
    if set(rows) != {row.key for row in schedule}:
        raise RuntimeError("resume rejected: schedule changed")
    manifest["status"] = "running"
    write_json(manifest_path, manifest)
    try:
        architecture: dict[tuple[int, str], Path] = {}
        for ordinal, selection in enumerate(schedule):
            row = rows[selection.key]
            run = run_selection(
                root, campaign, args.experiment_id, ordinal, selection,
                artifacts[selection.harts], fingerprint, row, args.resume)
            row["run_path"] = str(run.relative_to(campaign))
            write_json(manifest_path, manifest)
            pair_key = (selection.harts, selection.load.name)
            if selection.mode == "architecture":
                architecture[pair_key] = run
            else:
                arch = architecture.get(pair_key)
                if arch is None:
                    arch_row = rows[Selection(
                        selection.harts, selection.load, "architecture").key]
                    if arch_row.get("status") == "passed":
                        arch = campaign / arch_row["run_path"]
                if arch is None:
                    raise RuntimeError(f"RVLS run lacks architecture pair: {selection.key}")
                pair = pair_document(arch, run, selection)
                row["pair"] = pair
                manifest["pairs"] = [
                    item for item in manifest["pairs"]
                    if not (item["hart_count"] == selection.harts and
                            item["load_profile"] == selection.load.name)] + [pair]
                write_json(manifest_path, manifest)
        if len(schedule) == 18:
            results = collect_results(campaign, rows)
            write_json(campaign / "results.json", results)
            manifest["results"] = results
            manifest["status"] = "passed"
        else:
            manifest["status"] = "partial-passed"
        manifest["end_time"] = now()
        write_json(manifest_path, manifest)
        return 0
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["end_time"] = now()
        manifest["failure"] = str(error)
        write_json(manifest_path, manifest)
        print(f"buffer stress campaign stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
