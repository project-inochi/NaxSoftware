#!/usr/bin/env python3
"""Run one H2/H4 SIZE=0 Phase-4 stale-D/full gate process."""

from __future__ import annotations

import argparse
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

from run_dirtygen_perf import (command_record, find_repo_root, finish_metadata,
                               now, repository_states, toolchain_information,
                               top_level_gitlinks, trace_signature,
                               write_metadata)


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SCHEMA = "shdlt-buffer-boundary-phase4-run-v1"


class RunFailure(RuntimeError):
    def __init__(self, stage: str, message: str, code: int = 1):
        super().__init__(message)
        self.stage = stage
        self.code = code or 1


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dirtygen_dir(root: Path) -> Path:
    return root / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen"


def elf_path(root: Path, harts: int) -> Path:
    return (dirtygen_dir(root) / "build" /
            f"buffer-mc-v1-h{harts}-stale-d-full" /
            "dirtygen_buffer_mc.elf")


def build_command(root: Path, harts: int) -> list[str]:
    return ["make", "-C", str(dirtygen_dir(root)), "buffer-mc",
            f"BUFFER_MC_HARTS={harts}"]


def cpu_config(harts: int, mode: str) -> dict[str, Any]:
    return {
        "xlen": 64, "cpu_count": harts, "physical_width": 32,
        "reset_vector": "0x80000000",
        "isa": "h,m,a,c,svadu,shdlt,zicntr", "fetch_l1": True,
        "lsu_l1": True, "lsu_l1_coherency": True,
        "performance_counters": 4, "pass_policy": "all",
        "fail_policy": "any", "fail_after": 2_000_000_000,
        "dbus_ready_factor": "1.01", "memory_latency": 0, "seed": 2,
        "stdin": False, "rvls_check": mode == "rvls", "raw_physical_trace": True,
    }


def simulation_name(experiment: str, harts: int, mode: str,
                    run_id: str) -> str:
    return (f"shdlt_buffer_phase4_{experiment}_h{harts}_size0_{mode}_"
            f"seed2_{run_id}")


def mill_command(root: Path, experiment: str, harts: int, mode: str,
                 run_id: str) -> list[str]:
    mill = shutil.which("mill")
    if mill is None:
        raise RuntimeError("mill was not found in PATH")
    config = cpu_config(harts, mode)
    command = [
        "/bin/sh", mill, "--no-server", "Test[2.13.12].runMain",
        "vexiiriscv.tester.TestBench", "--xlen", "64", "--cpu-count", str(harts),
        "--physical-width", "32", "--reset-vector", "0x80000000",
        "--with-isa", config["isa"], "--with-fetch-l1", "--with-lsu-l1",
        "--lsu-l1-coherency", "--performance-counters", "4", "--load-elf",
        str(elf_path(root, harts)), "--pass-symbol", "pass", "--fail-symbol", "fail",
        "--pass-policy", "all", "--fail-policy", "any", "--fail-after",
        str(config["fail_after"]), "--dbus-ready-factor",
        str(config["dbus_ready_factor"]), "--memory-latency", "0", "--seed", "2",
        "--name", simulation_name(experiment, harts, mode, run_id),
        "--with-rvls-log",
    ]
    if mode == "architecture":
        command.append("--no-rvls-check")
    command.append("--no-stdin")
    return command


def report_command(root: Path, console: Path, tracer: Path | None,
                   output: Path, harts: int) -> list[str]:
    command = [
        sys.executable,
        str(dirtygen_dir(root) / "tools" / "dirtygen_buffer_mc_report.py"),
        str(console), "--output-dir", str(output), "--hart-count", str(harts),
    ]
    if tracer is not None:
        command.extend(("--tracer", str(tracer), "--elf", str(elf_path(root, harts))))
    return command


def trace_path(root: Path, name: str) -> Path:
    workspace = Path(os.environ.get("SPINALSIM_WORKSPACE", "simWorkspace"))
    if not workspace.is_absolute():
        workspace = root / workspace
    return workspace / "TestBenchDut" / name / "tracer.log"


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
            stream.write(
                f"\nHOST_TIMEOUT {timeout}s: verification incomplete, not an ISA verdict\n"
            )
            return 124
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise


def section_bytes(elf: Path, section: str) -> bytes:
    try:
        return subprocess.check_output([
            "riscv64-elf-objcopy", "-O", "binary", f"--only-section={section}",
            str(elf), "/dev/stdout",
        ])
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunFailure("artifact", f"cannot read ELF section {section}: {error}") from error


def symbols(elf: Path) -> dict[str, int]:
    wanted = {
        "dirtygen_buffer_mc_guest_start", "dirtygen_buffer_mc_guest_end",
        "dirtygen_buffer_mc_observer_store", "dirtygen_buffer_mc_producer_store",
        "dirtygen_buffer_mc_epoch_start", "dirtygen_buffer_mc_epoch_end",
        "pass", "fail",
    }
    try:
        output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunFailure("artifact", f"cannot inspect ELF symbols: {error}") from error
    result: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted:
            result[parts[2]] = int(parts[0], 16)
    if set(result) != wanted:
        raise RunFailure("artifact", f"ELF lacks symbols {sorted(wanted - set(result))}")
    return result


def artifact_fingerprint(elf: Path) -> dict[str, Any]:
    symbol_map = symbols(elf)
    guest = section_bytes(elf, ".text.guest")
    start = symbol_map["dirtygen_buffer_mc_guest_start"]
    end = symbol_map["dirtygen_buffer_mc_guest_end"]
    payload_size = end - start
    # The linker may pad the input section to its requested alignment after
    # guest_end.  Only the symbol-delimited payload is copied at run time.
    if payload_size <= 0 or payload_size > len(guest) or len(guest) > 4096:
        raise RunFailure("artifact", "guest payload is outside one-page .text.guest")
    observer = symbol_map["dirtygen_buffer_mc_observer_store"] - start
    producer = symbol_map["dirtygen_buffer_mc_producer_store"] - start
    if (observer < 0 or producer < 0 or
            max(observer, producer) + 4 > payload_size):
        raise RunFailure("artifact", "guest store symbols lie outside payload")
    return {
        "elf": str(elf), "elf_sha256": sha256_file(elf),
        "text_init_sha256": sha256_bytes(section_bytes(elf, ".text.init")),
        "text_sha256": sha256_bytes(section_bytes(elf, ".text")),
        "guest_section_sha256": sha256_bytes(guest),
        "guest_section_size": len(guest),
        "guest_payload_sha256": sha256_bytes(guest[:payload_size]),
        "guest_payload_size": payload_size,
        "guest_trailing_padding_size": len(guest) - payload_size,
        "symbols": {name: f"0x{value:016x}"
                    for name, value in sorted(symbol_map.items())},
        "guest_runtime_pc": {
            "observer_store": f"0x{observer:x}", "producer_store": f"0x{producer:x}",
        },
    }


def file_fingerprints(root: Path) -> list[dict[str, str]]:
    paths = [
        "ext/NaxSoftware/benchmarks/dirtygen/Makefile",
        "ext/NaxSoftware/benchmarks/dirtygen/linker_buffer_mc.ld",
        "ext/NaxSoftware/benchmarks/dirtygen/include/dirtygen_buffer_mc.h",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_mc.c",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_mc_page_table.c",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_mc_startup.S",
        "ext/NaxSoftware/benchmarks/dirtygen/src/dirtygen_buffer_mc_guest.S",
        "ext/NaxSoftware/benchmarks/dirtygen/tools/dirtygen_buffer_mc_report.py",
        "ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_buffer_mc_phase4.py",
    ]
    return [{"path": path, "sha256": sha256_file(root / path)} for path in paths]


def protected_fingerprints(root: Path) -> list[dict[str, str]]:
    paths = [
        "ext/NaxSoftware/benchmarks/dirtygen/SHDLT_ISA_CONSISTENCY_AUDIT.md",
        "ext/NaxSoftware/benchmarks/dirtygen/SHDLT_DIRTYGEN_PERF_MC_REPORT.md",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_isa_consistency_inputs.json",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_isa_consistency_results.json",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_dirtygen_perf_mc_phase3_inputs.json",
        "ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_dirtygen_perf_mc_phase3_results.json",
    ]
    return [{"path": path, "sha256": sha256_file(root / path)} for path in paths]


