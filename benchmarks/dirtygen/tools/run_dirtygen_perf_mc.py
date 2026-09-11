#!/usr/bin/env python3
"""Build and run one fresh-reset dirtygen_perf_mc selection."""

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
                               toolchain_information,
                               top_level_gitlinks, trace_signature,
                               write_metadata)


BLOCKS = {
    "I0": ("B0", "B1", "B3", "B2"),
    "I1": ("B1", "B2", "B0", "B3"),
    "I2": ("B2", "B3", "B1", "B0"),
    "I3": ("B3", "B0", "B2", "B1"),
}
WORKLOAD_IDS = {"private-strong": 0, "private-weak": 1, "same-pte": 2,
                "prefilled-same-pte": 3}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def run_logged(command: list[str], cwd: Path, log: Path) -> int:
    """Bound the entire simulator process group, including on interruption."""
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            stream.write("\nHOST_TIMEOUT 1800s: verification incomplete, not an ISA verdict\n")
            return 124
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise


class RunFailure(RuntimeError):
    def __init__(self, stage: str, message: str, code: int = 1):
        super().__init__(message); self.stage = stage; self.code = code or 1


class RunInterrupted(RuntimeError):
    def __init__(self, signum: int):
        super().__init__(f"interrupted by signal {signum}"); self.signum = signum


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def cpu_config(harts: int, seed: int) -> dict[str, Any]:
    return {
        "xlen": 64, "cpu_count": harts, "physical_width": 32,
        "reset_vector": "0x80000000", "isa": "h,m,a,c,svadu,shdlt,zicntr",
        "fetch_l1": True, "lsu_l1": True,
        "lsu_l1_coherency": harts > 1, "performance_counters": 4,
        "pass_policy": "all", "fail_policy": "any", "fail_after": 2_000_000_000,
        "dbus_ready_factor": "1.01", "memory_latency": 0, "seed": seed,
        "stdin": False,
    }


def build_dir(harts: int, workload: str, baseline: str) -> str:
    if workload == "prefilled-same-pte":
        return f"perf-mc-v2-prefilled-h{harts}-b{baseline[1:]}"
    return f"perf-mc-v2-h{harts}-{workload}-b{baseline[1:]}"


def elf_path(root: Path, harts: int, workload: str, baseline: str) -> Path:
    image = ("dirtygen_perf_mc_prefilled.elf"
             if workload == "prefilled-same-pte" else "dirtygen_perf_mc.elf")
    return dirtygen_dir(root) / "build" / build_dir(harts, workload, baseline) / image


def build_command(root: Path, harts: int, workload: str, baseline: str) -> list[str]:
    target = "perf-mc-prefilled" if workload == "prefilled-same-pte" else "perf-mc"
    command = ["make", "-C", str(dirtygen_dir(root)), target,
               f"PERF_MC_HARTS={harts}"]
    if workload != "prefilled-same-pte":
        command.append(f"PERF_MC_WORKLOAD={workload}")
    command.append(f"PERF_MC_BASELINE={baseline[1:]}")
    return command


def simulation_name(harts: int, workload: str, baseline: str, block: str,
                    experiment: str, mode: str, seed: int, run_id: str) -> str:
    return (f"shdlt_dirtygen_perf_mc_{mode}_{experiment}_{block.lower()}_"
            f"h{harts}_{workload}_b{baseline[1:]}_seed{seed}_{run_id}")


def mill_command(root: Path, harts: int, workload: str, baseline: str,
                 block: str, experiment: str, mode: str, seed: int,
                 run_id: str) -> list[str]:
    mill = shutil.which("mill")
    if mill is None: raise RuntimeError("mill was not found in PATH")
    config = cpu_config(harts, seed)
    command = ["/bin/sh", mill, "--no-server", "Test[2.13.12].runMain",
               "vexiiriscv.tester.TestBench", "--xlen", "64", "--cpu-count", str(harts),
               "--physical-width", "32", "--reset-vector", "0x80000000",
               "--with-isa", config["isa"], "--with-fetch-l1", "--with-lsu-l1"]
    if harts > 1: command.append("--lsu-l1-coherency")
    command.extend(["--performance-counters", "4", "--load-elf",
                    str(elf_path(root, harts, workload, baseline)),
                    "--pass-symbol", "pass", "--fail-symbol", "fail",
                    "--pass-policy", "all", "--fail-policy", "any",
                    "--fail-after", str(config["fail_after"]),
                    "--dbus-ready-factor", str(config["dbus_ready_factor"]),
                    "--memory-latency", "0", "--seed", str(seed), "--name",
                    simulation_name(harts, workload, baseline, block, experiment, mode, seed, run_id),
                    "--with-rvls-log"])
    if mode == "architecture": command.append("--no-rvls-check")
    command.append("--no-stdin")
    return command


