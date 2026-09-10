#!/usr/bin/env python3
"""Build/run corrected tests without touching the legacy matrix or its ELF files."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

from shdlt_isa_audit import ROOT, NAX, DIRTYGEN, protected_state, sha256
from shdlt_isa_report import build_report, inspect_elf

FAMILIES = {
    "smoke": ("baremetal/multicore_smoke_shdlt", "multicore_smoke_shdlt",
              "load_only log_off predirty widths nonzero_index freeze reset_resume".split()),
    "race": ("baremetal/multicore_race_shdlt", "multicore_race_shdlt",
             "different_pages buffer_isolation same_pte same_cacheline_ptes".split()),
    "ctc": ("benchmarks/cache_tlb_shdlt", "cache_tlb_shdlt",
            "pte_cache_hit_miss remote_pte_reread ownership_transfer coherence_pressure cas_retry hfence_before_after hfence_gpa hfence_vmid hfence_global fence_hart_isolation".split()),
}


@dataclasses.dataclass(frozen=True)
class Selection:
    family: str
    case: str
    harts: int
    producer_delay: int = 0
    consumer_delay: int = 0

    @property
    def name(self) -> str:
        return f"{self.family}-h{self.harts}-{self.case}-p{self.producer_delay}-c{self.consumer_delay}"


def selections(stress: bool = False) -> list[Selection]:
    result = [Selection(family, case, harts) for family, (_, _, cases) in FAMILIES.items()
              for harts in (2, 4) for case in cases]
    if stress:
        result += [Selection(family, case, harts, p, c)
                   for family, case in (("smoke", "widths"), ("ctc", "cas_retry"))
                   for harts in (2, 4) for p, c in ((65536, 0), (0, 65536))]
    return result


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run(command: list[str], log: Path, timeout: int) -> dict:
    start = time.monotonic()
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = 124
    return {"command": command, "exit_code": code, "elapsed_seconds": time.monotonic() - start}


def make_command(selection: Selection, build: Path, profile: str) -> list[str]:
    directory, _, _ = FAMILIES[selection.family]
    return ["make", "-C", str(NAX / directory), f"PROFILE={profile}",
            f"CPU_COUNT={selection.harts}", f"CASE={selection.case}", f"OBJDIR={build}",
            f"PRODUCER_DELAY={selection.producer_delay}", f"CONSUMER_DELAY={selection.consumer_delay}", "all"]


def legacy_elf(selection: Selection) -> Path:
    directory, image, _ = FAMILIES[selection.family]
    if selection.family == "smoke":
        subdir = (f"cpu2s_rv64gc_{selection.case}_shdlt" if selection.harts == 2
                  else f"final4_{selection.case}")
    else:
        subdir = f"cpu{selection.harts}_{selection.case}"
    return NAX / directory / "build" / subdir / f"{image}.elf"


def verify_legacy(output: Path) -> None:
    results = []
    for selection in selections():
        folder = output / "legacy-rebuild" / selection.name
        folder.mkdir(parents=True, exist_ok=True)
        build = folder / "build"
        record = run(make_command(selection, build, "legacy"), folder / "build.log", 180)
        elf = build / (FAMILIES[selection.family][1] + ".elf")
        expected = sha256(legacy_elf(selection))
        actual = sha256(elf) if record["exit_code"] == 0 else None
        result = {"selection": dataclasses.asdict(selection), **record,
                  "expected_sha256": expected, "rebuilt_sha256": actual,
                  "status": "PASS" if actual == expected else "FAIL"}
        results.append(result)
        write_json(output / "legacy-rebuild.json", {"results": results})
        if result["status"] != "PASS":
            raise RuntimeError(f"legacy rebuild changed: {selection.name}")
    print(f"legacy isolated rebuild: PASS ({len(results)} ELF files)", flush=True)


def run_selection(selection: Selection, output: Path, build_only: bool, trace_all: bool = False) -> dict:
    folder = output / "runs" / selection.name
    folder.mkdir(parents=True, exist_ok=False)
    build = folder / "build"
    record = {"selection": dataclasses.asdict(selection), "profile": "isa", "rvls_check": False,
              "status": "RUNNING"}
    path = folder / "run.json"
    write_json(path, record)
    try:
        record["build"] = run(make_command(selection, build, "isa"), folder / "build.log", 180)
        if record["build"]["exit_code"]:
            raise RuntimeError("build failed")
        elf = build / (FAMILIES[selection.family][1] + ".elf")
        record["elf_sha256"] = sha256(elf)
        record["elf_checks"] = inspect_elf(elf, selection.family)
        if build_only:
            record["status"] = "BUILD_PASS"
            return record
        focused_trace = (selection.family, selection.case) in (("ctc", "cas_retry"), ("race", "same_pte"))
        trace_requested = trace_all or selection.family in ("ctc", "race")
        name = f"shdlt_isa_{selection.name}_{uuid.uuid4().hex[:12]}"
        command = ["/bin/sh", "/usr/bin/mill", "--no-server", "Test[2.13.12].runMain",
                   "vexiiriscv.tester.TestBench", "--xlen", "64", "--cpu-count", str(selection.harts),
                   "--physical-width", "32", "--reset-vector", "0x80000000",
                   "--with-isa", "h,m,a,c,svadu,shdlt,zicntr", "--with-fetch-l1", "--with-lsu-l1",
                   "--lsu-l1-coherency", "--performance-counters", "4", "--load-elf", str(elf),
                   "--pass-symbol", "pass", "--fail-symbol", "fail", "--pass-policy", "all",
                   "--fail-policy", "any", "--fail-after", "300000000",
                   "--dbus-ready-factor", "1.01",
                   "--memory-latency", "0", "--seed", "2", "--name", name, "--no-rvls-check", "--no-stdin"]
        if trace_requested:
            command.append("--with-rvls-log")
        console = folder / "console.log"
        record["simulation"] = run(command, console, 1800)
        trace = None
        if trace_requested:
            import shutil
            raw = ROOT / "simWorkspace/TestBenchDut" / name / "tracer.log"
            if raw.is_file():
                trace = folder / "tracer.log"
                shutil.copy2(raw, trace)  # preserve before another TestBench compilation
                record["trace_sha256"] = sha256(trace)
        if record["simulation"]["exit_code"]:
            record["architecture_status"] = "UNVERIFIED"
            if record["simulation"]["exit_code"] == 124 or "Reached Timeout" in console.read_text():
                raise RuntimeError("simulation budget exhausted; architecture unverified")
            raise RuntimeError("simulation failed; inspect evidence before ISA classification")
        if trace_requested and trace is None:
            raise RuntimeError("required physical trace was not generated")
        report = build_report(console, selection.family, selection.harts, selection.case, elf,
                              trace if focused_trace else None)
        write_json(folder / "report.json", report)
        record["architecture_status"] = report["architecture_status"]
        record["diagnostic_status"] = report["diagnostics"]["status"]
        record["status"] = "PASS" if record["diagnostic_status"] != "INCOMPLETE" else "DIAGNOSTIC_INCOMPLETE"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record["status"] = "FAIL"
        record["error"] = str(error)
    finally:
        write_json(path, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DIRTYGEN / "build/isa-consistency/campaign")
    parser.add_argument("--family", choices=tuple(FAMILIES))
    parser.add_argument("--case")
    parser.add_argument("--harts", type=int, choices=(2, 4))
    parser.add_argument("--stress", action="store_true")
    parser.add_argument("--verify-legacy", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--trace-all", action="store_true", help="archive extra diagnostic traces")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()
    output = args.output_root.resolve()
    if not output.is_relative_to(DIRTYGEN / "build"):
        parser.error("output-root must be inside benchmarks/dirtygen/build")
    output.mkdir(parents=True, exist_ok=True)
    before = protected_state()
    write_json(output / "protected-before.json", before)
    if args.verify_legacy:
        verify_legacy(output)
    chosen = [s for s in selections(args.stress) if
              (args.family is None or s.family == args.family) and
              (args.case is None or s.case == args.case) and
              (args.harts is None or s.harts == args.harts)]
    if not chosen:
        parser.error("empty selection")
    records = []
    for selection in chosen:
        record = run_selection(selection, output, args.build_only, args.trace_all)
        records.append(record)
        write_json(output / "summary.json", {"schema": "shdlt-isa-campaign-v1", "expected": len(chosen),
                                              "results": records})
        print(f"{selection.name}: {record['status']} {record.get('error', '')}", flush=True)
        if record["status"] not in ("PASS", "BUILD_PASS") and not args.keep_going:
            break
    after = protected_state()
    write_json(output / "protected-after.json", after)
    if after != before:
        raise RuntimeError("protected baseline changed")
    return int(len(records) != len(chosen) or any(r["status"] not in ("PASS", "BUILD_PASS") for r in records))


if __name__ == "__main__":
    raise SystemExit(main())
