#!/usr/bin/env python3
"""ISA-profile firmware checks; physical logger events are separate diagnostics."""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

from shdlt_isa_audit import NAX

sys.path.insert(0, str(NAX / "benchmarks/cache_tlb_shdlt/tools"))
sys.path.insert(0, str(NAX / "baremetal/multicore_race_shdlt/tools"))
sys.path.insert(0, str(NAX / "baremetal/rtl_directed_shdlt/tools"))
import ctc_report
import race_report
from rtl_report import SMOKE_CASES, fields, parse_trace, empty_trace
from invariant_report import check_invariants

PROFILE_LINE = "SHDLT_TEST_PROFILE profile=isa version=1"
PHYSICAL = re.compile(r"^rv mmu physical-store (\d+) (\d+) (\d+) (\d+) ([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) (\d+) (pending|committed|superseded|error)$")
MMU_STORE = re.compile(r"^rv mmu store (\d+) ([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) (\d+)$")


def require_profile(text: str) -> None:
    if text.splitlines().count(PROFILE_LINE) != 1:
        raise ValueError("missing/duplicate ISA profile marker; legacy ELF is not accepted")


def inspect_elf(elf: Path, family: str) -> dict:
    symbols = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    if not re.search(r"^0*1 A shdlt_isa_profile_v1$", symbols, re.M):
        raise ValueError("ELF lacks ISA profile symbol; refusing a legacy binary")
    asm = subprocess.check_output(["riscv64-elf-objdump", "-d", str(elf)], text=True)
    if "0000100f" not in asm:
        raise ValueError("ELF lacks FENCE.I")
    result = {"profile": "isa", "fence_i": True}
    if family in ("ctc", "smoke"):
        def body(name: str) -> str:
            match = re.search(r"^\w+ <" + name + r"[^>]*>:\n(.*?)(?=\n\n|\Z)", asm, re.M | re.S)
            if not match:
                raise ValueError(f"ELF missing synchronization primitive {name}")
            return match[1]
        wait = body("shdlt_isa_wait_ready")
        instructions = [(int(m[1], 16), m[2], m[3]) for m in re.finditer(
            r"^\s*([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)$", wait, re.M)]
        loads = [pc for pc, op, _ in instructions if op == "ld"]
        reload_branches = []
        for pc, op, operands in instructions:
            target = re.search(r",([0-9a-f]+)\s+<", operands)
            if op.startswith("b") and target:
                address = int(target[1], 16)
                if any(address <= load < pc for load in loads):
                    reload_branches.append(pc)
        acquire_after_success = any(op == "fence" and operands.strip() == "r,rw" and
                                    reload_branches and pc > max(reload_branches)
                                    for pc, op, operands in instructions)
        if not reload_branches or not acquire_after_success:
            raise ValueError("ready poll must reload on its back edge and acquire after success")
        publish = body("shdlt_isa_publish")
        if not re.search(r"fence\s+rw,w.*\bsd\b", publish, re.S):
            raise ValueError("ready publication must release before the store")
        result.update(poll_reloads=True, acquire_after_poll=True, release_before_publish=True)
    return result


def validate_smoke(text: str, harts: int, case: str) -> dict:
    rows = []
    for line in text.splitlines():
        if not line.startswith("SHDLT_MC_SAMPLE "):
            continue
        keys = []
        for token in line.split()[1:]:
            if token.count("=") != 1:
                raise ValueError("malformed smoke field")
            key = token.split("=", 1)[0]
            if key in keys:
                raise ValueError("duplicate smoke field")
            keys.append(key)
        rows.append(fields(line))
    if text.splitlines().count("SHDLT_MC_BEGIN") != 1:
        raise ValueError("missing/duplicate smoke BEGIN")
    if len(rows) != harts or {r.get("hart") for r in rows} != set(range(harts)):
        raise ValueError("missing/duplicate/foreign smoke hart record")
    case_id = SMOKE_CASES[case]
    d_bits = (0, 0, 1, 1, 15, 3, 3, 1)[case_id]
    log_bits = (0, 0, 0, 0, 15, 3, 1, 1)[case_id]
    entries = log_bits.bit_count()
    initial = 5 if case_id == 5 else 0
    for row in rows:
        expected = {"case": case_id, "status": 0x600d, "a": 0xffff,
                    "d": d_bits, "expected": log_bits, "actual": log_bits,
                    "initial": initial, "final": initial + entries,
                    "entries": entries, "unique": entries, "dup": 0,
                    "missing": 0, "extra": 0, "data_errors": 0, "faults": 0}
        if set(row) != set(expected) | {"hart"} or any(row[k] != v for k, v in expected.items()):
            raise ValueError(f"smoke hart {row.get('hart')}: payload/status mismatch")
    if text.splitlines().count("SHDLT_MC_END") != 1:
        raise ValueError("missing/duplicate smoke completion")
    return {"profile": "isa", "harts": rows}


