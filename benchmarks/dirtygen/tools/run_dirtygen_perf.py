#!/usr/bin/env python3
"""Build and run one reproducible dirtygen_perf simulation campaign."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import struct
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
SUITES = (*SUITE_MASKS, "isolated")
ISOLATION_BLOCKS = {
    "I0": ("B0", "B1", "B3", "B2"),
    "I1": ("B1", "B2", "B0", "B3"),
    "I2": ("B2", "B3", "B1", "B0"),
    "I3": ("B3", "B0", "B2", "B1"),
}
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

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


class IsolationSpec:
    def __init__(
        self, config_id: int, experiment_id: str, block_id: str,
        process_run_id: str,
    ) -> None:
        if config_id < 0 or config_id >= 32:
            raise ValueError("isolated config id must be in the range 0..31")
        if not IDENTIFIER_PATTERN.fullmatch(experiment_id):
            raise ValueError("experiment id contains unsupported characters")
        if len(experiment_id) > 64:
            raise ValueError("experiment id is longer than 64 characters")
        if block_id not in ISOLATION_BLOCKS:
            raise ValueError(f"unknown isolation block {block_id!r}")
        if not IDENTIFIER_PATTERN.fullmatch(process_run_id):
            raise ValueError("process run id contains unsupported characters")
        if len(process_run_id) > 64:
            raise ValueError("process run id is longer than 64 characters")
        self.config_id = config_id
        self.experiment_id = experiment_id
        self.block_id = block_id
        self.process_run_id = process_run_id

    @property
    def baseline(self) -> str:
        return f"B{self.config_id & 3}"

    @property
    def launch_order(self) -> tuple[str, ...]:
        return ISOLATION_BLOCKS[self.block_id]

    @property
    def launch_position(self) -> int:
        return self.launch_order.index(self.baseline)


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


def build_directory(
    suite: str, schedule_id: str = "legacy",
    isolation: IsolationSpec | None = None,
) -> str:
    if suite == "isolated":
        if isolation is None:
            raise ValueError("isolated suite requires an isolation specification")
        if schedule_id != "isolated":
            raise ValueError("isolated suite cannot use a baseline schedule")
        return f"perf-isolated-c{isolation.config_id}"
    if isolation is not None:
        raise ValueError(f"suite {suite!r} cannot use an isolation specification")
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
    repo_root: Path, suite: str, schedule_id: str = "legacy",
    isolation: IsolationSpec | None = None,
) -> Path:
    build_dir = build_directory(suite, schedule_id, isolation)
    return dirtygen_dir(repo_root) / "build" / build_dir / "dirtygen_perf.elf"


def build_command(
    repo_root: Path, suite: str, schedule_id: str = "legacy",
    isolation: IsolationSpec | None = None,
) -> list[str]:
    if suite == "isolated":
        if isolation is None:
            raise ValueError("isolated suite requires an isolation specification")
        build_directory(suite, schedule_id, isolation)
        return [
            "make",
            "-C",
            str(dirtygen_dir(repo_root)),
            "perf-isolated",
            f"PERF_ISOLATED_CONFIG={isolation.config_id}",
        ]
    if isolation is not None:
        raise ValueError(f"suite {suite!r} cannot use an isolation specification")
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
    suite: str, mode: str, schedule_id: str = "legacy", seed: int = 2,
    isolation: IsolationSpec | None = None,
) -> str:
    if suite == "isolated":
        if isolation is None:
            raise ValueError("isolated suite requires an isolation specification")
        return (
            f"shdlt_dirtygen_perf_isolated_{mode}_{isolation.experiment_id}_"
            f"{isolation.block_id.lower()}_c{isolation.config_id}_seed{seed}_"
            f"{isolation.process_run_id}"
        )
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
    isolation: IsolationSpec | None = None,
) -> list[str]:
    config = cpu_config(seed)
    name = simulation_name(suite, mode, schedule_id, seed, isolation)
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
        str(elf_path(repo_root, suite, schedule_id, isolation)),
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
    isolation: IsolationSpec | None = None,
) -> list[str]:
    script = dirtygen_dir(repo_root) / "tools" / "dirtygen_perf_report.py"
    command = [
        sys.executable,
        str(script),
        str(console),
        "--suite",
        suite,
    ]
    if suite == "isolated":
        if isolation is None:
            raise ValueError("isolated suite requires an isolation specification")
        command.extend(("--config-id", str(isolation.config_id)))
    else:
        if isolation is not None:
            raise ValueError(f"suite {suite!r} cannot use isolation")
        command.extend(("--schedule-id", schedule_id))
    command.extend(("--output-dir", str(report_dir)))
    return command


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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def elf_fingerprints(path: Path) -> dict[str, Any]:
    """Hash the ELF code sections and the measured guest workload range."""
    payload = path.read_bytes()
    header_format = "<16sHHIQQQIHHHHHH"
    section_format = "<IIQQQQIIQQ"
    symbol_format = "<IBBHQQ"
    header_size = struct.calcsize(header_format)
    section_size = struct.calcsize(section_format)
    symbol_size = struct.calcsize(symbol_format)

    if len(payload) < header_size:
        raise ValueError("ELF header is truncated")
    header = struct.unpack_from(header_format, payload)
    identity = header[0]
    if identity[:4] != b"\x7fELF" or identity[4] != 2 or identity[5] != 1:
        raise ValueError("artifact is not a little-endian ELF64 image")

    section_offset = header[6]
    section_entry_size = header[11]
    section_count = header[12]
    section_names_index = header[13]
    if section_entry_size < section_size or section_count == 0:
        raise ValueError("ELF section table is missing or unsupported")
    if section_names_index >= section_count:
        raise ValueError("ELF section-name table index is invalid")
    if section_offset + section_entry_size * section_count > len(payload):
        raise ValueError("ELF section table is truncated")

    sections: list[dict[str, int | str]] = []
    for index in range(section_count):
        offset = section_offset + index * section_entry_size
        values = struct.unpack_from(section_format, payload, offset)
        sections.append({
            "name_offset": values[0],
            "type": values[1],
            "address": values[3],
            "offset": values[4],
            "size": values[5],
            "link": values[6],
            "entry_size": values[9],
        })

    def section_payload(section: dict[str, int | str]) -> bytes:
        offset = int(section["offset"])
        size = int(section["size"])
        if offset + size > len(payload):
            raise ValueError("ELF section contents are truncated")
        return payload[offset:offset + size]

    names_payload = section_payload(sections[section_names_index])

    def string_at(strings: bytes, offset: int) -> str:
        if offset >= len(strings):
            raise ValueError("ELF string-table offset is invalid")
        end = strings.find(b"\0", offset)
        if end < 0:
            raise ValueError("ELF string table is unterminated")
        return strings[offset:end].decode("ascii")

    named_sections: dict[str, dict[str, int | str]] = {}
    for section in sections:
        name = string_at(names_payload, int(section["name_offset"]))
        section["name"] = name
        named_sections[name] = section
    for required in (".text", ".text.init", ".symtab"):
        if required not in named_sections:
            raise ValueError(f"ELF section is missing: {required}")

    symbol_section = named_sections[".symtab"]
    string_index = int(symbol_section["link"])
    if string_index >= len(sections):
        raise ValueError("ELF symbol string-table index is invalid")
    symbol_strings = section_payload(sections[string_index])
    symbol_payload = section_payload(symbol_section)
    symbol_entry_size = int(symbol_section["entry_size"])
    if symbol_entry_size < symbol_size:
        raise ValueError("ELF symbol table entry size is unsupported")

    wanted = {
        "dirtygen_perf_guest_entry",
        "dirtygen_perf_trap_handler",
    }
    symbols: dict[str, int] = {}
    for offset in range(0, len(symbol_payload), symbol_entry_size):
        if offset + symbol_size > len(symbol_payload):
            raise ValueError("ELF symbol table is truncated")
        values = struct.unpack_from(symbol_format, symbol_payload, offset)
        name = string_at(symbol_strings, values[0])
        if name in wanted:
            symbols[name] = values[4]
    missing = sorted(wanted - symbols.keys())
    if missing:
        raise ValueError(f"ELF workload symbols are missing: {', '.join(missing)}")

    start_symbol = "dirtygen_perf_guest_entry"
    end_symbol = "dirtygen_perf_trap_handler"
    start = symbols[start_symbol]
    end = symbols[end_symbol]
    if end <= start:
        raise ValueError("ELF workload symbol range is empty or reversed")
    workload_section = None
    for section in sections:
        address = int(section["address"])
        size = int(section["size"])
        if address <= start and end <= address + size:
            workload_section = section
            break
    if workload_section is None:
        raise ValueError("ELF workload symbol range does not fit one section")
    section_data = section_payload(workload_section)
    workload_offset = start - int(workload_section["address"])
    workload = section_data[workload_offset:workload_offset + end - start]

    text = section_payload(named_sections[".text"])
    text_init = section_payload(named_sections[".text.init"])
    return {
        "elf_sha256": sha256_bytes(payload),
        "text_sha256": sha256_bytes(text),
        "text_size": len(text),
        "text_init_sha256": sha256_bytes(text_init),
        "text_init_size": len(text_init),
        "workload_code_sha256": sha256_bytes(workload),
        "workload_symbol_range": {
            "start_symbol": start_symbol,
            "end_symbol": end_symbol,
            "start_address": f"0x{start:016x}",
            "end_address": f"0x{end:016x}",
            "size": len(workload),
            "section": str(workload_section["name"]),
        },
    }


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
    isolation: IsolationSpec | None = None,
) -> dict[str, Any]:
    repositories = repository_states(repo_root)
    trace_required = mode == "rvls"
    trace_requested = "--with-rvls-log" in mill
    run_id = isolation.process_run_id if isolation is not None else uuid.uuid4().hex
    metadata = {
        "schema": "shdlt-dirtygen-perf-campaign-v2",
        "run_id": run_id,
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
            "elf": str(elf_path(repo_root, suite, schedule_id, isolation)),
            "sha256": None,
            "elf_sha256": None,
            "text_sha256": None,
            "text_size": None,
            "text_init_sha256": None,
            "text_init_size": None,
            "workload_code_sha256": None,
            "workload_symbol_range": None,
        },
        "build_exit_code": None,
        "simulation_exit_code": None,
        "report_exit_code": None,
    }
    if isolation is not None:
        metadata.update({
            "experiment_id": isolation.experiment_id,
            "isolation_block_id": isolation.block_id,
            "config_id": isolation.config_id,
            "baseline": isolation.baseline,
            "fresh_reset": True,
            "launch_order": list(isolation.launch_order),
            "launch_position": isolation.launch_position,
            "process_run_id": isolation.process_run_id,
        })
    return metadata


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
    isolation: IsolationSpec | None = None,
) -> Path:
    return (
        repo_root
        / "simWorkspace"
        / "TestBenchDut"
        / simulation_name(suite, mode, schedule_id, seed, isolation)
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
    isolation: IsolationSpec | None = None,
) -> Path | None:
    if mode != "rvls":
        return None
    source = rvls_trace_path(
        repo_root, suite, mode, schedule_id, seed, isolation
    )
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
    isolation: IsolationSpec | None = None,
) -> Path:
    if suite == "isolated":
        if isolation is None:
            raise ValueError("isolated suite requires an isolation specification")
        leaf = (
            f"isolated-{mode}-{isolation.experiment_id}-"
            f"{isolation.block_id.lower()}-c{isolation.config_id}-seed{seed}"
        )
    else:
        leaf = f"{suite}-{mode}-{schedule_id.lower()}-seed{seed}"
    return (
        dirtygen_dir(repo_root)
        / "build"
        / "campaign"
        / "dirtygen-perf"
        / leaf
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one reproducible SHDLT dirtygen performance campaign"
    )
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--mode", choices=("architecture", "rvls"), required=True)
    parser.add_argument("--schedule-id", choices=SCHEDULE_IDS)
    parser.add_argument("--config-id", type=int)
    parser.add_argument("--experiment-id")
    parser.add_argument("--isolation-block-id", choices=tuple(ISOLATION_BLOCKS))
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    metadata: dict[str, Any] | None = None
    metadata_path: Path | None = None
    original_handlers: dict[int, Any] = {}
    active_stage: str | None = "setup"

    isolation: IsolationSpec | None = None
    if args.suite == "isolated":
        if args.schedule_id is not None:
            parser.error("--suite isolated does not accept --schedule-id")
        missing = [
            option
            for option, value in (
                ("--config-id", args.config_id),
                ("--experiment-id", args.experiment_id),
                ("--isolation-block-id", args.isolation_block_id),
            )
            if value is None
        ]
        if missing:
            parser.error(f"--suite isolated requires {', '.join(missing)}")
        try:
            isolation = IsolationSpec(
                config_id=args.config_id,
                experiment_id=args.experiment_id,
                block_id=args.isolation_block_id,
                process_run_id=uuid.uuid4().hex,
            )
        except ValueError as error:
            parser.error(str(error))
        schedule_id = "isolated"
    else:
        isolated_values = (
            args.config_id,
            args.experiment_id,
            args.isolation_block_id,
        )
        if any(value is not None for value in isolated_values):
            parser.error(
                "--config-id, --experiment-id and --isolation-block-id "
                "require --suite isolated"
            )
        schedule_id = args.schedule_id or "legacy"

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
                repo_root, args.suite, args.mode, schedule_id, args.seed,
                isolation,
            )
        )
        build = build_command(repo_root, args.suite, schedule_id, isolation)
        mill = mill_command(
            repo_root, args.suite, args.mode, schedule_id, args.seed,
            isolation,
        )
        console = output / "console.log"
        report_dir = output / "report"
        report = report_command(
            repo_root, args.suite, console, report_dir, schedule_id,
            isolation,
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
            schedule_id,
            args.seed,
            isolation,
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
        elf = elf_path(repo_root, args.suite, schedule_id, isolation)
        if not elf.is_file():
            raise CampaignFailure("artifact", f"ELF is missing: {elf}")
        try:
            fingerprint = elf_fingerprints(elf)
        except (OSError, ValueError) as error:
            raise CampaignFailure(
                "artifact", f"could not fingerprint ELF {elf}: {error}"
            ) from error
        metadata["artifact"].update(fingerprint)
        metadata["artifact"]["sha256"] = fingerprint["elf_sha256"]
        write_metadata(metadata_path, metadata)

        trace_before = trace_signature(
            rvls_trace_path(
                repo_root,
                args.suite,
                args.mode,
                schedule_id,
                args.seed,
                isolation,
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
                schedule_id,
                args.seed,
                isolation,
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