def report_command(root: Path, console: Path, tracer: Path, output: Path,
                   elf: Path, harts: int, workload: str, baseline: str) -> list[str]:
    return [sys.executable, str(dirtygen_dir(root) / "tools" / "dirtygen_perf_mc_report.py"),
            str(console), "--hart-count", str(harts), "--workload", workload,
            "--baseline", baseline, "--tracer", str(tracer), "--elf", str(elf),
            "--output-dir", str(output)]


def section_bytes(elf: Path, section: str) -> bytes:
    try:
        return subprocess.check_output(["riscv64-elf-objcopy", "-O", "binary",
                                        f"--only-section={section}", str(elf), "/dev/stdout"])
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunFailure("artifact", f"cannot read ELF section {section}: {error}") from error


def nm_symbols(elf: Path) -> dict[str, int]:
    wanted = {"dirtygen_perf_mc_guest_start", "dirtygen_perf_mc_guest_end",
              "dirtygen_perf_mc_timed_start", "dirtygen_perf_mc_timed_end",
              "dirtygen_perf_mc_epoch_start", "dirtygen_perf_mc_epoch_end",
              "dirtygen_perf_mc_prepare_next", "dirtygen_perf_mc_record_trap",
              "dirtygen_perf_mc_complete", "dirtygen_perf_mc_selection"}
    try: output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunFailure("artifact", f"cannot read ELF symbols: {error}") from error
    symbols: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted: symbols[parts[2]] = int(parts[0], 16)
    missing = wanted - set(symbols)
    if missing: raise RunFailure("artifact", f"ELF lacks symbols {sorted(missing)}")
    return symbols


def fingerprints(elf: Path) -> dict[str, Any]:
    symbols = nm_symbols(elf)
    selection = section_bytes(elf, ".perf_mc_selection")
    if len(selection) != 64: raise RunFailure("artifact", "selection section is not 64 bytes")
    values = struct.unpack("<8Q", selection)
    guest = section_bytes(elf, ".text.guest")
    start, end = symbols["dirtygen_perf_mc_guest_start"], symbols["dirtygen_perf_mc_guest_end"]
    timed_start = symbols["dirtygen_perf_mc_timed_start"] - start
    timed_end = symbols["dirtygen_perf_mc_timed_end"] - start
    if timed_start < 0 or timed_end < timed_start or timed_end > len(guest):
        raise RunFailure("artifact", "timed-window symbols are outside .text.guest")
    return {
        "elf_sha256": sha256_file(elf), "text_sha256": sha256_bytes(section_bytes(elf, ".text")),
        "text_init_sha256": sha256_bytes(section_bytes(elf, ".text.init")),
        "workload_code_sha256": sha256_bytes(guest),
        "timed_window_sha256": sha256_bytes(guest[timed_start:timed_end]),
        "workload_symbol_range": {"start_symbol": "dirtygen_perf_mc_guest_start",
                                  "end_symbol": "dirtygen_perf_mc_guest_end",
                                  "start_address": f"0x{start:016x}", "end_address": f"0x{end:016x}",
                                  "size": end - start, "timed_start_address": f"0x{symbols['dirtygen_perf_mc_timed_start']:016x}",
                                  "timed_end_address": f"0x{symbols['dirtygen_perf_mc_timed_end']:016x}"},
        "key_symbols": {name: f"0x{value:016x}" for name, value in sorted(symbols.items())},
        "selection_sha256": sha256_bytes(selection),
        "selection": {"magic": f"0x{values[0]:016x}", "abi_version": values[1],
                      "hart_count": values[2], "workload": values[3],
                      "baseline": values[4], "runs": values[5]},
    }


