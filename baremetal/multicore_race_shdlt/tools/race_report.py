#!/usr/bin/env python3
"""Parse and strictly validate the SHDLT multicore race ABI v1 stream."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ABI_VERSION = 1
RESULT_BYTES = 512
STATUS_READY = 0x600D
STATUS_FAIL = 0x0BAD
PREFIX = "SHDLT_RACE_"
CASE_NAMES = (
    "different_pages", "order_permute", "skewed_completion", "result_isolation",
    "buffer_isolation", "same_page", "same_pte", "same_cacheline_ptes",
)

HART_FIELDS = (
    "case", "hart", "status", "done", "phase", "target0", "target1", "a", "d",
    "expected_d", "initial", "final", "entries", "entry_min", "entry_max",
    "log_bitmap", "duplicates", "missing", "extra", "foreign", "launch0", "finish0",
    "launch1", "finish1", "buffer_errors", "result_errors", "tail_writes",
    "data_errors", "pte_errors", "faults", "unexpected", "isolation_errors",
)


def _value(value: str) -> Any:
    return int(value, 16) if value.startswith("0x") else value


def _record(line: str):
    pos = line.find(PREFIX)
    if pos < 0:
        return None
    tokens = line[pos:].strip().split()
    kind = tokens[0][len(PREFIX):].lower()
    values: dict[str, Any] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise ValueError(f"malformed SHDLT_RACE token {token!r}")
        name, value = token.split("=", 1)
        if name in values:
            raise ValueError(f"duplicate SHDLT_RACE field {name!r}")
        values[name] = _value(value)
    return kind, values


def _num(record: dict[str, Any], name: str, kind: str) -> int:
    value = record.get(name)
    if not isinstance(value, int):
        raise ValueError(f"{kind} missing numeric field {name!r}")
    return value


def target_gpa(case: int, hart: int, phase: int) -> int:
    if case == 1:
        return (0xC0000 if phase else 0x80000) + hart * 0x8000
    if case in (5, 6):
        return 0x30000
    if case == 7:
        return 0x30000 + hart * 0x1000
    return 0x30000 + hart * 0x8000


@dataclass
class RaceReport:
    begin: dict[str, Any] | None = None
    global_record: dict[str, Any] | None = None
    end: dict[str, Any] | None = None
    harts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def validate(self, require_pass: bool = True) -> None:
        if self.begin is None:
            raise ValueError("missing SHDLT_RACE_BEGIN")
        if self.global_record is None:
            raise ValueError("missing SHDLT_RACE_GLOBAL")
        if self.end is None:
            raise ValueError("missing SHDLT_RACE_END")
        if self.errors:
            raise ValueError(f"firmware emitted {len(self.errors)} SHDLT_RACE_ERROR record(s)")

        case = _num(self.begin, "case", "BEGIN")
        cpus = _num(self.begin, "cpus", "BEGIN")
        if _num(self.begin, "version", "BEGIN") != ABI_VERSION:
            raise ValueError("ABI version mismatch")
        if _num(self.begin, "result_bytes", "BEGIN") != RESULT_BYTES:
            raise ValueError("result ABI size mismatch")
        if case < 0 or case >= len(CASE_NAMES):
            raise ValueError("case is out of range")
        if cpus not in (2, 4):
            raise ValueError("cpus must be 2 or 4")
        if len(self.harts) != cpus:
            raise ValueError(f"expected {cpus} HART records, got {len(self.harts)}")

        by_hart: dict[int, dict[str, Any]] = {}
        phases = 2 if case == 1 else 1
        expected_mask = (1 << phases) - 1
        failed_harts = 0
        total_entries = 0
        recorded = 0
        sums = {name: 0 for name in ("data_errors", "pte_errors", "buffer_errors", "isolation_errors")}
        for record in self.harts:
            for name in HART_FIELDS:
                _num(record, name, "HART")
            hart = record["hart"]
            if hart in by_hart:
                raise ValueError(f"duplicate HART record {hart}")
            if hart < 0 or hart >= cpus:
                raise ValueError(f"hart {hart} is out of range")
            by_hart[hart] = record
            if record["case"] != case or record["done"] != 1:
                raise ValueError(f"hart {hart}: identity/done mismatch")
            if record["phase"] != (1 if case == 1 else 0):
                raise ValueError(f"hart {hart}: phase mismatch")
            if record["target0"] != target_gpa(case, hart, 0):
                raise ValueError(f"hart {hart}: target0 mismatch")
            expected_target1 = target_gpa(case, hart, 1) if phases == 2 else 0
            if record["target1"] != expected_target1:
                raise ValueError(f"hart {hart}: target1 mismatch")
            if record["a"] != expected_mask or record["d"] != expected_mask or record["expected_d"] != expected_mask:
                raise ValueError(f"hart {hart}: A/D bitmap mismatch")
            if record["initial"] != 0 or record["final"] != record["entries"]:
                raise ValueError(f"hart {hart}: index mismatch")
            if case == 6:
                if record["entry_min"] != 0 or record["entry_max"] != 1 or record["entries"] not in (0, 1):
                    raise ValueError(f"hart {hart}: shared-PTE entry bounds mismatch")
                if record["log_bitmap"] != (1 if record["entries"] else 0):
                    raise ValueError(f"hart {hart}: shared-PTE log bitmap mismatch")
            else:
                if record["entry_min"] != phases or record["entry_max"] != phases or record["entries"] != phases:
                    raise ValueError(f"hart {hart}: entry count mismatch")
                if record["log_bitmap"] != expected_mask:
                    raise ValueError(f"hart {hart}: log bitmap mismatch")
            for name in ("duplicates", "missing", "extra", "foreign", "buffer_errors", "result_errors",
                         "data_errors", "pte_errors", "faults", "unexpected", "isolation_errors"):
                if record[name] != 0:
                    raise ValueError(f"hart {hart}: {name} is nonzero")
            if case != 6 and record["tail_writes"] != 0:
                raise ValueError(f"hart {hart}: unexpected tail write")
            if record["status"] not in (STATUS_READY, STATUS_FAIL):
                raise ValueError(f"hart {hart}: unknown status")
            failed_harts += record["status"] != STATUS_READY
            total_entries += record["entries"]
            if record["entries"]:
                recorded |= 1 << hart
            sums["data_errors"] += record["data_errors"]
            sums["pte_errors"] += record["pte_errors"]
            sums["buffer_errors"] += record["buffer_errors"] + record["result_errors"]
            sums["isolation_errors"] += record["isolation_errors"] + record["foreign"]

        if set(by_hart) != set(range(cpus)):
            raise ValueError("HART coverage mismatch")
        launch0 = sorted(record["launch0"] for record in self.harts)
        finish0 = sorted(record["finish0"] for record in self.harts)
        if launch0 != list(range(cpus)) or finish0 != list(range(cpus)):
            raise ValueError("phase-0 launch/finish ranks are not permutations")
        if case == 1:
            if sorted(record["launch1"] for record in self.harts) != list(range(cpus)) or \
               sorted(record["finish1"] for record in self.harts) != list(range(cpus)):
                raise ValueError("phase-1 launch/finish ranks are not permutations")
            for hart, record in by_hart.items():
                if (record["launch0"], record["finish0"], record["launch1"], record["finish1"]) != \
                   (hart, cpus - 1 - hart, cpus - 1 - hart, hart):
                    raise ValueError(f"hart {hart}: ordered ranks mismatch")
        else:
            for record in self.harts:
                if record["launch1"] != 0 or record["finish1"] != 0:
                    raise ValueError("unexpected phase-1 rank")
        if case == 2 and (by_hart[0]["finish0"] != 0 or by_hart[cpus - 1]["finish0"] != cpus - 1):
            raise ValueError("skewed completion endpoints mismatch")
        if case == 6 and not (1 <= total_entries <= cpus and recorded != 0):
            raise ValueError("shared-PTE logs must total 1..CPU_COUNT")

        global_record = self.global_record
        expected_global = {
            "case": case, "cpus": cpus, "completed": cpus,
            "total_entries": total_entries, "recorded_harts": recorded,
            **sums,
        }
        for name, value in expected_global.items():
            if _num(global_record, name, "GLOBAL") != value:
                raise ValueError(f"GLOBAL {name} mismatch")
        failures = _num(global_record, "failures", "GLOBAL")
        status = _num(global_record, "status", "GLOBAL")
        if failures < failed_harts or status != (1 if failures else 0):
            raise ValueError("GLOBAL failure/status mismatch")
        for name, value in {"completed": cpus, "failures": failures, "status": status}.items():
            if _num(self.end, name, "END") != value:
                raise ValueError(f"END {name} mismatch")
        if require_pass and (failed_harts or failures or status):
            raise ValueError(f"race report failed: failed_harts={failed_harts} failures={failures}")


def parse_text(text: str, validate: bool = True, require_pass: bool = True) -> RaceReport:
    report = RaceReport()
    for line in text.splitlines():
        item = _record(line)
        if item is None:
            continue
        kind, values = item
        if kind == "begin":
            if report.begin is not None:
                raise ValueError("duplicate SHDLT_RACE_BEGIN")
            report.begin = values
        elif kind == "hart":
            report.harts.append(values)
        elif kind == "global":
            if report.global_record is not None:
                raise ValueError("duplicate SHDLT_RACE_GLOBAL")
            report.global_record = values
        elif kind == "end":
            if report.end is not None:
                raise ValueError("duplicate SHDLT_RACE_END")
            report.end = values
        elif kind == "error":
            report.errors.append(values)
        else:
            raise ValueError(f"unknown SHDLT_RACE record {kind!r}")
    if validate:
        report.validate(require_pass=require_pass)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument("--allow-failed", action="store_true", help="validate structure while retaining failed hart records")
    args = parser.parse_args(argv)
    try:
        report = parse_text(args.log.read_text(errors="replace"), require_pass=not args.allow_failed)
    except (OSError, ValueError) as error:
        print(f"SHDLT race report error: {error}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"begin": report.begin, "harts": report.harts,
                          "global": report.global_record, "end": report.end}, indent=2))
    else:
        case = report.begin["case"]
        print(f"case={case} ({CASE_NAMES[case]}) cpus={report.begin['cpus']}")
        print("hart  entries  launch0  finish0  status")
        for record in sorted(report.harts, key=lambda item: item["hart"]):
            status = "PASS" if record["status"] == STATUS_READY else "FAIL"
            print(f"{record['hart']:>4}  {record['entries']:>7}  {record['launch0']:>7}  {record['finish0']:>7}  {status}")
        print(f"total_entries={report.global_record['total_entries']} "
              f"recorded_harts=0x{report.global_record['recorded_harts']:x} "
              f"failures={report.global_record['failures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
