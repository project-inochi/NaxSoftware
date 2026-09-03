#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


PREFIX = "SHDLT_PHASE6"
CASE_NAME = "implicit_vs_pte_store"
PTE_V = 0x01
PTE_R = 0x02
PTE_W = 0x04
PTE_U = 0x10
PTE_A = 0x40
PTE_D = 0x80
PTE_LOW_MASK = 0x3FF
VS_PTE_FLAGS_BEFORE = PTE_V | PTE_R | PTE_W | PTE_D
GSTAGE_PT_FLAGS_BEFORE = PTE_V | PTE_R | PTE_W | PTE_U | PTE_A
GSTAGE_DATA_FLAGS = GSTAGE_PT_FLAGS_BEFORE | PTE_D
EXPECTED_CAUSE = 10
EXPECTED_LOG_ENTRY = 0x202000
EXPECTED_DATA_BEFORE = 0xA60D1C0000000000
EXPECTED_DATA_AFTER = 0x1122334455667788


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


def _validate_pte_transition(
    record: dict[str, Any],
    before_key: str,
    after_key: str,
    before_flags: int,
    added_flag: int,
) -> None:
    before = _required_int(record, before_key, CASE_NAME)
    after = _required_int(record, after_key, CASE_NAME)
    if before & PTE_LOW_MASK != before_flags:
        raise ValueError(f"{CASE_NAME} has incorrect initial {before_key}")
    if after != before | added_flag:
        raise ValueError(f"{CASE_NAME} has incorrect {before_key[:-7]} transition")


@dataclass
class Phase6Report:
    begin: dict[str, Any] | None = None
    cases: list[dict[str, Any]] = field(default_factory=list)
    end: dict[str, Any] | None = None

    def validate(self) -> None:
        if self.begin is None:
            raise ValueError("missing SHDLT_PHASE6_BEGIN")
        if self.end is None:
            raise ValueError("missing SHDLT_PHASE6_END")
        if _required_int(self.begin, "cases", "SHDLT_PHASE6_BEGIN") != 1:
            raise ValueError("SHDLT_PHASE6_BEGIN has the wrong case count")
        if len(self.cases) != 1:
            raise ValueError(f"expected 1 Phase-6 case, found {len(self.cases)}")

        record = self.cases[0]
        if record.get("case") != CASE_NAME:
            raise ValueError(f"unknown Phase-6 case {record.get('case')!r}")
        for key, expected in (
            ("id", 0),
            ("status", 0),
            ("expected_cause", EXPECTED_CAUSE),
            ("actual_cause", EXPECTED_CAUSE),
            ("idx_before", 0),
            ("idx_after", 1),
            ("expected_log_entry", EXPECTED_LOG_ENTRY),
            ("actual_log_entry", EXPECTED_LOG_ENTRY),
            ("buffer_errors", 0),
        ):
            actual = _required_int(record, key, CASE_NAME)
            if actual != expected:
                raise ValueError(f"{CASE_NAME} {key}={actual}, expected {expected}")

        _validate_pte_transition(
            record,
            "vs_pte_before",
            "vs_pte_after",
            VS_PTE_FLAGS_BEFORE,
            PTE_A,
        )
        _validate_pte_transition(
            record,
            "gstage_pt_pte_before",
            "gstage_pt_pte_after",
            GSTAGE_PT_FLAGS_BEFORE,
            PTE_D,
        )

        data_before = _required_int(record, "gstage_data_pte_before", CASE_NAME)
        data_after = _required_int(record, "gstage_data_pte_after", CASE_NAME)
        if data_before & PTE_LOW_MASK != GSTAGE_DATA_FLAGS:
            raise ValueError(f"{CASE_NAME} has incorrect initial gstage_data_pte")
        if data_after != data_before:
            raise ValueError(f"{CASE_NAME} changed gstage_data_pte")
        for key, expected in (
            ("data_before", EXPECTED_DATA_BEFORE),
            ("data_after", EXPECTED_DATA_AFTER),
        ):
            actual = _required_int(record, key, CASE_NAME)
            if actual != expected:
                raise ValueError(f"{CASE_NAME} {key}={actual}, expected {expected}")

        for key, expected in (("cases", 1), ("failures", 0), ("status", 0)):
            actual = _required_int(self.end, key, "SHDLT_PHASE6_END")
            if actual != expected:
                raise ValueError(
                    f"SHDLT_PHASE6_END {key}={actual}, expected {expected}"
                )

    def as_dict(self) -> dict[str, Any]:
        return {"begin": self.begin, "cases": self.cases, "end": self.end}


def parse_lines(stream: TextIO) -> Phase6Report:
    report = Phase6Report()
    for line in stream:
        start = line.find(PREFIX)
        if start < 0:
            continue
        tokens = line[start:].strip().split()
        tag = tokens[0]
        if tag == f"{PREFIX}_BEGIN":
            if report.begin is not None:
                raise ValueError("duplicate SHDLT_PHASE6_BEGIN")
            report.begin = _fields(tokens[1:], tag)
        elif tag == f"{PREFIX}_END":
            if report.end is not None:
                raise ValueError("duplicate SHDLT_PHASE6_END")
            report.end = _fields(tokens[1:], tag)
        elif tag == PREFIX:
            report.cases.append(_fields(tokens[1:], tag))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SHDLT Phase-6 output")
    parser.add_argument("log", type=Path)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args()

    try:
        with args.log.open(encoding="utf-8", errors="replace") as stream:
            report = parse_lines(stream)
        report.validate()
    except (OSError, ValueError) as error:
        print(f"phase6 report error: {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        json.dump(report.as_dict(), sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        record = report.cases[0]
        print(
            f"{record['case']}: PASS cause={record['actual_cause']} "
            f"log=0x{record['actual_log_entry']:x} idx={record['idx_after']}"
        )
        print("Phase 6: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