def validate_architecture(text: str, family: str, harts: int, case: str) -> dict:
    require_profile(text)
    if harts not in (2, 4):
        raise ValueError("ISA profile requires 2 or 4 harts")
    if family == "smoke":
        arch = validate_smoke(text, harts, case)
    elif family == "ctc":
        report = ctc_report.parse_text(text, profile="isa")
        if report.begin["cpus"] != harts or ctc_report.CASE_NAMES[report.begin["case"]] != case:
            raise ValueError("CTC selection mismatch")
        arch = dataclasses.asdict(report)
        arch.pop("text")
    elif family == "race":
        report = race_report.parse_text(text, profile="isa")
        if report.begin["cpus"] != harts or race_report.CASE_NAMES[report.begin["case"]] != case:
            raise ValueError("race selection mismatch")
        arch = dataclasses.asdict(report)
    else:
        raise ValueError("unknown family")
    invariants = check_invariants(family, case, harts, empty_trace(harts), arch)
    if invariants["status"] != "PASS":
        raise ValueError(f"architecture invariants: {invariants['violations']}")
    return {"architecture_status": "PASS", "architecture": arch, "invariants": invariants}


def check_lifecycle(lines, family: str, harts: int) -> dict:
    """Focused single-PTE diagnostic. Does not demand H CAS participants."""
    events, stores = {}, []
    base = {"ctc": 0x83010000, "race": 0x82010000}[family]
    gpa = {"ctc": 0x40000, "race": 0x30000}[family]
    for line in lines:
        if match := PHYSICAL.fullmatch(line.strip()):
            hart, source, attempt = map(int, match.group(1, 2, 3))
            payload = (hart, int(match[5], 16), int(match[6]), int(match[7], 16), int(match[8]))
            if not 0 <= hart < harts or payload[1:] != (base + hart * 0x800000, 8, gpa, 0):
                raise ValueError("malformed/foreign physical logger event")
            item = events.setdefault((hart, source, attempt), {"payload": payload, "states": []})
            if item["payload"] != payload:
                raise ValueError("physical attempt changed payload")
            item["states"].append(match[9])
        elif match := MMU_STORE.fullmatch(line.strip()):
            stores.append((int(match[1]), int(match[2], 16), int(match[3]), int(match[4], 16), int(match[5])))
        elif line.startswith(("rv mmu physical-store", "rv mmu store")):
            raise ValueError("malformed MMU diagnostic record")
    committed = superseded = 0
    counts = [0] * harts
    for item in events.values():
        counts[item["payload"][0]] += 1
        if item["states"] == ["pending", "committed"]:
            committed += 1
            if stores.count(item["payload"]) != 1:
                raise ValueError("committed logger event missing/duplicated in architectural stream")
        elif item["states"] == ["pending", "superseded"]:
            superseded += 1
            if item["payload"] in stores:
                raise ValueError("superseded event entered architectural stream")
        else:
            raise ValueError("open/duplicate/error logger lifecycle")
    if committed != 1 or superseded != len(events) - 1 or not 1 <= len(events) <= harts or any(n > 1 for n in counts):
        raise ValueError("single-PTE physical diagnostic count mismatch")
    logger_stores = [s for s in stores if any(base + h * 0x800000 <= s[1] < base + h * 0x800000 + 4096 for h in range(harts))]
    if len(logger_stores) != 1 or len(stores) != 2:
        raise ValueError("single-PTE architectural store stream mismatch")
    pte_address = {"ctc": 0x81008200, "race": 0x81005180}[family]
    expected_pte = (logger_stores[0][0], pte_address, 8, 0x204800d7, 0)
    if stores.count(expected_pte) != 1:
        raise ValueError("shared PTE final update/owner mismatch")
    return {"status": "PASS", "profile": "vexii-shdlt-physical-v1",
            "physical_attempts": len(events), "committed": committed,
            "superseded": superseded, "attempts_by_hart": counts}


def build_report(console: Path, family: str, harts: int, case: str,
                 elf: Path, trace: Path | None = None) -> dict:
    text = console.read_text(errors="replace")
    if "[Done] Simulation done" not in text or "SUCCESS] mill" not in text:
        raise ValueError("TestBench all-hart success is missing")
    document = {"schema": "shdlt-isa-report-v1", "profile": "isa", "rvls_check": False,
                "family": family, "harts": harts, "case": case, "elf_checks": inspect_elf(elf, family),
                **validate_architecture(text, family, harts, case)}
    document["diagnostics"] = {"status": "NOT_REQUESTED", "available": False}
    if family == "ctc" and case in ("hfence_gpa", "hfence_vmid"):
        document["translation_observations"] = {
            "classification": "diagnostic only; new non-target data does not prove over-fencing",
            "same_vmid_pages": True,
            "harts": [{"hart": row["hart"], "requested_vmid": row["requested_vmid"],
                       "readback_vmid": row["readback_vmid"],
                       "old_mapping_bitmap": row["old_mapping_bitmap"],
                       "new_mapping_bitmap": row["new_mapping_bitmap"]}
                      for row in document["architecture"]["harts"]]}
    if trace is not None:
        try:
            summary = parse_trace(trace, family, harts)
            if summary.attribution_errors or summary.dirty_log_faults:
                raise ValueError("trace attribution/fault errors")
            with trace.open() as stream:
                diagnostic = check_lifecycle(stream, family, harts)
            document["diagnostics"] = {**diagnostic, "available": True,
                                        "architecture_stream": dataclasses.asdict(summary)}
        except ValueError as error:
            document["diagnostics"] = {"status": "INCOMPLETE", "available": True, "error": str(error)}
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console", type=Path)
    parser.add_argument("--family", choices=("smoke", "race", "ctc"), required=True)
    parser.add_argument("--harts", type=int, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    result = build_report(args.console, args.family, args.harts, args.case, args.elf, args.trace)
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(result["diagnostics"]["status"] == "INCOMPLETE")


if __name__ == "__main__":
    raise SystemExit(main())
