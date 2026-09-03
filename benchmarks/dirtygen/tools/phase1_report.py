#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


PREFIX = "SHDLT_PHASE1"
PTE_V = 0x01
PTE_R = 0x02
PTE_W = 0x04
PTE_U = 0x10
PTE_A = 0x40
PTE_LOW_MASK = 0x3FF

CASE_SPECS = {
    "boundary_full_a0d0": {
        "id": 0,
        "cause": 24,
        "flags": PTE_V | PTE_R | PTE_W | PTE_U,
        "index": 512,
    },
    "log_target_store_fault": {
        "id": 1,
        "cause": 7,
        "flags": PTE_V | PTE_R | PTE_W | PTE_U | PTE_A,
        "index": 0,
    },
    "invalid_gstage_pte_full": {
        "id": 2,
        "cause": 23,
        "flags": 0,
        "index": 512,
    },
    "write_permission_denied_full": {
        "id": 3,
        "cause": 23,
        "flags": PTE_V | PTE_R | PTE_U | PTE_A,
        "index": 512,
    },
}


def _parse_value(value: str) -> Any:
    if value.startswith("0x"):
        return int(value, 16)
    return value


def _fields(tokens: list[str], kind: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            raise ValueError(f"malformed {kind} token: {token!r}")
        key, value = token.split("=", 1)
        if key in result:
            raise ValueError(f"duplicate {kind} field: {key!r}")
        result[key] = _parse_value(value)
    return result


def _required_int(record: dict[str, Any], key: str, kind: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{kind} is missing numeric field {key!r}")
    return value


@dataclass
class Phase1Report:
    begin: dict[str, Any] | None = None
    cases: list[dict[str, Any]] = field(default_factory=list)
    end: dict[str, Any] | None = None

    def validate(self) -> None:
        if self.begin is None:
            raise ValueError("missing SHDLT_PHASE1_BEGIN")
        if self.end is None:
            raise ValueError("missing SHDLT_PHASE1_END")
        if _required_int(self.begin, "cases", "SHDLT_PHASE1_BEGIN") != len(CASE_SPECS):
            raise ValueError("SHDLT_PHASE1_BEGIN has the wrong case count")
        if len(self.cases) != len(CASE_SPECS):
            raise ValueError(
                f"expected {len(CASE_SPECS)} Phase-1 cases, found {len(self.cases)}"
            )

        seen: set[str] = set()
        for record in self.cases:
            name = record.get("case")
            if not isinstance(name, str) or name not in CASE_SPECS:
                raise ValueError(f"unknown Phase-1 case {name!r}")
            if name in seen:
                raise ValueError(f"duplicate Phase-1 case {name!r}")
            seen.add(name)
            spec = CASE_SPECS[name]

            for key, expected in (
                ("id", spec["id"]),
                ("status", 0),
                ("expected_cause", spec["cause"]),
                ("actual_cause", spec["cause"]),
                ("idx_before", spec["index"]),
                ("idx_after", spec["index"]),
                ("buffer_errors", 0),
            ):
                actual = _required_int(record, key, name)
                if actual != expected:
                    raise ValueError(f"{name} {key}={actual}, expected {expected}")

            pte_before = _required_int(record, "pte_before", name)
            pte_after = _required_int(record, "pte_after", name)
            if pte_before != pte_after:
                raise ValueError(f"{name} changed its PTE")
            if pte_before & PTE_LOW_MASK != spec["flags"]:
                raise ValueError(f"{name} has incorrect initial PTE flags")
            if _required_int(record, "data_before", name) != _required_int(
                record, "data_after", name
            ):
                raise ValueError(f"{name} changed guest data")

        if seen != set(CASE_SPECS):
            raise ValueError("Phase-1 case set is incomplete")
        for key, expected in (
            ("cases", len(CASE_SPECS)),
            ("failures", 0),
            ("status", 0),
        ):
            actual = _required_int(self.end, key, "SHDLT_PHASE1_END")
            if actual != expected:
                raise ValueError(
                    f"SHDLT_PHASE1_END {key}={actual}, expected {expected}"
                )

    def as_dict(self) -> dict[str, Any]:
        return {"begin": self.begin, "cases": self.cases, "end": self.end}


def parse_lines(stream: TextIO) -> Phase1Report:
    report = Phase1Report()
    for line in stream:
        start = line.find(PREFIX)
        if start < 0:
            continue
        tokens = line[start:].strip().split()
        tag = tokens[0]
        if tag == f"{PREFIX}_BEGIN":
            if report.begin is not None:
                raise ValueError("duplicate SHDLT_PHASE1_BEGIN")
            report.begin = _fields(tokens[1:], tag)
        elif tag == f"{PREFIX}_END":
            if report.end is not None:
                raise ValueError("duplicate SHDLT_PHASE1_END")
            report.end = _fields(tokens[1:], tag)
        elif tag == PREFIX:
            report.cases.append(_fields(tokens[1:], tag))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SHDLT Phase-1 output")
    parser.add_argument("log", type=Path)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args()

    try:
        with args.log.open(encoding="utf-8", errors="replace") as stream:
            report = parse_lines(stream)
        report.validate()
    except (OSError, ValueError) as error:
        print(f"phase1 report error: {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        json.dump(report.as_dict(), sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        for record in report.cases:
            print(
                f"{record['case']}: PASS cause={record['actual_cause']} "
                f"pte=0x{record['pte_after']:x} idx={record['idx_after']}"
            )
        print("Phase 1: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
