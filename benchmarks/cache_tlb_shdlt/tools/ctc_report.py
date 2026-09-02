#!/usr/bin/env python3
"""Strict parser for the SHDLT cache/TLB/coherence ABI v1."""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ABI_VERSION = 1
RESULT_BYTES = 512
PASS, FAIL, XFAIL, XPASS = range(4)
CASE_NAMES = (
    "pte_cache_hit_miss", "remote_pte_reread", "ownership_transfer",
    "coherence_pressure", "cas_retry", "hfence_before_after", "hfence_gpa",
    "hfence_vmid", "hfence_global", "fence_hart_isolation",
)
EXPECTED_OUTCOME = (PASS, PASS, PASS, PASS, PASS, PASS, XFAIL, XFAIL, PASS, PASS)
EXPECTED_PHASE = (1, 3, 1, 1, 1, 3, 2, 2, 2, 3)
EXPECTED_ENTRIES = ((1, 1), (0, 0), (1, 1), (64, 64), (0, 1),
                    (2, 2), (0, 0), (0, 0), (0, 0), (0, 0))
PREFIX = "SHDLT_CTC_"
RVLS_FAILURE_MARKERS = ("INTEGER WRITE MISSMATCH", "FLOAT WRITE MISSMATCH",
                        "MEMORY WRITE MISSMATCH", "rvls failure context", "RVLS MISMATCH")

HART_FIELDS = (
    "abi_version", "case", "outcome", "status", "done", "hart", "cpus", "phase",
    "requested_gpa", "requested_vmid", "readback_vmid", "pte_before", "pte_modified",
    "pte_after", "old_mapping_bitmap", "new_mapping_bitmap", "a_bitmap", "d_bitmap",
    "expected_bitmap", "initial_index", "final_index", "entries", "log_bitmap",
    "duplicates", "missing", "extra", "data_errors", "pte_errors", "fence_errors",
    "faults", "observer_required_mask", "observer_available_mask", "observer_valid_mask",
)
OBSERVER_COUNTERS = (
    "tlb_hit", "tlb_miss", "tlb_refill", "log_write", "cas_attempt", "cas_mismatch",
    "cas_redo", "cas_success", "acquire", "probe", "release", "writeback", "grant",
    "grant_ack", "stall_a", "stall_b", "stall_c", "stall_d", "stall_e", "forced_probe",
)

def _value(value: str) -> Any:
    if value.startswith("0x"):
        return int(value, 16)
    if value.lstrip("-").isdigit():
        return int(value)
    return value

def _record(line: str):
    pos = line.find(PREFIX)
    if pos < 0:
        return None
    tokens = line[pos:].strip().split()
    kind = tokens[0][len(PREFIX):].lower()
    values: dict[str, Any] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise ValueError(f"malformed CTC token {token!r}")
        key, value = token.split("=", 1)
        if key in values:
            raise ValueError(f"duplicate CTC field {key!r}")
        values[key] = _value(value)
    return kind, values

def _num(record: dict[str, Any], field: str, kind: str) -> int:
    value = record.get(field)
    if not isinstance(value, int):
        raise ValueError(f"{kind} missing numeric field {field!r}")
    return value