def normative_fingerprints() -> dict[str, Any]:
    paths = [
        Path("/mnt/files/inochi/cache/docs/riscv-isa-manual/src/priv/supervisor.adoc"),
        Path("/mnt/files/inochi/cache/docs/riscv-isa-manual/src/priv/hypervisor.adoc"),
        Path("/mnt/files/inochi/cache/docs/riscv-isa-manual/src/priv/machine.adoc"),
        Path("/mnt/files/inochi/cache/docs/riscv-isa-manual/src/priv/svadu.adoc"),
        Path("/mnt/files/inochi/cache/docs/riscv-isa-manual/src/unpriv/rvwmo.adoc"),
        Path("/mnt/files/inochi/cache/docs/riscv-isa-manual/src/unpriv/zifencei.adoc"),
        Path("/mnt/files/inochi/cache/docs/riscv-sbi-doc/src/ext-rfence.adoc"),
        Path("/home/inochi/code/spec/presentation/riscv/shpgat/mail/shdlt.adoc"),
    ]
    return {
        "isa_head": "e5c0c60fa1fbfcc1d343e314299d15693485f678",
        "sbi_head": "8a545effe9b50484ff897d9815d7d9015cdef203",
        "shdlt_version": "RFC v6",
        "files": [{"path": str(path), "sha256": sha256_file(path)} for path in paths],
    }


