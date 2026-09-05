#!/usr/bin/env python3
"""Build and run one reproducible dirtygen_perf simulation campaign."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import uuid
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

SUITE_MASKS = {
    "full": "0xffffffff",
    "smoke": "0x0f0000f0",
    "sensitivity": "0xf000f000",
}
SCHEDULE_MACROS = {"S0": 0, "S1": 1, "S2": 2, "S3": 3}
SCHEDULE_IDS = ("legacy", *SCHEDULE_MACROS)

TERMINAL_STATUSES = {"passed", "failed", "interrupted"}
FAILURE_STAGES = {
    "setup",
    "build",
    "artifact",
    "simulation",
    "trace",
    "report",
    "internal",
}


class CampaignFailure(RuntimeError):
    def __init__(self, stage: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code if exit_code != 0 else 1


class CampaignInterrupted(RuntimeError):
    def __init__(self, signum: int):
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat()


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


def build_directory(suite: str, schedule_id: str = "legacy") -> str:
    if suite not in SUITE_MASKS:
        raise ValueError(f"unknown suite {suite!r}")
    if schedule_id not in SCHEDULE_IDS:
        raise ValueError(f"unknown schedule {schedule_id!r}")
    if schedule_id == "legacy":
        if suite == "full":
            return "perf"
        if suite == "smoke":
            return "perf-rvls-smoke"
        return "perf-sensitivity-legacy"
    return f"perf-{suite}-{schedule_id.lower()}"


def elf_path(
    repo_root: Path, suite: str, schedule_id: str = "legacy"
) -> Path:
    build_dir = build_directory(suite, schedule_id)
    return dirtygen_dir(repo_root) / "build" / build_dir / "dirtygen_perf.elf"


def build_command(
    repo_root: Path, suite: str, schedule_id: str = "legacy"
) -> list[str]:
    if schedule_id == "legacy" and suite in ("full", "smoke"):
        return ["make", "-C", str(dirtygen_dir(repo_root)), suite_target(suite)]
    command = [
        "make",
        "-C",
        str(dirtygen_dir(repo_root)),
        "SUITE=perf",
        f"BUILD_DIR=build/{build_directory(suite, schedule_id)}",
        f"PERF_CONFIG_MASK={SUITE_MASKS[suite]}",
    ]
    if schedule_id != "legacy":
        command.append(f"PERF_SCHEDULE_ID={SCHEDULE_MACROS[schedule_id]}")
    command.append("all")
    return command


def simulation_name(
    suite: str, mode: str, schedule_id: str = "legacy", seed: int = 2
) -> str:
    return (
        f"shdlt_dirtygen_perf_{suite}_{mode}_"
        f"{schedule_id.lower()}_seed{seed}"
    )


def cpu_config(seed: int = 2) -> dict[str, Any]:
    config = dict(CPU_CONFIG)
    config["seed"] = seed
    return config


def mill_command(
    repo_root: Path,
    suite: str,
    mode: str,
    schedule_id: str = "legacy",
    seed: int = 2,
) -> list[str]:
    config = cpu_config(seed)
    name = simulation_name(suite, mode, schedule_id, seed)
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
        str(config["isa"]),
        "--with-fetch-l1",
        "--with-lsu-l1",
        "--load-elf",
        str(elf_path(repo_root, suite, schedule_id)),
        "--pass-symbol",
        "pass",
        "--fail-symbol",
        "fail",
        "--pass-policy",
        "all",
        "--fail-policy",
        "any",
        "--fail-after",
        str(config["fail_after"]),
        "--dbus-ready-factor",
        str(config["dbus_ready_factor"]),
        "--memory-latency",
        str(config["memory_latency"]),
        "--seed",
        str(config["seed"]),
        "--name",
        name,
        "--with-rvls-log" if mode == "rvls" else "--no-rvls-check",
        "--no-stdin",
    ]
    return command


def report_command(
    repo_root: Path,
    suite: str,
    console: Path,
    report_dir: Path,
    schedule_id: str = "legacy",
) -> list[str]:
    script = dirtygen_dir(repo_root) / "tools" / "dirtygen_perf_report.py"
    return [
        sys.executable,
        str(script),
        str(console),
        "--suite",
        suite,
        "--schedule-id",
        schedule_id,
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
        status = run_git(
            path, "status", "--porcelain=v1", "--untracked-files=all"
        )
        status_lines = status.splitlines()
        tracked = [line for line in status_lines if not line.startswith("??")]
        untracked = [line[3:] for line in status_lines if line.startswith("??")]
        states[name] = {
            "path": str(path),
            "head": run_git(path, "rev-parse", "HEAD"),
            "branch": run_git(path, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(status_lines),
            "tracked_dirty": bool(tracked),
            "untracked_dirty": bool(untracked),
            "tracked_status": tracked,
            "untracked_paths": untracked,
            "status": status_lines,
        }
    return states


def top_level_gitlinks(
    repo_root: Path, repositories: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    paths = {
        "NaxSoftware": "ext/NaxSoftware",
        "Spike": "ext/riscv-isa-sim",
        "RVLS": "ext/rvls",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, relative_path in paths.items():
        line = run_git(repo_root, "ls-tree", "HEAD", "--", relative_path)
        fields = line.split(None, 3)
        if len(fields) != 4 or fields[0] != "160000" or fields[1] != "commit":
            raise RuntimeError(f"could not resolve gitlink {relative_path}")
        gitlink_head = fields[2]
        actual_head = repositories[name]["head"]
        result[name] = {
            "path": relative_path,
            "gitlink_head": gitlink_head,
            "actual_head": actual_head,
            "matches_actual": gitlink_head == actual_head,
        }
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def version_record(executable: str, *arguments: str) -> dict[str, Any]:
    path = shutil.which(executable)
    record: dict[str, Any] = {
        "available": path is not None,
        "path": path,
        "argv": [path or executable, *arguments],
        "exit_code": None,
        "version": None,
        "error": None,
    }
    if path is None:
        record["error"] = f"{executable} was not found in PATH"
        return record
    try:
        completed = subprocess.run(
            [path, *arguments],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        record["exit_code"] = completed.returncode
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr)
            if part.strip()
        )
        record["version"] = output or None
        if completed.returncode != 0:
            record["error"] = f"version command exited {completed.returncode}"
    except OSError as error:
        record["error"] = str(error)
    return record


def toolchain_information(mill_command_argv: list[str]) -> dict[str, Any]:
    mill_path = Path(mill_command_argv[1]).resolve()
    return {
        "python": {
            "available": True,
            "path": sys.executable,
            "version": sys.version,
        },
        "riscv_gcc": version_record("riscv64-elf-gcc", "--version"),
        "java": version_record("java", "-version"),
        "verilator": version_record("verilator", "--version"),
        "mill": {
            "available": mill_path.is_file(),
            "path": str(mill_path),
            "sha256": sha256(mill_path) if mill_path.is_file() else None,
        },
    }


def command_record(command: list[str]) -> dict[str, Any]:
    return {"argv": command, "shell": shlex.join(command)}


def initial_metadata(
    repo_root: Path,
    suite: str,
    mode: str,
    build: list[str],
    mill: list[str],
    report: list[str],
    schedule_id: str = "legacy",
    seed: int = 2,
) -> dict[str, Any]:
    repositories = repository_states(repo_root)
    trace_required = mode == "rvls"
    trace_requested = "--with-rvls-log" in mill
    return {
        "schema": "shdlt-dirtygen-perf-campaign-v2",
        "run_id": uuid.uuid4().hex,
        "schedule_id": schedule_id,
        "suite": suite,
        "mode": mode,
        "status": "initialized",
        "exit_code": None,
        "failure_stage": None,
        "failure_message": None,
        "start_time": now(),
        "end_time": None,
        "trace_required": trace_required,
        "trace_requested": trace_requested,
        "trace_generated": False,
        "trace_path": None,
        "simulation_seed": seed,
        "repositories": repositories,
        "top_level_gitlinks": top_level_gitlinks(repo_root, repositories),
        "toolchain": toolchain_information(mill),
        "cpu_config": cpu_config(seed),
        "commands": {
            "build": command_record(build),
            "simulation": command_record(mill),
            "report": command_record(report),
        },
        "artifact": {
            "elf": str(elf_path(repo_root, suite, schedule_id)),
            "sha256": None,
        },
        "build_exit_code": None,
        "simulation_exit_code": None,
        "report_exit_code": None,
    }


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    payload = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The atomic rename is sufficient on filesystems which cannot fsync
            # a directory (and the temporary file itself was already synced).
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def finish_metadata(
    metadata: dict[str, Any], status: str, exit_code: int,
    failure_stage: str | None = None, failure_message: str | None = None,
) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"invalid terminal status {status!r}")
    if failure_stage is not None and failure_stage not in FAILURE_STAGES:
        raise ValueError(f"invalid failure stage {failure_stage!r}")
    metadata["status"] = status
    metadata["exit_code"] = exit_code
    metadata["failure_stage"] = failure_stage
    metadata["failure_message"] = failure_message
    metadata["end_time"] = now()


_active_process: subprocess.Popen[str] | None = None


def terminate_active_process() -> None:
    global _active_process
    process = _active_process
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_logged(command: list[str], cwd: Path, log: Path) -> int:
    global _active_process
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        _active_process = process
        try:
            return process.wait()
        except BaseException:
            terminate_active_process()
            raise
        finally:
            _active_process = None


def rvls_trace_path(
    repo_root: Path,
    suite: str,
    mode: str,
    schedule_id: str = "legacy",
    seed: int = 2,
) -> Path:
    return (
        repo_root
        / "simWorkspace"
        / "TestBenchDut"
        / simulation_name(suite, mode, schedule_id, seed)
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
    schedule_id: str = "legacy",
    seed: int = 2,
) -> Path | None:
    if mode != "rvls":
        return None
    source = rvls_trace_path(repo_root, suite, mode, schedule_id, seed)
    if not source.is_file():
        return None
    if trace_signature(source) == previous_signature:
        return None
    destination = output / "tracer.log"
    shutil.copy2(source, destination)
    return destination


def default_output_root(
    repo_root: Path,
    suite: str,
    mode: str,
    schedule_id: str = "legacy",
    seed: int = 2,
) -> Path:
    return (
        dirtygen_dir(repo_root)
        / "build"
        / "campaign"
        / "dirtygen-perf"
        / f"{suite}-{mode}-{schedule_id.lower()}-seed{seed}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one reproducible SHDLT dirtygen performance campaign"
    )
    parser.add_argument("--suite", choices=tuple(SUITE_MASKS), required=True)
    parser.add_argument("--mode", choices=("architecture", "rvls"), required=True)
    parser.add_argument("--schedule-id", choices=SCHEDULE_IDS, default="legacy")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    metadata: dict[str, Any] | None = None
    metadata_path: Path | None = None
    original_handlers: dict[int, Any] = {}
    active_stage: str | None = "setup"

    def interrupt_handler(signum: int, _frame: Any) -> None:
        raise CampaignInterrupted(signum)

    def persist_terminal(
        status: str, exit_code: int, stage: str | None, message: str | None
    ) -> None:
        if metadata is None or metadata_path is None:
            return
        finish_metadata(metadata, status, exit_code, stage, message)
        write_metadata(metadata_path, metadata)

    try:
        repo_root = find_repo_root(Path(__file__))
        output = (
            args.output_root.resolve()
            if args.output_root is not None
            else default_output_root(
                repo_root, args.suite, args.mode, args.schedule_id, args.seed
            )
        )
        build = build_command(repo_root, args.suite, args.schedule_id)
        mill = mill_command(
            repo_root, args.suite, args.mode, args.schedule_id, args.seed
        )
        console = output / "console.log"
        report_dir = output / "report"
        report = report_command(
            repo_root, args.suite, console, report_dir, args.schedule_id
        )

        if args.dry_run:
            print(f"BUILD {shlex.join(build)}")
            print(f"SIMULATE {shlex.join(mill)}")
            print(f"REPORT {shlex.join(report)}")
            print(f"OUTPUT {output}")
            return 0

        if output.exists() and any(output.iterdir()):
            raise RuntimeError(
                f"output root already contains a campaign: {output}"
            )
        output.mkdir(parents=True, exist_ok=True)
        metadata_path = output / "metadata.json"
        metadata = initial_metadata(
            repo_root,
            args.suite,
            args.mode,
            build,
            mill,
            report,
            args.schedule_id,
            args.seed,
        )
        write_metadata(metadata_path, metadata)

        for signum in (signal.SIGINT, signal.SIGTERM):
            original_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupt_handler)

        metadata["status"] = "running"
        write_metadata(metadata_path, metadata)

        active_stage = "build"
        build_exit = run_logged(build, repo_root, output / "build.log")
        metadata["build_exit_code"] = build_exit
        write_metadata(metadata_path, metadata)
        if build_exit != 0:
            raise CampaignFailure(
                "build", f"build command exited {build_exit}", build_exit
            )

        active_stage = "artifact"
        elf = elf_path(repo_root, args.suite, args.schedule_id)
        if not elf.is_file():
            raise CampaignFailure("artifact", f"ELF is missing: {elf}")
        metadata["artifact"]["sha256"] = sha256(elf)
        write_metadata(metadata_path, metadata)

        trace_before = trace_signature(
            rvls_trace_path(
                repo_root,
                args.suite,
                args.mode,
                args.schedule_id,
                args.seed,
            )
        ) if args.mode == "rvls" else None

        active_stage = "simulation"
        simulation_exit = run_logged(mill, repo_root, console)
        metadata["simulation_exit_code"] = simulation_exit
        write_metadata(metadata_path, metadata)

        active_stage = "trace"
        try:
            trace = copy_rvls_trace(
                repo_root,
                args.suite,
                args.mode,
                output,
                trace_before,
                args.schedule_id,
                args.seed,
            )
        except OSError as error:
            if simulation_exit != 0:
                raise CampaignFailure(
                    "simulation",
                    f"simulation exited {simulation_exit}; trace copy failed: {error}",
                    simulation_exit,
                ) from error
            raise CampaignFailure(
                "trace", f"could not copy RVLS trace: {error}"
            ) from error
        metadata["trace_generated"] = trace is not None
        metadata["trace_path"] = trace.name if trace is not None else None
        write_metadata(metadata_path, metadata)

        if simulation_exit != 0:
            raise CampaignFailure(
                "simulation",
                f"simulation command exited {simulation_exit}",
                simulation_exit,
            )
        if metadata["trace_required"] and trace is None:
            raise CampaignFailure("trace", "fresh RVLS trace was not generated")

        active_stage = "report"
        report_exit = run_logged(report, repo_root, output / "report.log")
        metadata["report_exit_code"] = report_exit
        write_metadata(metadata_path, metadata)
        if report_exit != 0:
            raise CampaignFailure(
                "report", f"report command exited {report_exit}", report_exit
            )
        finish_metadata(metadata, "passed", 0)
        write_metadata(metadata_path, metadata)
        return 0
    except CampaignInterrupted as error:
        terminate_active_process()
        exit_code = 128 + error.signum
        try:
            persist_terminal(
                "interrupted", exit_code, active_stage or "internal", str(error)
            )
        except OSError as metadata_error:
            print(
                f"could not update campaign metadata: {metadata_error}",
                file=sys.stderr,
            )
        print(f"dirtygen perf campaign interrupted: {error}", file=sys.stderr)
        return exit_code
    except KeyboardInterrupt:
        terminate_active_process()
        try:
            persist_terminal(
                "interrupted", 130, active_stage or "internal",
                "interrupted by keyboard",
            )
        except OSError as metadata_error:
            print(
                f"could not update campaign metadata: {metadata_error}",
                file=sys.stderr,
            )
        print("dirtygen perf campaign interrupted by keyboard", file=sys.stderr)
        return 130
    except CampaignFailure as error:
        try:
            persist_terminal("failed", error.exit_code, error.stage, str(error))
        except OSError as metadata_error:
            print(
                f"could not update campaign metadata: {metadata_error}",
                file=sys.stderr,
            )
        print(f"dirtygen perf campaign error: {error}", file=sys.stderr)
        return error.exit_code
    except Exception as error:
        try:
            persist_terminal("failed", 1, "internal", str(error))
        except OSError as metadata_error:
            print(
                f"could not update campaign metadata: {metadata_error}",
                file=sys.stderr,
            )
        print(f"dirtygen perf campaign error: {error}", file=sys.stderr)
        return 1
    finally:
        for signum, handler in original_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
