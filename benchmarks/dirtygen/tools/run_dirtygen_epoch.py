#!/usr/bin/env python3
"""Build and run one fresh-process dirty-epoch backend selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from run_dirtygen_perf import (command_record, dirtygen_dir, find_repo_root,
                               finish_metadata, now, repository_states,
                               toolchain_information, top_level_gitlinks,
                               write_metadata)


SCHEMA = "shdlt-dirtygen-epoch-campaign-v1"
BACKENDS = {"pte-scan-serial": 0, "shdlt-log": 1}
BLOCKS = {"E0": ("pte-scan-serial", "shdlt-log"),
          "E1": ("shdlt-log", "pte-scan-serial")}
SINGLE_VALUES = {"unique": (1, 8, 32, 128),
                 "repeat": (1, 8, 128, 4096)}
MC_WORKLOADS = {"private-strong": 0, "private-weak": 1, "same-pte": 2}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class RunFailure(RuntimeError):
    def __init__(self, stage: str, message: str, code: int = 1):
        super().__init__(message)
        self.stage, self.code = stage, code or 1


class RunInterrupted(RuntimeError):
    def __init__(self, signum: int):
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scoped_files(repository: Path, relative: str) -> list[Path]:
    """Enumerate source files without entering generated/metadata trees."""
    candidate = repository / relative
    if candidate.is_file():
        return [candidate]
    result: list[Path] = []
    for directory, directories, files in os.walk(candidate, followlinks=False):
        directories[:] = [name for name in directories
                          if name not in ("build", ".git", "__pycache__")]
        base = Path(directory)
        result.extend(base / name for name in files
                      if not name.endswith(".pyc"))
    return result


def run_logged(command: list[str], cwd: Path, log: Path,
               timeout_seconds: int = 1800) -> int:
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=stream,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            stream.write(f"\nHOST_TIMEOUT {timeout_seconds}s: verification incomplete\n")
            return 124
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise


def build_directory(profile: str, workload: str, value: int | None,
                    harts: int, backend: str) -> str:
    if profile == "single":
        kind = "p" if workload == "unique" else "o"
        return f"perf-epoch-v1-{workload}-{kind}{value}-{backend}"
    return f"perf-mc-epoch-v1-h{harts}-{workload}-{backend}"


def elf_path(root: Path, profile: str, workload: str, value: int | None,
             harts: int, backend: str) -> Path:
    image = "dirtygen_perf_epoch.elf" if profile == "single" else "dirtygen_perf_mc_epoch.elf"
    return dirtygen_dir(root) / "build" / build_directory(profile, workload, value, harts, backend) / image


def build_command(root: Path, profile: str, workload: str, value: int | None,
                  harts: int, backend: str) -> list[str]:
    command = ["make", "-C", str(dirtygen_dir(root))]
    if profile == "single":
        command += ["perf-epoch", f"PERF_EPOCH_PATTERN={workload}",
                    f"PERF_EPOCH_VALUE={value}"]
    else:
        command += ["perf-mc-epoch", f"PERF_MC_HARTS={harts}",
                    f"PERF_MC_WORKLOAD={workload}"]
    command.append(f"PERF_EPOCH_BACKEND={backend}")
    return command


def cpu_config(profile: str, harts: int, seed: int) -> dict[str, Any]:
    performance_counters = 4 if profile == "mc" else 0
    return {"xlen": 64, "cpu_count": harts, "physical_width": 32,
            "reset_vector": "0x80000000",
            "isa": "h,m,a,c,svadu,shdlt,zicntr", "fetch_l1": True,
            "lsu_l1": True, "lsu_l1_coherency": harts > 1,
            "performance_counters": performance_counters,
            "pass_policy": "all", "fail_policy": "any",
            "fail_after": 2_000_000_000, "dbus_ready_factor": "1.01",
            "memory_latency": 0, "seed": seed, "stdin": False}


def simulation_name(profile: str, workload: str, value: int | None, harts: int,
                    backend: str, block: str, experiment: str, mode: str,
                    seed: int, run_id: str) -> str:
    selection = (f"{workload}-{value}" if profile == "single"
                 else f"h{harts}-{workload}")
    return (f"shdlt_epoch_{mode}_{experiment}_{block.lower()}_{profile}_"
            f"{selection}_{backend}_seed{seed}_{run_id}")


def mill_command(root: Path, profile: str, workload: str, value: int | None,
                 harts: int, backend: str, block: str, experiment: str,
                 mode: str, seed: int, run_id: str,
                 trace_mode: str = "required") -> list[str]:
    mill = shutil.which("mill")
    if mill is None:
        raise RuntimeError("mill was not found in PATH")
    config = cpu_config(profile, harts, seed)
    command = ["/bin/sh", mill, "--no-server", "Test[2.13.12].runMain",
               "vexiiriscv.tester.TestBench", "--xlen", "64",
               "--cpu-count", str(harts), "--physical-width", "32",
               "--reset-vector", "0x80000000", "--with-isa", config["isa"],
               "--with-fetch-l1", "--with-lsu-l1"]
    if harts > 1:
        command.append("--lsu-l1-coherency")
    if config["performance_counters"] != 0:
        command += ["--performance-counters",
                    str(config["performance_counters"])]
    command += ["--load-elf", str(elf_path(root, profile, workload, value,
                                            harts, backend)),
                "--pass-symbol", "pass", "--fail-symbol", "fail",
                "--pass-policy", "all", "--fail-policy", "any",
                "--fail-after", str(config["fail_after"]),
                "--dbus-ready-factor", config["dbus_ready_factor"],
                "--memory-latency", "0", "--seed", str(seed), "--name",
                simulation_name(profile, workload, value, harts, backend,
                                block, experiment, mode, seed, run_id)]
    if trace_mode == "required":
        command.append("--with-rvls-log")
    if mode == "architecture":
        command.append("--no-rvls-check")
    command.append("--no-stdin")
    return command


def report_command(root: Path, console: Path, tracer: Path, output: Path,
                   elf: Path, profile: str, workload: str, value: int | None,
                   harts: int, backend: str,
                   trace_mode: str = "required") -> list[str]:
    command = [sys.executable, str(dirtygen_dir(root) / "tools" /
                                   "dirtygen_epoch_report.py"), str(console),
               "--profile", profile, "--workload", workload,
               "--hart-count", str(harts), "--backend", backend,
               "--elf", str(elf), "--output-dir", str(output)]
    if trace_mode == "required":
        command += ["--tracer", str(tracer)]
    else:
        command.append("--without-trace")
    if value is not None:
        command += ["--value", str(value)]
    return command


def section_bytes(elf: Path, section: str) -> bytes:
    try:
        return subprocess.check_output(["riscv64-elf-objcopy", "-O", "binary",
                                        f"--only-section={section}", str(elf),
                                        "/dev/stdout"])
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunFailure("artifact", f"cannot read ELF section {section}: {error}") from error


def nm_symbols(elf: Path, profile: str, workload: str) -> dict[str, int]:
    if profile == "single":
        start = ("dirtygen_perf_unique_timed_start" if workload == "unique"
                 else "dirtygen_perf_repeat_timed_start")
        wanted = {"dirtygen_perf_guest_entry", "dirtygen_perf_trap_handler",
                  start, "dirtygen_perf_timed_end",
                  "dirtygen_perf_epoch_trace_start", "dirtygen_perf_epoch_trace_end",
                  "dirtygen_perf_epoch_selection"}
    else:
        wanted = {"dirtygen_perf_mc_guest_start", "dirtygen_perf_mc_guest_end",
                  "dirtygen_perf_mc_timed_start", "dirtygen_perf_mc_timed_end",
                  "dirtygen_perf_mc_epoch_start", "dirtygen_perf_mc_epoch_end",
                  "dirtygen_perf_mc_selection"}
    try:
        output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunFailure("artifact", f"cannot read ELF symbols: {error}") from error
    symbols = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted:
            symbols[parts[2]] = int(parts[0], 16)
    if set(symbols) != wanted:
        raise RunFailure("artifact", f"ELF lacks symbols {sorted(wanted - set(symbols))}")
    return symbols


def fingerprints(elf: Path, profile: str, workload: str) -> dict[str, Any]:
    symbols = nm_symbols(elf, profile, workload)
    if profile == "single":
        section, fmt = ".perf_epoch_selection", "<Q8I3Q"
        raw = section_bytes(elf, section)
        values = struct.unpack(fmt, raw)
        selection = {"magic": f"0x{values[0]:016x}", "abi_version": values[1],
                     "backend": values[2], "workload": values[3],
                     "hart_count": values[4], "dirty_pages": values[5],
                     "operations": values[6], "tracked_pages": values[7],
                     "runs": values[8]}
        code = section_bytes(elf, ".text.init")
        base = symbols["dirtygen_perf_guest_entry"]
        workload_end = symbols["dirtygen_perf_trap_handler"]
        timed_name = ("dirtygen_perf_unique_timed_start" if workload == "unique"
                      else "dirtygen_perf_repeat_timed_start")
        start, end = symbols[timed_name], symbols["dirtygen_perf_timed_end"]
        # .text.init is linked at 0x80000000 for this profile.
        code_base = 0x80000000
    else:
        section = ".perf_mc_selection"
        raw = section_bytes(elf, section)
        values = struct.unpack("<8Q", raw)
        selection = {"magic": f"0x{values[0]:016x}", "abi_version": values[1],
                     "hart_count": values[2], "workload": values[3],
                     "backend": values[6], "runtime_mode": values[4],
                     "tracked_pages": values[7], "runs": values[5]}
        code = section_bytes(elf, ".text.guest")
        base = symbols["dirtygen_perf_mc_guest_start"]
        workload_end = symbols["dirtygen_perf_mc_guest_end"]
        start, end = symbols["dirtygen_perf_mc_timed_start"], symbols["dirtygen_perf_mc_timed_end"]
        code_base = base
    workload_lo, workload_hi = base - code_base, workload_end - code_base
    timed_lo, timed_hi = start - code_base, end - code_base
    if min(workload_lo, timed_lo) < 0 or workload_hi > len(code) or timed_hi > len(code) or timed_hi < timed_lo:
        raise RunFailure("artifact", "ELF code-window symbols are inconsistent")
    return {"elf_sha256": sha256_file(elf),
            "text_sha256": sha256_bytes(section_bytes(elf, ".text")),
            "text_init_sha256": sha256_bytes(section_bytes(elf, ".text.init")),
            "workload_code_sha256": sha256_bytes(code[workload_lo:workload_hi]),
            "timed_window_sha256": sha256_bytes(code[timed_lo:timed_hi]),
            "workload_symbol_range": {"start_address": f"0x{base:016x}",
                                      "end_address": f"0x{workload_end:016x}",
                                      "timed_start_address": f"0x{start:016x}",
                                      "timed_end_address": f"0x{end:016x}"},
            "key_symbols": {name: f"0x{address:016x}" for name, address in sorted(symbols.items())},
            "selection_sha256": sha256_bytes(raw), "selection": selection}


def source_fingerprint(root: Path) -> dict[str, Any]:
    repositories = repository_states(root)
    scopes = {"VexiiRiscv": (root, ("src/main/scala/vexiiriscv/test",
                                    "src/main/scala/vexiiriscv/memory/PteUpdatePlugin.scala")),
              "NaxSoftware": (root / "ext/NaxSoftware", ("benchmarks/dirtygen",)),
              "Spike": (root / "ext/riscv-isa-sim", ("riscv/mmu.cc", "riscv/mmu.h", "riscv/simif.h")),
              "RVLS": (root / "ext/rvls", ("src", "bindings"))}
    result: dict[str, Any] = {}
    for name, (repo, paths) in scopes.items():
        rows = []
        for relative in paths:
            for path in scoped_files(repo, relative):
                if not path.is_file():
                    continue
                rows.append({"path": str(path.relative_to(repo)), "sha256": sha256_file(path)})
        rows.sort(key=lambda row: row["path"])
        result[name] = {"head": repositories[name]["head"],
                        "files": rows,
                        "digest": sha256_bytes(json.dumps(rows, sort_keys=True).encode())}
    result["digest"] = sha256_bytes(json.dumps(result, sort_keys=True).encode())
    return result


def trace_path(root: Path, name: str) -> Path:
    workspace = Path(os.environ.get("SPINALSIM_WORKSPACE", "simWorkspace"))
    if not workspace.is_absolute():
        workspace = root / workspace
    return workspace / "TestBenchDut" / name / "tracer.log"


def trace_signature(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def validate_selection(artifact: dict[str, Any], profile: str, workload: str,
                       value: int | None, harts: int, backend: str) -> None:
    if profile == "single":
        expected = {"magic": "0x5348444c54455031", "abi_version": 1,
                    "backend": BACKENDS[backend],
                    "workload": 0 if workload == "unique" else 1,
                    "hart_count": 1,
                    "dirty_pages": value if workload == "unique" else 1,
                    "operations": value, "tracked_pages": 128, "runs": 6}
    else:
        expected = {"magic": "0x5348444c544d4531", "abi_version": 1,
                    "hart_count": harts, "workload": MC_WORKLOADS[workload],
                    "backend": BACKENDS[backend],
                    "runtime_mode": 3 if backend == "shdlt-log" else 2,
                    "tracked_pages": 128, "runs": 6}
    if artifact["selection"] != expected:
        raise RunFailure("artifact", f"ELF selection mismatch: {artifact['selection']!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("single", "mc"), required=True)
    parser.add_argument("--workload", choices=tuple(SINGLE_VALUES | MC_WORKLOADS), required=True)
    parser.add_argument("--value", type=int)
    parser.add_argument("--hart-count", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--backend", choices=tuple(BACKENDS), required=True)
    parser.add_argument("--epoch-block-id", choices=tuple(BLOCKS), required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--mode", choices=("architecture", "rvls"), required=True)
    parser.add_argument("--trace-mode", choices=("required", "disabled"),
                        default="required")
    parser.add_argument("--prebuilt-elf-sha256")
    parser.add_argument("--expected-source-fingerprint")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--host-timeout-seconds", type=int, default=1800)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not IDENTIFIER.fullmatch(args.experiment_id) or len(args.experiment_id) > 64:
        parser.error("invalid experiment id")
    if args.profile == "single":
        if args.workload not in SINGLE_VALUES or args.value not in SINGLE_VALUES.get(args.workload, ()) or args.hart_count != 1:
            parser.error("invalid single profile workload/value/hart-count")
    elif args.workload not in MC_WORKLOADS or args.value is not None:
        parser.error("MC profile requires an MC workload and no --value")
    if args.host_timeout_seconds < 1:
        parser.error("--host-timeout-seconds must be positive")
    if args.mode != "architecture" and args.trace_mode == "disabled":
        parser.error("trace may be disabled only in architecture mode")
    for name in ("prebuilt_elf_sha256", "expected_source_fingerprint"):
        value = getattr(args, name)
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            parser.error(f"--{name.replace('_', '-')} must be a lowercase SHA-256")
    return args


def default_output(root: Path, args: argparse.Namespace) -> Path:
    selection = (f"{args.workload}-{args.value}" if args.profile == "single"
                 else f"h{args.hart_count}-{args.workload}")
    leaf = (f"{args.experiment_id}-{args.epoch_block_id.lower()}-{args.profile}-"
            f"{selection}-{args.backend}-{args.mode}-seed{args.seed}")
    return dirtygen_dir(root) / "build/campaign/dirtygen-epoch" / leaf


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = find_repo_root(Path(__file__))
    run_id = uuid.uuid4().hex
    output = args.output_root or default_output(root, args)
    elf = elf_path(root, args.profile, args.workload, args.value,
                   args.hart_count, args.backend)
    build = build_command(root, args.profile, args.workload, args.value,
                          args.hart_count, args.backend)
    mill = mill_command(root, args.profile, args.workload, args.value,
                        args.hart_count, args.backend, args.epoch_block_id,
                        args.experiment_id, args.mode, args.seed, run_id,
                        args.trace_mode)
    name = simulation_name(args.profile, args.workload, args.value,
                           args.hart_count, args.backend, args.epoch_block_id,
                           args.experiment_id, args.mode, args.seed, run_id)
    console, tracer, report_dir = output / "console.log", output / "tracer.log", output / "report"
    report = report_command(root, console, tracer, report_dir, elf, args.profile,
                            args.workload, args.value, args.hart_count, args.backend,
                            args.trace_mode)
    if args.dry_run:
        print(json.dumps({"schema": SCHEMA, "output_root": str(output),
                          "build": build, "simulation": mill, "report": report,
                          "cpu_config": cpu_config(args.profile,
                                                   args.hart_count, args.seed),
                          "host_timeout_seconds": args.host_timeout_seconds,
                          "trace_mode": args.trace_mode,
                          "prebuilt_elf_sha256": args.prebuilt_elf_sha256,
                          "expected_source_fingerprint":
                              args.expected_source_fingerprint},
                         indent=2, sort_keys=True))
        return 0
    if output.exists():
        print(f"dirtygen epoch runner error: output exists: {output}", file=sys.stderr)
        return 2
    output.mkdir(parents=True)
    metadata_path = output / "metadata.json"
    metadata: dict[str, Any] | None = None
    handlers: dict[int, Any] = {}

    def interrupt(signum: int, _frame: Any) -> None:
        raise RunInterrupted(signum)

    try:
        repositories = repository_states(root)
        source = source_fingerprint(root)
        metadata = {"schema": SCHEMA, "status": "initialized", "exit_code": None,
            "failure_stage": None, "failure_message": None, "start_time": now(),
            "end_time": None, "run_id": run_id, "process_run_id": run_id,
            "experiment_id": args.experiment_id,
            "epoch_block_id": args.epoch_block_id,
            "launch_order": list(BLOCKS[args.epoch_block_id]),
            "launch_position": BLOCKS[args.epoch_block_id].index(args.backend),
            "fresh_reset": True, "profile": args.profile,
            "hart_count": args.hart_count, "workload": args.workload,
            "value": args.value, "backend": args.backend, "mode": args.mode,
            "simulation_seed": args.seed,
            "host_timeout_seconds": args.host_timeout_seconds,
            "trace_mode": args.trace_mode,
            "trace_required": args.trace_mode == "required",
            "trace_requested": args.trace_mode == "required",
            "trace_generated": False, "trace_path": None,
            "build_mode": ("prebuilt" if args.prebuilt_elf_sha256 is not None
                           else "local"),
            "repositories": repositories,
            "top_level_gitlinks": top_level_gitlinks(root, repositories),
            "source_fingerprint": source,
            "toolchain": toolchain_information(mill),
            "cpu_config": cpu_config(args.profile, args.hart_count, args.seed),
            "execution_environment": {"MILL_OUTPUT_DIR": os.environ.get("MILL_OUTPUT_DIR"),
                                      "SPINALSIM_WORKSPACE": os.environ.get("SPINALSIM_WORKSPACE")},
            "commands": {"build": command_record(build),
                         "simulation": command_record(mill),
                         "report": command_record(report)},
            "artifact": {"elf": str(elf), "elf_sha256": None,
                         "text_sha256": None, "text_init_sha256": None,
                         "workload_code_sha256": None,
                         "timed_window_sha256": None,
                         "workload_symbol_range": None, "key_symbols": None,
                         "selection_sha256": None, "selection": None},
            "build_exit_code": None, "simulation_exit_code": None,
            "report_exit_code": None}
        write_metadata(metadata_path, metadata)
        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, interrupt)
        metadata["status"] = "running"; write_metadata(metadata_path, metadata)
        if args.expected_source_fingerprint is not None and \
                source["digest"] != args.expected_source_fingerprint:
            raise RunFailure("fingerprint", "source fingerprint differs from prebuild")
        if args.prebuilt_elf_sha256 is None:
            code = run_logged(build, root, output / "build.log")
            metadata["build_exit_code"] = code; write_metadata(metadata_path, metadata)
            if code:
                raise RunFailure("build", f"build exited {code}", code)
        if not elf.is_file():
            raise RunFailure("artifact", f"missing ELF {elf}")
        if args.prebuilt_elf_sha256 is not None and \
                sha256_file(elf) != args.prebuilt_elf_sha256:
            raise RunFailure("fingerprint", "prebuilt ELF hash differs")
        artifact = fingerprints(elf, args.profile, args.workload)
        validate_selection(artifact, args.profile, args.workload, args.value,
                           args.hart_count, args.backend)
        metadata["artifact"].update(artifact); write_metadata(metadata_path, metadata)
        raw = trace_path(root, name)
        before = trace_signature(raw)
        code = run_logged(mill, root, console, args.host_timeout_seconds)
        metadata["simulation_exit_code"] = code
        after = trace_signature(raw)
        generated = after is not None and after != before
        if generated:
            shutil.copy2(raw, tracer)
            metadata["trace_generated"] = True; metadata["trace_path"] = "tracer.log"
        write_metadata(metadata_path, metadata)
        if code:
            raise RunFailure("simulation", f"simulation exited {code}; verification incomplete", code)
        if args.trace_mode == "required" and not generated:
            raise RunFailure("trace", "fresh tracer was not generated")
        if args.trace_mode == "disabled" and generated:
            raise RunFailure("trace", "trace was generated while disabled")
        code = run_logged(report, root, output / "report.log")
        metadata["report_exit_code"] = code; write_metadata(metadata_path, metadata)
        if code:
            raise RunFailure("report", f"report exited {code}", code)
        if args.prebuilt_elf_sha256 is not None and \
                sha256_file(elf) != args.prebuilt_elf_sha256:
            raise RunFailure("fingerprint", "prebuilt ELF changed during run")
        finish_metadata(metadata, "passed", 0); write_metadata(metadata_path, metadata)
        return 0
    except RunInterrupted as error:
        code = 128 + error.signum
        if metadata is not None:
            finish_metadata(metadata, "interrupted", code, "internal", str(error)); write_metadata(metadata_path, metadata)
        return code
    except KeyboardInterrupt:
        if metadata is not None:
            finish_metadata(metadata, "interrupted", 130, "internal", "KeyboardInterrupt"); write_metadata(metadata_path, metadata)
        return 130
    except RunFailure as error:
        if metadata is not None:
            finish_metadata(metadata, "failed", error.code, error.stage, str(error)); write_metadata(metadata_path, metadata)
        print(f"dirtygen epoch runner error: {error}", file=sys.stderr)
        return error.code
    except Exception as error:
        if metadata is not None:
            finish_metadata(metadata, "failed", 1, "internal", str(error)); write_metadata(metadata_path, metadata)
        print(f"dirtygen epoch runner error: {error}", file=sys.stderr)
        return 1
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
