#!/usr/bin/env python3
"""Validate the Phase-4 buffer-mc ABI and its physical trace evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


PREFIX = "SHDLT_BUFFER_MC"
ABI_VERSION = 1
HART_COUNT = 2
CASE = 8
SIZE = 0
CAPACITY = 512
RUNS = 6
TRACKED_GPA = 0x10000
TRACKED_PHYSICAL = 0x81200000
PTE_ADDRESS = 0x81005080
PTE_CLEAN = ((TRACKED_PHYSICAL >> 12) << 10) | 0x57
PTE_DIRTY = ((TRACKED_PHYSICAL >> 12) << 10) | 0xD7
LOG_BASE = 0x83000000
LOG_STRIDE = 0x00400000
LOG_SENTINEL = 0x51D1700000000000
VALUE_PREFIX = 0xB400000000000000

BEGIN_FIELDS = ("abi", "hart_count", "case", "size", "capacity", "samples")
SAMPLE_FIELDS = (
    "sample", "warmup", "repetition", "status", "pte_before", "pte_after",
    "data_errors", "buffer_errors", "d_transitions", "committed_logs",
    "cas_attempts", "log_faults",
)
HART_FIELDS = (
    "sample", "hart", "case", "status", "logger_base", "size_readback",
    "capacity", "idx_before", "idx_at_fault", "idx_after", "ctl",
    "fault_count", "fault_cause", "fault_sepc", "fault_stval", "fault_htval",
    "pte_at_fault", "data_at_fault", "log0_at_fault", "log_last_at_fault",
    "guard_at_fault", "ecall_count", "ecall_cause", "cycle_start", "cycle_end",
    "instret_start", "instret_end", "prefill_value", "pte_final", "data_final",
    "log0_final", "log_last_final", "guard_final", "d_transitions",
    "committed_logs", "cas_attempts", "log_faults",
)
END_FIELDS = ("samples", "failures", "status")

PHYSICAL_RE = re.compile(
    r"^rv mmu physical-store (\d+) (\d+) (\d+) (\d+) ([0-9a-fA-F]+) "
    r"(\d+) ([0-9a-fA-F]+) (\d+) (pending|committed|superseded|error)$"
)
STORE_RE = re.compile(
    r"^rv mmu store (\d+) ([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) (\d+)$"
)
COMMIT_RE = re.compile(r"^rv commit (\d+) ([0-9a-fA-F]+) ")


class ReportError(RuntimeError):
    pass


class DiagnosticIncomplete(ReportError):
    pass


def parse_value(value: str) -> int:
    try:
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError as error:
        raise ReportError(f"non-integer firmware value {value!r}") from error


def parse_fields(tokens: list[str], context: str) -> dict[str, int]:
    fields: dict[str, int] = {}
    for token in tokens:
        if "=" not in token:
            raise ReportError(f"malformed {context} token {token!r}")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise ReportError(f"invalid or duplicate {context} field {key!r}")
        fields[key] = parse_value(value)
    return fields


def require_fields(record: dict[str, int], expected: tuple[str, ...], context: str) -> None:
    missing = sorted(set(expected) - set(record))
    extra = sorted(set(record) - set(expected))
    if missing or extra:
        raise ReportError(f"{context} fields missing={missing} extra={extra}")


def sentinel(hart: int, slot: int) -> int:
    return LOG_SENTINEL ^ (hart << 32) ^ slot


def expected_value(sample: int, hart: int) -> int:
    return VALUE_PREFIX | (sample << 16) | (hart << 8)


def logger_control(hart: int) -> int:
    return (((LOG_BASE + hart * LOG_STRIDE) >> 12) << 10) | 1


@dataclass
class BufferMcReport:
    begin: dict[str, int] | None = None
    samples: list[dict[str, int]] = field(default_factory=list)
    harts: list[dict[str, int]] = field(default_factory=list)
    end: dict[str, int] | None = None
    record_order: list[tuple[str, int, int | None]] = field(default_factory=list)

    def validate_shape(self, hart_count: int = HART_COUNT) -> None:
        if self.begin is None or self.end is None:
            raise ReportError("missing BEGIN or END")
        require_fields(self.begin, BEGIN_FIELDS, "BEGIN")
        require_fields(self.end, END_FIELDS, "END")
        expected_begin = {
            "abi": ABI_VERSION, "hart_count": hart_count, "case": CASE,
            "size": SIZE, "capacity": CAPACITY, "samples": RUNS,
        }
        if self.begin != expected_begin:
            raise ReportError(f"BEGIN mismatch: {self.begin!r}")
        if len(self.samples) != RUNS or len(self.harts) != RUNS * hart_count:
            raise ReportError(
                f"record count samples={len(self.samples)} harts={len(self.harts)}"
            )
        expected_order = [
            item for sample in range(RUNS)
            for item in ([('SAMPLE', sample, None)] +
                         [('HART', sample, hart) for hart in range(hart_count)])
        ]
        if self.record_order != expected_order:
            raise ReportError("SAMPLE/HART record order does not match buffer-mc ABI v1")
        for ordinal, record in enumerate(self.samples):
            require_fields(record, SAMPLE_FIELDS, f"SAMPLE {ordinal}")
            if record["sample"] != ordinal:
                raise ReportError(f"SAMPLE {ordinal} has wrong sample id")
        for ordinal, record in enumerate(self.harts):
            require_fields(record, HART_FIELDS, f"HART {ordinal}")
            sample, hart = divmod(ordinal, hart_count)
            if record["sample"] != sample or record["hart"] != hart:
                raise ReportError(f"HART {ordinal} has wrong sample/hart identity")

    def architecture_errors(self, hart_count: int = HART_COUNT) -> list[str]:
        self.validate_shape(hart_count)
        errors: list[str] = []
        if self.end != {"samples": RUNS, "failures": 0, "status": 0}:
            errors.append(f"END reports failure: {self.end!r}")
        harts = {(row["sample"], row["hart"]): row for row in self.harts}
        for sample_id, sample in enumerate(self.samples):
            fixed = {
                "sample": sample_id, "warmup": int(sample_id == 0),
                "repetition": 0 if sample_id == 0 else sample_id - 1,
                "status": 0, "pte_before": PTE_CLEAN, "pte_after": PTE_DIRTY,
                "data_errors": 0, "buffer_errors": 0, "d_transitions": 1,
                "committed_logs": 1, "log_faults": 0,
            }
            for name, expected in fixed.items():
                if sample[name] != expected:
                    errors.append(
                        f"sample {sample_id} {name}=0x{sample[name]:x}, expected 0x{expected:x}"
                    )
            # CAS participation is explicitly diagnostic and unconstrained.
            for hart in range(hart_count):
                row = harts[(sample_id, hart)]
                expected_index = 1 if hart == 0 else CAPACITY
                fixed_hart = {
                    "case": CASE, "status": 0,
                    "logger_base": LOG_BASE + hart * LOG_STRIDE,
                    "size_readback": SIZE, "capacity": CAPACITY,
                    "idx_before": 0 if hart == 0 else CAPACITY,
                    "idx_at_fault": 0, "idx_after": expected_index,
                    "ctl": logger_control(hart), "fault_count": 0,
                    "fault_cause": 0, "fault_sepc": 0, "fault_stval": 0,
                    "fault_htval": 0, "pte_at_fault": 0, "data_at_fault": 0,
                    "log0_at_fault": 0, "log_last_at_fault": 0,
                    "guard_at_fault": 0, "ecall_count": 1, "ecall_cause": 10,
                    "prefill_value": 0, "pte_final": PTE_DIRTY,
                    "data_final": expected_value(sample_id, hart),
                    "log0_final": (TRACKED_GPA if hart == 0 else sentinel(hart, 0)),
                    "log_last_final": sentinel(hart, CAPACITY - 1),
                    "guard_final": sentinel(hart, CAPACITY),
                    "d_transitions": 1 if hart == 0 else 0,
                    "committed_logs": 1 if hart == 0 else 0,
                    "log_faults": 0,
                }
                for name, expected in fixed_hart.items():
                    if row[name] != expected:
                        errors.append(
                            f"sample {sample_id} hart {hart} {name}=0x{row[name]:x}, "
                            f"expected 0x{expected:x}"
                        )
                if row["cycle_end"] < row["cycle_start"]:
                    errors.append(f"sample {sample_id} hart {hart} cycle interval is negative")
                if row["instret_end"] < row["instret_start"]:
                    errors.append(f"sample {sample_id} hart {hart} instret interval is negative")
        return errors

    def classification(self, observer_store_pc: int,
                       hart_count: int = HART_COUNT) -> str:
        """Classify the expected current-RTL failure without making it PASS."""
        try:
            self.validate_shape(hart_count)
        except ReportError:
            return "MALFORMED_OR_INCOMPLETE_FIRMWARE_EVIDENCE"
        observers = [row for row in self.harts if row["hart"] != 0]
        false_full = [
            row for row in observers
            if row["fault_count"] == 1
            and row["fault_cause"] == 24
            and row["fault_sepc"] == observer_store_pc
            and row["idx_before"] == CAPACITY
            and row["idx_at_fault"] == CAPACITY
            and row["idx_after"] == CAPACITY
            and row["pte_at_fault"] == PTE_DIRTY
            and row["data_at_fault"] == 0
            and row["log0_at_fault"] == sentinel(row["hart"], 0)
            and row["log_last_at_fault"] == sentinel(row["hart"], CAPACITY - 1)
            and row["guard_at_fault"] == sentinel(row["hart"], CAPACITY)
            and row["log_faults"] >= 1
        ]
        if len(false_full) == len(observers) and observers:
            return "STALE_D_FALSE_FULL_FAULT"
        return "OTHER_ARCHITECTURE_FAILURE"


def parse_lines(stream: TextIO) -> BufferMcReport:
    report = BufferMcReport()
    for line in stream:
        start = line.find(PREFIX)
        if start < 0:
            continue
        tokens = line[start:].strip().split()
        tag = tokens[0]
        fields = parse_fields(tokens[1:], tag)
        if tag == PREFIX + "_BEGIN":
            if report.begin is not None:
                raise ReportError("duplicate BEGIN")
            report.begin = fields
        elif tag == PREFIX + "_SAMPLE":
            report.samples.append(fields)
            report.record_order.append(("SAMPLE", fields.get("sample", -1), None))
        elif tag == PREFIX + "_HART":
            report.harts.append(fields)
            report.record_order.append(
                ("HART", fields.get("sample", -1), fields.get("hart", -1))
            )
        elif tag == PREFIX + "_END":
            if report.end is not None:
                raise ReportError("duplicate END")
            report.end = fields
        else:
            raise ReportError(f"unknown record {tag}")
    return report


def symbol_values(elf: Path) -> dict[str, int]:
    wanted = {
        "dirtygen_buffer_mc_guest_start", "dirtygen_buffer_mc_observer_store",
        "dirtygen_buffer_mc_producer_store", "dirtygen_buffer_mc_epoch_start",
        "dirtygen_buffer_mc_epoch_end",
    }
    try:
        output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReportError(f"cannot inspect ELF symbols: {error}") from error
    values: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted:
            values[parts[2]] = int(parts[0], 16)
    if set(values) != wanted:
        raise ReportError(f"ELF missing symbols: {sorted(wanted - set(values))}")
    return values


def check_trace(lines: TextIO, epoch_start_pc: int, epoch_end_pc: int,
                hart_count: int = HART_COUNT) -> dict[str, Any]:
    active: list[int | None] = [None] * hart_count
    next_sample = [0] * hart_count
    lifecycle: dict[tuple[int, int, int], dict[str, Any]] = {}
    stores: list[list[tuple[int, int, int, int, int]]] = [[] for _ in range(RUNS)]
    bad_markers: list[str] = []
    for raw in lines:
        line = raw.strip()
        lower = line.lower()
        if any(marker in lower for marker in (
                "rvls mismatch", "attribution error", "failure context",
                "residual mmustorequeue", "timeout")):
            bad_markers.append(line)
        match = COMMIT_RE.match(line)
        if match:
            hart, pc = int(match.group(1)), int(match.group(2), 16)
            if hart < hart_count and pc == epoch_start_pc:
                if active[hart] is not None or next_sample[hart] >= RUNS:
                    raise DiagnosticIncomplete(f"invalid epoch start hart={hart}")
                active[hart] = next_sample[hart]
                next_sample[hart] += 1
            elif hart < hart_count and pc == epoch_end_pc:
                if active[hart] is None:
                    raise DiagnosticIncomplete(f"epoch end without start hart={hart}")
                active[hart] = None
            continue
        match = PHYSICAL_RE.match(line)
        if match:
            hart, source, attempt, cycle = map(int, match.group(1, 2, 3, 4))
            address = int(match.group(5), 16)
            length = int(match.group(6))
            data = int(match.group(7), 16)
            error = int(match.group(8))
            state = match.group(9)
            key = (hart, source, attempt)
            if hart >= hart_count or (active[hart] is None and key not in lifecycle):
                raise DiagnosticIncomplete(f"unattributable physical lifecycle: {line}")
            entry = lifecycle.setdefault(key, {
                "sample": active[hart], "hart": hart, "source": source,
                "attempt": attempt, "observed_cycle": cycle, "address": address,
                "length": length, "data": data, "error": error, "states": [],
            })
            if any(entry[name] != value for name, value in (
                    ("address", address), ("length", length), ("data", data),
                    ("error", error))):
                raise ReportError(f"physical lifecycle context changed for {key}")
            entry["states"].append(state)
            continue
        match = STORE_RE.match(line)
        if match:
            hart = int(match.group(1))
            if hart >= hart_count or active[hart] is None:
                raise DiagnosticIncomplete(f"unattributable MMU store: {line}")
            stores[active[hart]].append((
                hart, int(match.group(2), 16), int(match.group(3)),
                int(match.group(4), 16), int(match.group(5)),
            ))
        elif line.startswith(("rv mmu physical-store", "rv mmu store")):
            raise DiagnosticIncomplete(f"malformed MMU record: {line}")
    if bad_markers:
        raise ReportError(f"trace failure marker: {bad_markers[0]}")
    if any(item is not None for item in active) or next_sample != [RUNS] * hart_count:
        raise DiagnosticIncomplete(
            f"incomplete epochs active={active} completed={next_sample}"
        )

    per_sample: list[dict[str, Any]] = []
    lifecycle_rows: list[dict[str, Any]] = []
    for entry in sorted(lifecycle.values(), key=lambda row: (
            row["sample"], row["hart"], row["source"], row["attempt"])):
        if entry["states"] not in (["pending", "committed"],
                                    ["pending", "superseded"], ["error"]):
            raise ReportError(
                f"open/duplicate lifecycle {(entry['hart'], entry['source'], entry['attempt'])} "
                f"states={entry['states']}"
            )
        lifecycle_rows.append({
            **entry, "address": f"0x{entry['address']:016x}",
            "data": f"0x{entry['data']:016x}",
            "terminal_state": entry["states"][-1],
        })
    for sample in range(RUNS):
        events = [row for row in lifecycle.values() if row["sample"] == sample]
        committed = [row for row in events if row["states"] == ["pending", "committed"]]
        superseded = [row for row in events if row["states"] == ["pending", "superseded"]]
        errors = [row for row in events if row["states"] == ["error"]]
        if len(committed) != 1 or superseded or errors:
            raise ReportError(
                f"sample {sample} physical lifecycle committed={len(committed)} "
                f"superseded={len(superseded)} errors={len(errors)}"
            )
        event = committed[0]
        if (event["hart"], event["address"], event["length"], event["data"],
                event["error"]) != (0, LOG_BASE, 8, TRACKED_GPA, 0):
            raise ReportError(f"sample {sample} malformed committed logger event")
        wanted = {
            (0, LOG_BASE, 8, TRACKED_GPA, 0),
            (0, PTE_ADDRESS, 8, PTE_DIRTY, 0),
        }
        observed = set(stores[sample])
        if observed != wanted or len(stores[sample]) != len(wanted):
            raise ReportError(
                f"sample {sample} architectural MMU stores {stores[sample]!r}, "
                f"expected {sorted(wanted)!r}"
            )
        per_sample.append({
            "sample": sample, "physical_attempts": len(events),
            "committed": len(committed), "superseded": len(superseded),
            "errors": len(errors), "architectural_stores": len(stores[sample]),
        })
    return {
        "schema": "shdlt-buffer-boundary-phase4-trace-v1", "status": "PASS",
        "sample_segmentation": "per-hart HS epoch",
        "samples": per_sample, "lifecycles": lifecycle_rows,
        "totals": {
            name: sum(row[name] for row in per_sample)
            for name in ("physical_attempts", "committed", "superseded", "errors",
                         "architectural_stores")
        },
    }


def write_outputs(report: BufferMcReport, output_dir: Path,
                  verdict: dict[str, Any], trace: dict[str, Any] | None,
                  hart_count: int = HART_COUNT) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    harts = {(row["sample"], row["hart"]): row for row in report.harts}
    samples = []
    for sample in report.samples:
        item: dict[str, Any] = dict(sample)
        item["harts"] = [harts[(sample["sample"], hart)]
                         for hart in range(hart_count)
                         if (sample["sample"], hart) in harts]
        samples.append(item)
    document = {
        "schema": "shdlt-buffer-boundary-phase4-samples-v1",
        "begin": report.begin, "samples": samples, "end": report.end,
    }
    (output_dir / "samples.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    )
    if trace is not None:
        (output_dir / "trace-report.json").write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console", type=Path)
    parser.add_argument("--tracer", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--hart-count", type=int, choices=(2, 4), default=2)
    args = parser.parse_args(argv)
    if (args.tracer is None) != (args.elf is None):
        parser.error("--tracer and --elf must be supplied together")

    report = BufferMcReport()
    trace_report: dict[str, Any] | None = None
    try:
        with args.console.open(errors="replace") as stream:
            report = parse_lines(stream)
        symbols = symbol_values(args.elf) if args.elf else {}
        errors = report.architecture_errors(args.hart_count)
        observer_pc = 0
        if symbols:
            observer_pc = (symbols["dirtygen_buffer_mc_observer_store"] -
                           symbols["dirtygen_buffer_mc_guest_start"])
        classification = ("PASS" if not errors else
                          report.classification(observer_pc, args.hart_count))
        architecture_status = "PASS" if not errors else "FAIL"
        trace_status = "NOT_REQUESTED"
        trace_error = None
        if args.tracer:
            try:
                with args.tracer.open(errors="replace") as stream:
                    trace_report = check_trace(
                        stream, symbols["dirtygen_buffer_mc_epoch_start"],
                        symbols["dirtygen_buffer_mc_epoch_end"], args.hart_count
                    )
                trace_status = "PASS"
            except (OSError, ReportError) as error:
                trace_status = "INCOMPLETE"
                trace_error = str(error)
                trace_report = {
                    "schema": "shdlt-buffer-boundary-phase4-trace-v1",
                    "status": "INCOMPLETE", "error": trace_error,
                }
        verdict = {
            "schema": "shdlt-buffer-boundary-phase4-verdict-v1",
            "status": "PASS" if not errors and trace_status in ("PASS", "NOT_REQUESTED") else "FAIL",
            "architecture_status": architecture_status,
            "classification": classification,
            "architecture_errors": errors,
            "trace_status": trace_status,
            "trace_error": trace_error,
        }
        if args.output_dir:
            write_outputs(report, args.output_dir, verdict, trace_report,
                          args.hart_count)
        if errors:
            print(f"dirtygen buffer mc: FAIL {classification}: {errors[0]}", file=sys.stderr)
            return 1
        if trace_status == "INCOMPLETE":
            print(f"dirtygen buffer mc: firmware PASS; trace incomplete: {trace_error}", file=sys.stderr)
            return 2
        print(f"dirtygen buffer mc: PASS harts={args.hart_count} "
              "case=STALE_D_FULL_OBSERVERS size=0 samples=6")
        return 0
    except (OSError, ReportError, ValueError) as error:
        verdict = {
            "schema": "shdlt-buffer-boundary-phase4-verdict-v1",
            "status": "FAIL", "architecture_status": "INCOMPLETE",
            "classification": "MALFORMED_OR_INCOMPLETE_FIRMWARE_EVIDENCE",
            "architecture_errors": [str(error)], "trace_status": "NOT_CHECKED",
            "trace_error": None,
        }
        if args.output_dir:
            write_outputs(report, args.output_dir, verdict, trace_report,
                          args.hart_count)
        print(f"dirtygen buffer mc report error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
