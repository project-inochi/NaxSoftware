#!/usr/bin/env python3
"""Build and run one reproducible dirtygen_perf simulation campaign."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


CPU_CONFIG: dict[str, Any] = {
    "xlen": 64,
    "cpu_count": 1,
    "physical_width": 32,
    "reset_vector": "0x80000000",
    "isa": "h,m,a,c,svadu,shdlt,zicntr",
    "fetch_l1": True,
    "lsu_l1": True,
    "lsu_l1_coherency": False,
    "pass_policy": "all",
    "fail_policy": "any",
    "fail_after": 2_000_000_000,
    "dbus_ready_factor": "1.01",
    "memory_latency": 0,
    "seed": 2,
    "stdin": False,
}


def find_repo_root(start: Path) -> Path:
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    while candidate != candidate.parent:
        if (candidate / "build.mill").is_file():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("could not locate VexiiRiscv build.mill")


def dirtygen_dir(repo_root: Path) -> Path:
    return repo_root / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen"


def suite_target(suite: str) -> str:
    return "perf" if suite == "full" else "perf-rvls-smoke"


def elf_path(repo_root: Path, suite: str) -> Path:
    build_dir = "perf" if suite == "full" else "perf-rvls-smoke"
    return dirtygen_dir(repo_root) / "build" / build_dir / "dirtygen_perf.elf"


def build_command(repo_root: Path, suite: str) -> list[str]:
    return ["make", "-C", str(dirtygen_dir(repo_root)), suite_target(suite)]


def simulation_name(suite: str, mode: str) -> str:
    return f"shdlt_dirtygen_perf_{suite}_{mode}_seed2"


def mill_command(repo_root: Path, suite: str, mode: str) -> list[str]:
    name = simulation_name(suite, mode)
    mill = shutil.which("mill")
    if mill is None:
        raise RuntimeError("mill was not found in PATH")
    command = [
        "/bin/sh",
        mill,
        "--no-server",
        "Test[2.13.12].runMain",
        "vexiiriscv.tester.TestBench",
        "--xlen",
        "64",
        "--cpu-count",
        "1",
        "--physical-width",
        "32",
        "--reset-vector",
        "0x80000000",
        "--with-isa",
        str(CPU_CONFIG["isa"]),
        "--with-fetch-l1",
        "--with-lsu-l1",
        "--load-elf",
        str(elf_path(repo_root, suite)),
        "--pass-symbol",
        "pass",
        "--fail-symbol",
        "fail",
        "--pass-policy",
        "all",
        "--fail-policy",
        "any",
        "--fail-after",
        str(CPU_CONFIG["fail_after"]),
        "--dbus-ready-factor",
        str(CPU_CONFIG["dbus_ready_factor"]),
        "--memory-latency",
        str(CPU_CONFIG["memory_latency"]),
        "--seed",
        str(CPU_CONFIG["seed"]),
        "--name",
        name,
        "--with-rvls-log" if mode == "rvls" else "--no-rvls-check",
        "--no-stdin",
    ]
    return command


def report_command(
    repo_root: Path, suite: str, console: Path, report_dir: Path
) -> list[str]:
    script = dirtygen_dir(repo_root) / "tools" / "dirtygen_perf_report.py"
    return [
        sys.executable,
        str(script),
        str(console),
        "--suite",
        suite,
        "--output-dir",
        str(report_dir),
    ]


def run_git(path: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def repository_states(repo_root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "VexiiRiscv": repo_root,
        "NaxSoftware": repo_root / "ext" / "NaxSoftware",
        "Spike": repo_root / "ext" / "riscv-isa-sim",
        "RVLS": repo_root / "ext" / "rvls",
    }
    states: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        status = run_git(path, "status", "--short")
        states[name] = {
            "path": str(path),
            "head": run_git(path, "rev-parse", "HEAD"),
            "branch": run_git(path, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(status),
            "status": status.splitlines(),
        }
    return states


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def toolchain_version() -> str:
    completed = subprocess.run(
        ["riscv64-elf-gcc", "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.splitlines()[0]


def command_record(command: list[str]) -> dict[str, Any]:
    return {"argv": command, "shell": shlex.join(command)}


def initial_metadata(
    repo_root: Path,
    suite: str,
    mode: str,
    build: list[str],
    mill: list[str],
    report: list[str],
) -> dict[str, Any]:
    return {
        "schema": "shdlt-dirtygen-perf-campaign-v1",
        "captured_at": datetime.datetime.now().astimezone().isoformat(),
        "suite": suite,
        "mode": mode,
        "status": "initialized",
        "repositories": repository_states(repo_root),
        "toolchain": toolchain_version(),
        "cpu_config": CPU_CONFIG,
        "commands": {
            "build": command_record(build),
            "simulation": command_record(mill),
            "report": command_record(report),
        },
        "artifact": {
            "elf": str(elf_path(repo_root, suite)),
            "sha256": None,
        },
    }


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_logged(command: list[str], cwd: Path, log: Path) -> int:
    with log.open("w", encoding="utf-8") as stream:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    return completed.returncode


def rvls_trace_path(repo_root: Path, suite: str, mode: str) -> Path:
    return (
        repo_root
        / "simWorkspace"
        / "TestBenchDut"
        / simulation_name(suite, mode)
        / "tracer.log"
    )


def trace_signature(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def copy_rvls_trace(
    repo_root: Path,
    suite: str,
    mode: str,
    output: Path,
    previous_signature: tuple[int, int] | None,
) -> bool:
    if mode != "rvls":
        return True
    source = rvls_trace_path(repo_root, suite, mode)
    if not source.is_file():
        return False
    if trace_signature(source) == previous_signature:
        return False
    shutil.copy2(source, output / "tracer.log")
    return True


def default_output_root(repo_root: Path, suite: str, mode: str) -> Path:
    return (
        dirtygen_dir(repo_root)
        / "build"
        / "campaign"
        / "dirtygen-perf"
        / f"{suite}-{mode}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one reproducible SHDLT dirtygen performance campaign"
    )
    parser.add_argument("--suite", choices=("full", "smoke"), required=True)
    parser.add_argument("--mode", choices=("architecture", "rvls"), required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        repo_root = find_repo_root(Path(__file__))
        output = (
            args.output_root.resolve()
            if args.output_root is not None
            else default_output_root(repo_root, args.suite, args.mode)
        )
        build = build_command(repo_root, args.suite)
        mill = mill_command(repo_root, args.suite, args.mode)
        console = output / "console.log"
        report_dir = output / "report"
        report = report_command(repo_root, args.suite, console, report_dir)

        if args.dry_run:
            print(f"BUILD {shlex.join(build)}")
            print(f"SIMULATE {shlex.join(mill)}")
            print(f"REPORT {shlex.join(report)}")
            print(f"OUTPUT {output}")
            return 0

        if (output / "metadata.json").exists() or console.exists():
            raise RuntimeError(
                f"output root already contains a campaign: {output}"
            )
        output.mkdir(parents=True, exist_ok=True)
        metadata_path = output / "metadata.json"
        metadata = initial_metadata(
            repo_root, args.suite, args.mode, build, mill, report
        )
        write_metadata(metadata_path, metadata)

        build_exit = run_logged(build, repo_root, output / "build.log")
        metadata["build_exit_code"] = build_exit
        if build_exit != 0:
            metadata["status"] = "build_failed"
            write_metadata(metadata_path, metadata)
            return 1
        elf = elf_path(repo_root, args.suite)
        if not elf.is_file():
            metadata["status"] = "missing_elf"
            write_metadata(metadata_path, metadata)
            return 1
        metadata["artifact"]["sha256"] = sha256(elf)

        trace_before = trace_signature(
            rvls_trace_path(repo_root, args.suite, args.mode)
        ) if args.mode == "rvls" else None
        simulation_exit = run_logged(mill, repo_root, console)
        metadata["simulation_exit_code"] = simulation_exit
        trace_available = copy_rvls_trace(
            repo_root, args.suite, args.mode, output, trace_before
        )
        metadata["rvls_trace_available"] = trace_available
        if simulation_exit != 0:
            metadata["status"] = "simulation_failed"
            write_metadata(metadata_path, metadata)
            return 1
        if args.mode == "rvls" and not trace_available:
            metadata["status"] = "missing_rvls_trace"
            write_metadata(metadata_path, metadata)
            return 1

        report_exit = run_logged(report, repo_root, output / "report.log")
        metadata["report_exit_code"] = report_exit
        metadata["status"] = "pass" if report_exit == 0 else "report_failed"
        write_metadata(metadata_path, metadata)
        return 0 if report_exit == 0 else 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"dirtygen perf campaign error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