def load_verdict(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--hart-count", type=int, choices=(2, 4), default=2)
    parser.add_argument("--mode", choices=("architecture", "rvls"),
                        default="architecture")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not IDENTIFIER.fullmatch(args.experiment_id) or len(args.experiment_id) > 64:
        parser.error("invalid experiment id")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = find_repo_root(Path(__file__))
    run_id = uuid.uuid4().hex
    output = args.output_root or (
        dirtygen_dir(root) / "build" / "campaign" /
        "dirtygen-buffer-boundary-phase4" /
        f"{args.experiment_id}-h{args.hart_count}-size0-{args.mode}-seed2"
    )
    build = build_command(root, args.hart_count)
    simulation = mill_command(root, args.experiment_id, args.hart_count,
                              args.mode, run_id)
    name = simulation_name(args.experiment_id, args.hart_count, args.mode,
                           run_id)
    console = output / "console.log"
    archived_trace = output / "tracer.log"
    report_dir = output / "report"
    if args.dry_run:
        print(json.dumps({
            "scope": f"H{args.hart_count}/SIZE=0 {args.mode} gate only",
            "output_root": str(output), "build": build,
            "simulation": simulation,
            "cpu_config": cpu_config(args.hart_count, args.mode),
        }, indent=2))
        return 0
    if output.exists():
        print(f"dirtygen buffer phase4 runner error: output exists: {output}", file=sys.stderr)
        return 2
    output.mkdir(parents=True)
    metadata_path = output / "metadata.json"
    raw_trace = trace_path(root, name)
    report: list[str] | None = None
    metadata: dict[str, Any] = {
        "schema": SCHEMA, "status": "initialized", "exit_code": None,
        "failure_stage": None, "failure_message": None,
        "start_time": now(), "end_time": None, "experiment_id": args.experiment_id,
        "run_id": run_id,
        "scope": (f"STALE_D_FULL_OBSERVERS H{args.hart_count} SIZE=0 "
                  f"{args.mode}"),
        "case": "STALE_D_FULL_OBSERVERS", "case_id": 8,
        "hart_count": args.hart_count,
        "requested_size": 0, "expected_capacity": 512, "mode": args.mode,
        "simulation_seed": 2, "fresh_process": True, "host_timeout_seconds": 1800,
        "trace_required": True, "trace_generated": False, "trace_path": None,
        "cpu_config": cpu_config(args.hart_count, args.mode),
        "repositories": repository_states(root),
        "source_files": file_fingerprints(root),
        "protected_before": protected_fingerprints(root),
        "normative": normative_fingerprints(),
        "top_level_gitlinks": top_level_gitlinks(root, repository_states(root)),
        "toolchain": toolchain_information(simulation),
        "execution_environment": {
            "MILL_OUTPUT_DIR": os.environ.get("MILL_OUTPUT_DIR"),
            "SPINALSIM_WORKSPACE": os.environ.get("SPINALSIM_WORKSPACE"),
        },
        "commands": {
            "build": command_record(build), "simulation": command_record(simulation),
            "report": None,
        },
        "artifact": None, "build_exit_code": None,
        "simulation_exit_code": None, "report_exit_code": None,
        "firmware_verdict": None,
    }
    write_metadata(metadata_path, metadata)
    try:
        metadata["status"] = "running"
        write_metadata(metadata_path, metadata)
        build_code = run_logged(build, root, output / "build.log")
        metadata["build_exit_code"] = build_code
        write_metadata(metadata_path, metadata)
        if build_code:
            raise RunFailure("build", f"build exited {build_code}", build_code)
        elf = elf_path(root, args.hart_count)
        if not elf.is_file():
            raise RunFailure("artifact", f"missing ELF {elf}")
        metadata["artifact"] = artifact_fingerprint(elf)
        assembly = elf.with_suffix(".asm")
        if not assembly.is_file():
            raise RunFailure("artifact", f"missing disassembly {assembly}")
        shutil.copy2(assembly, output / "dirtygen_buffer_mc.asm")
        write_metadata(metadata_path, metadata)

        before = trace_signature(raw_trace)
        simulation_code = run_logged(simulation, root, console, timeout=1800)
        metadata["simulation_exit_code"] = simulation_code
        after = trace_signature(raw_trace)
        if after is not None and after != before:
            shutil.copy2(raw_trace, archived_trace)
            metadata["trace_generated"] = True
            metadata["trace_path"] = "tracer.log"
        report = report_command(
            root, console, archived_trace if metadata["trace_generated"] else None,
            report_dir, args.hart_count,
        )
        metadata["commands"]["report"] = command_record(report)
        write_metadata(metadata_path, metadata)
        report_code = run_logged(report, root, output / "report.log")
        metadata["report_exit_code"] = report_code
        metadata["firmware_verdict"] = load_verdict(report_dir / "verdict.json")
        metadata["protected_after"] = protected_fingerprints(root)
        metadata["protected_after_matches"] = (
            metadata["protected_after"] == metadata["protected_before"]
        )
        metadata["source_after"] = file_fingerprints(root)
        metadata["source_after_matches"] = (
            metadata["source_after"] == metadata["source_files"]
        )
        write_metadata(metadata_path, metadata)
        if simulation_code:
            raise RunFailure(
                "simulation", f"simulation exited {simulation_code}; gate failed or incomplete",
                simulation_code,
            )
        if not metadata["trace_generated"]:
            raise RunFailure("trace", "fresh raw physical trace was not generated")
        if report_code:
            raise RunFailure("report", f"firmware/trace report exited {report_code}", report_code)
        if not metadata["protected_after_matches"] or not metadata["source_after_matches"]:
            raise RunFailure("provenance", "protected or Phase-4 source hashes changed during run")
        finish_metadata(metadata, "passed", 0)
        write_metadata(metadata_path, metadata)
        return 0
    except KeyboardInterrupt:
        finish_metadata(metadata, "interrupted", 130, "internal", "KeyboardInterrupt")
        write_metadata(metadata_path, metadata)
        return 130
    except RunFailure as error:
        if "protected_after" not in metadata:
            metadata["protected_after"] = protected_fingerprints(root)
            metadata["protected_after_matches"] = (
                metadata["protected_after"] == metadata["protected_before"]
            )
        finish_metadata(metadata, "failed", error.code, error.stage, str(error))
        write_metadata(metadata_path, metadata)
        print(f"dirtygen buffer phase4 runner error: {error}", file=sys.stderr)
        return error.code
    except Exception as error:
        finish_metadata(metadata, "failed", 1, "internal", str(error))
        write_metadata(metadata_path, metadata)
        print(f"dirtygen buffer phase4 runner error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