def trace_path(root: Path, name: str) -> Path:
    workspace = Path(os.environ.get("SPINALSIM_WORKSPACE", "simWorkspace"))
    if not workspace.is_absolute():
        workspace = root / workspace
    return workspace / "TestBenchDut" / name / "tracer.log"


def initial_metadata(root: Path, harts: int, workload: str, baseline: str,
                     block: str, experiment: str, mode: str, seed: int,
                     run_id: str, build: list[str], mill: list[str], report: list[str]) -> dict[str, Any]:
    repos = repository_states(root)
    return {"schema": "shdlt-dirtygen-perf-mc-campaign-v2", "status": "initialized",
            "exit_code": None, "failure_stage": None, "failure_message": None,
            "start_time": now(), "end_time": None, "run_id": run_id,
            "process_run_id": run_id, "experiment_id": experiment,
            "isolation_block_id": block, "launch_order": list(BLOCKS[block]),
            "launch_position": BLOCKS[block].index(baseline), "fresh_reset": True,
            "hart_count": harts, "workload": workload, "baseline": baseline,
            "counter_contract": "abi-v2:5*N+5;CSR-I-fences", "host_timeout_seconds": 1800,
            "mode": mode, "simulation_seed": seed, "trace_required": True,
            "trace_requested": True, "trace_generated": False, "trace_path": None,
            "repositories": repos, "top_level_gitlinks": top_level_gitlinks(root, repos),
            "toolchain": toolchain_information(mill), "cpu_config": cpu_config(harts, seed),
            "execution_environment": {
                "MILL_OUTPUT_DIR": os.environ.get("MILL_OUTPUT_DIR"),
                "SPINALSIM_WORKSPACE": os.environ.get("SPINALSIM_WORKSPACE"),
            },
            "commands": {"build": command_record(build), "simulation": command_record(mill),
                         "report": command_record(report)},
            "artifact": {"elf": str(elf_path(root, harts, workload, baseline)),
                         "elf_sha256": None, "text_sha256": None,
                         "text_init_sha256": None, "workload_code_sha256": None,
                         "timed_window_sha256": None,
                         "workload_symbol_range": None, "key_symbols": None,
                         "selection_sha256": None, "selection": None},
            "build_exit_code": None, "simulation_exit_code": None, "report_exit_code": None}