@dataclass
class CtcReport:
    text: str = ""
    begin: dict[str, Any] | None = None
    harts: list[dict[str, Any]] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)
    observers: list[dict[str, Any]] = field(default_factory=list)
    global_record: dict[str, Any] | None = None
    end: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)

    def validate(self, require_observer: bool = False) -> None:
        if any(marker.lower() in self.text.lower() for marker in RVLS_FAILURE_MARKERS):
            raise ValueError("RVLS mismatch text detected")
        if self.begin is None or self.global_record is None or self.end is None:
            raise ValueError("missing BEGIN, GLOBAL, or END record")
        if self.errors:
            raise ValueError("firmware emitted SHDLT_CTC_ERROR")
        case = _num(self.begin, "case", "BEGIN")
        cpus = _num(self.begin, "cpus", "BEGIN")
        if case not in range(len(CASE_NAMES)) or cpus not in (2, 4):
            raise ValueError("case/cpus out of range")
        if _num(self.begin, "abi_version", "BEGIN") != ABI_VERSION or \
           _num(self.begin, "result_bytes", "BEGIN") != RESULT_BYTES:
            raise ValueError("ABI version/size mismatch")
        if len(self.harts) != cpus:
            raise ValueError(f"expected {cpus} HART records, got {len(self.harts)}")
        by_hart: dict[int, dict[str, Any]] = {}
        total_entries = 0
        counts = [0, 0, 0, 0]
        for r in self.harts:
            for name in HART_FIELDS:
                _num(r, name, "HART")
            hart = r["hart"]
            if hart in by_hart or hart not in range(cpus):
                raise ValueError(f"duplicate/out-of-range hart {hart}")
            by_hart[hart] = r
            if r["abi_version"] != ABI_VERSION or r["case"] != case or r["cpus"] != cpus or r["done"] != 1:
                raise ValueError(f"hart {hart}: identity mismatch")
            if r["phase"] != EXPECTED_PHASE[case]:
                raise ValueError(f"hart {hart}: phase mismatch")
            if r["outcome"] != EXPECTED_OUTCOME[case]:
                label = "XPASS" if r["outcome"] == XPASS else "unexpected outcome"
                raise ValueError(f"hart {hart}: {label} {r['outcome']}")
            if r["status"] != 0:
                raise ValueError(f"hart {hart}: failed status")
            low, high = EXPECTED_ENTRIES[case]
            if not low <= r["entries"] <= high or r["initial_index"] != 0 or r["final_index"] != r["entries"]:
                raise ValueError(f"hart {hart}: dirty-log index/count mismatch")
            for name in ("duplicates", "missing", "extra", "data_errors", "pte_errors", "faults"):
                if r[name]:
                    raise ValueError(f"hart {hart}: {name}={r[name]}")
            if EXPECTED_OUTCOME[case] == XFAIL:
                if r["fence_errors"] != 1:
                    raise ValueError(f"hart {hart}: XFAIL evidence is not exact")
                if case == 6 and r["new_mapping_bitmap"] != 3:
                    raise ValueError(f"hart {hart}: GPA XFAIL lacks global-flush evidence")
                if case == 7 and (r["readback_vmid"] != 0 or r["new_mapping_bitmap"] != 3):
                    raise ValueError(f"hart {hart}: VMID XFAIL lacks WARL/global-flush evidence")
            elif r["fence_errors"]:
                raise ValueError(f"hart {hart}: fence_errors={r['fence_errors']}")
            counts[r["outcome"]] += 1
            total_entries += r["entries"]
        if set(by_hart) != set(range(cpus)):
            raise ValueError("hart coverage mismatch")
        if case == 4 and total_entries < 1:
            raise ValueError("CAS retry campaign produced no committed dirty transition")

        # Every firmware phase must have exactly one begin/end marker. Observer
        # records are optional for the portable/no-whitebox backend.
        expected_phase_count = EXPECTED_PHASE[case]
        phase_actions: dict[tuple[int, str], int] = {}
        for p in self.phases:
            if _num(p, "case", "PHASE") != case:
                raise ValueError("PHASE case mismatch")
            phase = _num(p, "phase", "PHASE")
            action = p.get("action")
            if phase not in range(expected_phase_count) or action not in ("begin", "end"):
                raise ValueError("PHASE identity/action mismatch")
            key = (phase, action)
            phase_actions[key] = phase_actions.get(key, 0) + 1
            for name in ("hart_mask", "gpa_base", "gpa_mask", "pte_base", "pte_mask", "probe_pa", "probe_requested"):
                _num(p, name, "PHASE")
        for phase in range(expected_phase_count):
            for action in ("begin", "end"):
                if phase_actions.get((phase, action)) != 1:
                    raise ValueError(f"missing/duplicate phase {phase} {action}")

        observer_keys: set[tuple[int, int]] = set()
        for o in self.observers:
            o_case, phase, hart = (_num(o, n, "OBSERVER") for n in ("case", "phase", "hart"))
            if o_case != case or phase not in range(expected_phase_count) or hart not in range(cpus):
                raise ValueError("OBSERVER identity mismatch")
            key = (phase, hart)
            if key in observer_keys:
                raise ValueError(f"duplicate OBSERVER phase/hart {key}")
            observer_keys.add(key)
            available = _num(o, "available_mask", "OBSERVER")
            valid = _num(o, "valid_mask", "OBSERVER")
            if valid & ~available:
                raise ValueError("OBSERVER valid mask exceeds available mask")
            for name in OBSERVER_COUNTERS:
                _num(o, name, "OBSERVER")
        if require_observer:
            if observer_keys != {(p, h) for p in range(expected_phase_count) for h in range(cpus)}:
                raise ValueError("observer phase/hart coverage mismatch")
            required = self.harts[0]["observer_required_mask"]
            for o in self.observers:
                if o["valid_mask"] & required != required:
                    raise ValueError("required observer signals unavailable/invalid")
            if case == 0:
                for h in range(cpus):
                    total = [o for o in self.observers if o["hart"] == h][0]
                    if total["tlb_miss"] < 1 or total["tlb_hit"] < 1 or total["cas_success"] != 1:
                        raise ValueError("PTE hit/miss observer lower bound failed")
            if case == 2:
                if sum(o["probe"] for o in self.observers) < cpus - 1 or \
                   sum(o["release"] for o in self.observers) < cpus - 1 or \
                   sum(o["acquire"] for o in self.observers) < cpus:
                    raise ValueError("ownership transfer observer lower bound failed")
            if case == 3:
                if not any(o["forced_probe"] for o in self.observers):
                    raise ValueError("forced probe was requested but not observed")
                for name in ("probe", "writeback", "grant", "grant_ack"):
                    if not sum(o[name] for o in self.observers):
                        raise ValueError(f"coherence observer {name} lower bound failed")
                if not sum(sum(o[name] for name in ("stall_a", "stall_b", "stall_c", "stall_d", "stall_e"))
                           for o in self.observers):
                    raise ValueError("coherence observer saw no channel backpressure")
            if case == 1:
                if any(o["tlb_refill"] for o in self.observers if o["phase"] == 1):
                    raise ValueError("remote-PTE idle phase unexpectedly refilled")
            if case == 5:
                if any(o["tlb_refill"] or o["cas_attempt"] or o["log_write"]
                       for o in self.observers if o["phase"] == 1):
                    raise ValueError("pre-HFENCE idle phase changed translation/log state")
            if case == 9:
                for o in self.observers:
                    if o["phase"] == 1 and (o["hart"] & 1) and o["tlb_refill"]:
                        raise ValueError("one hart's fence affected its unfenced peer")

        g = self.global_record
        expected_global = {"case": case, "cpus": cpus, "completed": cpus,
                           "pass": counts[PASS], "fail": counts[FAIL],
                           "xfail": counts[XFAIL], "xpass": counts[XPASS],
                           "total_entries": total_entries, "status": 0}
        for name, value in expected_global.items():
            if _num(g, name, "GLOBAL") != value:
                raise ValueError(f"GLOBAL {name} mismatch")
        for name, value in {"completed": cpus, "fail": 0, "xfail": counts[XFAIL], "xpass": 0, "status": 0}.items():
            if _num(self.end, name, "END") != value:
                raise ValueError(f"END {name} mismatch")