def default_output(root: Path, experiment: str, block: str, harts: int,
                   workload: str, baseline: str, mode: str, seed: int) -> Path:
    return dirtygen_dir(root) / "build" / "campaign" / "dirtygen-perf-mc" / (
        f"{experiment}-{block.lower()}-h{harts}-{workload}-{baseline.lower()}-{mode}-seed{seed}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hart-count", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--workload", choices=tuple(WORKLOAD_IDS), required=True)
    parser.add_argument("--baseline", choices=("B0", "B1", "B2", "B3"), required=True)
    parser.add_argument("--isolation-block-id", choices=tuple(BLOCKS), required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--mode", choices=("architecture", "rvls"), required=True)
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not IDENTIFIER.fullmatch(args.experiment_id) or len(args.experiment_id) > 64:
        parser.error("invalid experiment id")
    if (args.workload == "prefilled-same-pte" and
            (args.hart_count not in (2, 4) or args.baseline not in ("B2", "B3"))):
        parser.error("prefilled-same-pte requires --hart-count 2|4 and --baseline B2|B3")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = find_repo_root(Path(__file__))
    run_id = uuid.uuid4().hex
    output = args.output_root or default_output(root, args.experiment_id,
                                                args.isolation_block_id, args.hart_count,
                                                args.workload, args.baseline, args.mode, args.seed)
    build = build_command(root, args.hart_count, args.workload, args.baseline)
    mill = mill_command(root, args.hart_count, args.workload, args.baseline,
                        args.isolation_block_id, args.experiment_id, args.mode,
                        args.seed, run_id)
    name = simulation_name(args.hart_count, args.workload, args.baseline,
                           args.isolation_block_id, args.experiment_id, args.mode,
                           args.seed, run_id)
    elf = elf_path(root, args.hart_count, args.workload, args.baseline)
    console, tracer, report_dir = output / "console.log", output / "tracer.log", output / "report"
    report = report_command(root, console, tracer, report_dir, elf, args.hart_count,
                            args.workload, args.baseline)
    if args.dry_run:
        print(json.dumps({"output_root": str(output), "build": build, "simulation": mill,
                          "report": report, "cpu_config": cpu_config(args.hart_count, args.seed),
                          "execution_environment": {
                              "MILL_OUTPUT_DIR": os.environ.get("MILL_OUTPUT_DIR"),
                              "SPINALSIM_WORKSPACE": os.environ.get("SPINALSIM_WORKSPACE"),
                          }}, indent=2))
        return 0
    if output.exists():
        print(f"dirtygen perf mc runner error: output exists: {output}", file=sys.stderr); return 2
    output.mkdir(parents=True)
    metadata_path = output / "metadata.json"
    metadata: dict[str, Any] | None = None
    previous_handlers: dict[int, Any] = {}
    def interrupt(signum: int, _frame: Any) -> None:
        raise RunInterrupted(signum)
    try:
        metadata = initial_metadata(root, args.hart_count, args.workload, args.baseline,
                                    args.isolation_block_id, args.experiment_id, args.mode,
                                    args.seed, run_id, build, mill, report)
        write_metadata(metadata_path, metadata)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, interrupt)
        metadata["status"] = "running"; write_metadata(metadata_path, metadata)
        code = run_logged(build, root, output / "build.log"); metadata["build_exit_code"] = code
        if code: raise RunFailure("build", f"build exited {code}", code)
        if not elf.is_file(): raise RunFailure("artifact", f"missing ELF {elf}")
        artifact = fingerprints(elf)
        expected_selection = {"magic": "0x5348444c544d4331", "abi_version": 2,
                              "hart_count": args.hart_count,
                              "workload": WORKLOAD_IDS[args.workload],
                              "baseline": int(args.baseline[1:]), "runs": 6}
        if artifact["selection"] != expected_selection:
            raise RunFailure("artifact", f"ELF selection mismatch: {artifact['selection']!r}")
        metadata["artifact"].update(artifact); write_metadata(metadata_path, metadata)
        raw_trace = trace_path(root, name); before = trace_signature(raw_trace)
        code = run_logged(mill, root, console); metadata["simulation_exit_code"] = code
        after = trace_signature(raw_trace)
        if after is not None and after != before:
            shutil.copy2(raw_trace, tracer)
            metadata["trace_generated"] = True
            metadata["trace_path"] = "tracer.log"
            write_metadata(metadata_path, metadata)
        if code: raise RunFailure("simulation", f"simulation exited {code}; incomplete verification", code)
        if after is None or after == before: raise RunFailure("trace", "fresh tracer was not generated")
        shutil.copy2(raw_trace, tracer); metadata["trace_generated"] = True
        metadata["trace_path"] = "tracer.log"; write_metadata(metadata_path, metadata)
        code = run_logged(report, root, output / "report.log"); metadata["report_exit_code"] = code
        if code: raise RunFailure("report", f"report exited {code}", code)
        finish_metadata(metadata, "passed", 0); write_metadata(metadata_path, metadata); return 0
    except KeyboardInterrupt:
        if metadata is not None:
            finish_metadata(metadata, "interrupted", 130, "internal", "KeyboardInterrupt")
            write_metadata(metadata_path, metadata)
        return 130
    except RunInterrupted as error:
        code = 128 + error.signum
        if metadata is not None:
            finish_metadata(metadata, "interrupted", code, None, str(error))
            write_metadata(metadata_path, metadata)
        return code
    except RunFailure as error:
        if metadata is not None:
            finish_metadata(metadata, "failed", error.code, error.stage, str(error)); write_metadata(metadata_path, metadata)
        print(f"dirtygen perf mc runner error: {error}", file=sys.stderr); return error.code
    except Exception as error:
        if metadata is not None:
            finish_metadata(metadata, "failed", 1, "internal", str(error)); write_metadata(metadata_path, metadata)
        print(f"dirtygen perf mc runner error: {error}", file=sys.stderr); return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