def parse_text(text: str, validate: bool = True, require_observer: bool = False) -> CtcReport:
    report = CtcReport(text=text)
    singles = {"begin": "begin", "global": "global_record", "end": "end"}
    for line in text.splitlines():
        item = _record(line)
        if item is None:
            continue
        kind, values = item
        if kind in singles:
            attr = singles[kind]
            if getattr(report, attr) is not None:
                raise ValueError(f"duplicate {kind.upper()} record")
            setattr(report, attr, values)
        elif kind == "hart": report.harts.append(values)
        elif kind == "phase": report.phases.append(values)
        elif kind == "observer": report.observers.append(values)
        elif kind == "error": report.errors.append(values)
        else: raise ValueError(f"unknown CTC record {kind!r}")
    if validate:
        report.validate(require_observer=require_observer)
    return report

def validate_campaign(paths: list[Path], require_observer: bool = False) -> list[CtcReport]:
    reports = [parse_text(p.read_text(errors="replace"), require_observer=require_observer) for p in paths]
    # CAS/coherence counters are an optional simulation diagnostic.  A
    # portable architecture-only campaign has no observer records and must
    # still be able to validate the complete case set.  Apply this lower bound
    # only when the caller explicitly requested the legacy observer ABI.
    if require_observer:
        for cpus in (2, 4):
            subset = [r for r in reports if r.begin["case"] == 4 and r.begin["cpus"] == cpus]
            if subset and not any(sum(o["cas_mismatch"] for o in r.observers) for r in subset):
                raise ValueError(f"{cpus}-hart CAS campaign observed no mismatch/retry")
    return reports

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--require-observer", action="store_true")
    ap.add_argument("--campaign", action="store_true")
    ap.add_argument("--format", choices=("table", "json"), default="table")
    args = ap.parse_args(argv)
    try:
        reports = validate_campaign(args.logs, args.require_observer) if args.campaign else \
                  [parse_text(p.read_text(errors="replace"), require_observer=args.require_observer) for p in args.logs]
    except (OSError, ValueError) as error:
        print(f"SHDLT CTC report error: {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps([{"begin": r.begin, "harts": r.harts, "phases": r.phases,
                           "observers": r.observers, "global": r.global_record, "end": r.end}
                          for r in reports], indent=2))
    else:
        for r in reports:
            case = r.begin["case"]
            label = "XFAIL" if EXPECTED_OUTCOME[case] == XFAIL else "PASS"
            print(f"case={CASE_NAMES[case]} cpus={r.begin['cpus']} outcome={label} "
                  f"entries={r.global_record['total_entries']} observers={len(r.observers)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
