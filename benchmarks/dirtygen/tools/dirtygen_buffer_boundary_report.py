#!/usr/bin/env python3
"""Strict validator for the SHDLT Phase-4 buffer-boundary ABI v1."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, TextIO


PREFIX = "SHDLT_BUFFER_BOUNDARY"
ABI_VERSION = 1
STRESS_ABI_VERSION = 2
PROFILE_H1 = 1
PROFILE_MULTI = 2
PROFILE_STRESS = 3
STRESS_RUNS = 6
MAX_INDEX = 0xFFFFF
TRACKED_GPA = 0x10000
TRACKED_PHYSICAL = 0x81200000
PTE_BASE = 0x81005080
PTE_FLAGS_CLEAN = 0x57
PTE_FLAGS_DIRTY = 0xD7
LOG_BASE = 0x83000000
LOG_HART_STRIDE = 0x00800000
LOG_REPLACEMENT_OFFSET = 0x00400000
LOG_SENTINEL = 0x51D1700000000000
REPLACEMENT_SENTINEL = 0x6EA2E00000000000
VALUE_PREFIX = 0xB500000000000000

LAST_SLOT_COMMIT = 1
EXACT_FULL_FAULT = 2
OVERFULL_MAX_INDEX_FAULT = 3
FULL_PREDIRTY_BYPASS = 4
FULL_LOG_OFF_BYPASS = 5
REPLACE_AND_RETRY = 6
PRIVATE_FULL_ALL = 7
STALE_D_FULL_OBSERVERS = 8
PRIVATE_RECOVER_ALL = 9
STALE_D_SPACE_OBSERVERS = 10
RESERVED_SIZE_WARL = 11

BEGIN_FIELDS = ("abi", "profile", "hart_count", "selections")
SAMPLE_FIELDS = (
    "selection", "case", "size_requested", "hart_count", "status",
    "pte_errors", "data_errors", "buffer_errors", "control_errors",
    "faults", "d_transitions", "committed_logs", "cas_attempts",
    "log_faults",
)
SAMPLE_STRESS_FIELDS = SAMPLE_FIELDS + ("warmup", "repetition")
HART_FIELDS = (
    "selection", "case", "hart", "status", "size_requested",
    "size_readback", "capacity", "base_readback", "idx_before",
    "idx_at_fault", "idx_after", "ctl", "fault_count", "fault_cause",
    "fault_sepc", "fault_stval", "fault_htval", "pte_at_fault",
    "data_at_fault", "primary0_at_fault", "primary_last_at_fault",
    "primary_guard_at_fault", "ecall_count", "ecall_cause", "cycle_start",
    "cycle_end", "instret_start", "instret_end", "prefill_value",
    "pte_before", "pte_final", "data_final", "primary0_final",
    "primary_last_final", "primary_guard_final", "replacement0_final",
    "replacement_last_final", "replacement_guard_final", "d_transitions",
    "committed_logs", "cas_attempts", "log_faults",
)
HART_STRESS_FIELDS = HART_FIELDS + ("fault_entry_cycle", "fault_resume_cycle")
END_FIELDS = ("selections", "failures", "status")

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
    result: dict[str, int] = {}
    for token in tokens:
        if "=" not in token:
            raise ReportError(f"malformed {context} token {token!r}")
        name, value = token.split("=", 1)
        if not name or not value or name in result:
            raise ReportError(f"invalid or duplicate {context} field {name!r}")
        result[name] = parse_value(value)
    return result


def require_fields(record: dict[str, int], expected: tuple[str, ...], context: str) -> None:
    missing = sorted(set(expected) - set(record))
    extra = sorted(set(record) - set(expected))
    if missing or extra:
        raise ReportError(f"{context} fields missing={missing} extra={extra}")


def capacity(size: int) -> int:
    return 1 << (size + 9)


def schedule(profile: int, hart_count: int = 1) -> list[tuple[int, int]]:
    if profile == PROFILE_H1:
        return [(case, size) for size in range(10) for case in range(1, 7)] + [
            (RESERVED_SIZE_WARL, size) for size in range(10, 16)
        ]
    if profile == PROFILE_MULTI:
        cases = (STALE_D_FULL_OBSERVERS, PRIVATE_FULL_ALL,
                 PRIVATE_RECOVER_ALL, STALE_D_SPACE_OBSERVERS)
        return [(case, size) for size in (0, 9) for case in cases]
    if profile == PROFILE_STRESS:
        cases = [LAST_SLOT_COMMIT, EXACT_FULL_FAULT, REPLACE_AND_RETRY]
        if hart_count != 1:
            cases.append(STALE_D_FULL_OBSERVERS)
        return [(case, 0) for case in cases for _ in range(STRESS_RUNS)]
    raise ReportError(f"unsupported profile {profile}")


def primary(hart: int) -> int:
    return LOG_BASE + hart * LOG_HART_STRIDE


def replacement(hart: int) -> int:
    return primary(hart) + LOG_REPLACEMENT_OFFSET


def sentinel(hart: int, slot: int) -> int:
    return LOG_SENTINEL ^ (hart << 32) ^ slot


def replacement_sentinel(hart: int, slot: int) -> int:
    return REPLACEMENT_SENTINEL ^ (hart << 32) ^ slot


def is_private(case: int) -> bool:
    return case in (PRIVATE_FULL_ALL, PRIVATE_RECOVER_ALL)


def target_page(case: int, hart: int) -> int:
    return hart if is_private(case) else 0


def target_gpa(case: int, hart: int) -> int:
    return TRACKED_GPA + target_page(case, hart) * 0x1000


def pte(page: int, dirty: bool) -> int:
    physical = TRACKED_PHYSICAL + page * 0x1000
    return ((physical >> 12) << 10) | (PTE_FLAGS_DIRTY if dirty else PTE_FLAGS_CLEAN)


def value(selection: int, hart: int) -> int:
    return VALUE_PREFIX | (selection << 16) | (hart << 8)


def value_hart(case: int, hart: int) -> int:
    return hart if is_private(case) or case in (
        STALE_D_FULL_OBSERVERS, STALE_D_SPACE_OBSERVERS) else 0


def hart_executes_store(profile: int, case: int, hart: int) -> bool:
    return not (profile == PROFILE_STRESS and hart != 0 and
                case != STALE_D_FULL_OBSERVERS)


def logging_enabled(case: int) -> bool:
    return case not in (FULL_LOG_OFF_BYPASS, RESERVED_SIZE_WARL)


def recovery(case: int) -> bool:
    return case in (REPLACE_AND_RETRY, PRIVATE_RECOVER_ALL)


def fault_count(case: int, hart: int) -> int:
    if case in (PRIVATE_FULL_ALL, PRIVATE_RECOVER_ALL):
        return 1
    return int(hart == 0 and case in (
        EXACT_FULL_FAULT, OVERFULL_MAX_INDEX_FAULT, REPLACE_AND_RETRY))


def store_succeeds(case: int) -> bool:
    return case not in (
        EXACT_FULL_FAULT, OVERFULL_MAX_INDEX_FAULT, PRIVATE_FULL_ALL,
        RESERVED_SIZE_WARL,
    )


def initial_index(case: int, hart: int, cap: int) -> int:
    if case == LAST_SLOT_COMMIT:
        return cap - 1
    if case == OVERFULL_MAX_INDEX_FAULT:
        return MAX_INDEX
    if case == STALE_D_FULL_OBSERVERS:
        return 0 if hart == 0 else cap
    if case in (STALE_D_SPACE_OBSERVERS, RESERVED_SIZE_WARL):
        return 0
    return cap


def final_index(case: int, hart: int, cap: int) -> int:
    if case == LAST_SLOT_COMMIT:
        return cap if hart == 0 else cap - 1
    if case == OVERFULL_MAX_INDEX_FAULT:
        return MAX_INDEX
    if case == REPLACE_AND_RETRY:
        return 1 if hart == 0 else cap
    if case == PRIVATE_RECOVER_ALL:
        return 1
    if case == STALE_D_FULL_OBSERVERS:
        return 1 if hart == 0 else cap
    if case == STALE_D_SPACE_OBSERVERS:
        return 1 if hart == 0 else 0
    if case == RESERVED_SIZE_WARL:
        return 0
    return cap


def expected_d(case: int, hart: int) -> int:
    if case in (LAST_SLOT_COMMIT, FULL_LOG_OFF_BYPASS, REPLACE_AND_RETRY):
        return int(hart == 0)
    if case == PRIVATE_RECOVER_ALL:
        return 1
    if case in (STALE_D_FULL_OBSERVERS, STALE_D_SPACE_OBSERVERS):
        return int(hart == 0)
    return 0


def expected_log(case: int, hart: int) -> int:
    if case in (LAST_SLOT_COMMIT, REPLACE_AND_RETRY):
        return int(hart == 0)
    if case == PRIVATE_RECOVER_ALL:
        return 1
    if case in (STALE_D_FULL_OBSERVERS, STALE_D_SPACE_OBSERVERS):
        return int(hart == 0)
    return 0


def final_dirty(case: int) -> bool:
    return case not in (
        EXACT_FULL_FAULT, OVERFULL_MAX_INDEX_FAULT, PRIVATE_FULL_ALL,
        RESERVED_SIZE_WARL,
    )


@dataclass
class BoundaryReport:
    begin: dict[str, int] | None = None
    samples: list[dict[str, int]] = field(default_factory=list)
    harts: list[dict[str, int]] = field(default_factory=list)
    end: dict[str, int] | None = None
    order: list[tuple[str, int, int | None]] = field(default_factory=list)

    def validate_shape(self, hart_count: int, profile: int) -> None:
        if self.begin is None or self.end is None:
            raise ReportError("missing BEGIN or END")
        require_fields(self.begin, BEGIN_FIELDS, "BEGIN")
        require_fields(self.end, END_FIELDS, "END")
        wanted = schedule(profile, hart_count)
        abi = STRESS_ABI_VERSION if profile == PROFILE_STRESS else ABI_VERSION
        if self.begin != {"abi": abi, "profile": profile,
                          "hart_count": hart_count, "selections": len(wanted)}:
            raise ReportError(f"BEGIN mismatch: {self.begin!r}")
        if len(self.samples) != len(wanted) or len(self.harts) != len(wanted) * hart_count:
            raise ReportError(
                f"record count samples={len(self.samples)} harts={len(self.harts)}")
        expected_order = [item for selection in range(len(wanted)) for item in (
            [("SAMPLE", selection, None)] +
            [("HART", selection, hart) for hart in range(hart_count)])]
        if self.order != expected_order:
            raise ReportError("record order does not match ABI v1")
        for ordinal, record in enumerate(self.samples):
            require_fields(record, SAMPLE_STRESS_FIELDS if profile == PROFILE_STRESS
                           else SAMPLE_FIELDS, f"SAMPLE {ordinal}")
            if record["selection"] != ordinal:
                raise ReportError(f"SAMPLE {ordinal} has wrong identity")
        for ordinal, record in enumerate(self.harts):
            require_fields(record, HART_STRESS_FIELDS if profile == PROFILE_STRESS
                           else HART_FIELDS, f"HART {ordinal}")
            selection, hart = divmod(ordinal, hart_count)
            if record["selection"] != selection or record["hart"] != hart:
                raise ReportError(f"HART {ordinal} has wrong identity")

    def architecture_errors(self, hart_count: int, profile: int,
                            store_pc: int) -> list[str]:
        self.validate_shape(hart_count, profile)
        errors: list[str] = []
        wanted_schedule = schedule(profile, hart_count)
        if self.end != {"selections": len(wanted_schedule), "failures": 0, "status": 0}:
            errors.append(f"END reports failure: {self.end!r}")
        rows = {(row["selection"], row["hart"]): row for row in self.harts}
        for selection, (case, requested_size) in enumerate(wanted_schedule):
            sample = self.samples[selection]
            expected_faults = sum(fault_count(case, hart) for hart in range(hart_count))
            expected_ds = sum(expected_d(case, hart) for hart in range(hart_count))
            expected_logs = sum(expected_log(case, hart) for hart in range(hart_count))
            fixed_sample = {
                "case": case, "size_requested": requested_size,
                "hart_count": hart_count, "status": 0, "pte_errors": 0,
                "data_errors": 0, "buffer_errors": 0, "control_errors": 0,
                "faults": expected_faults, "d_transitions": expected_ds,
                "committed_logs": expected_logs, "log_faults": expected_faults,
            }
            if profile == PROFILE_STRESS:
                within_case = selection % STRESS_RUNS
                fixed_sample.update({
                    "warmup": int(within_case == 0),
                    "repetition": 0 if within_case == 0 else within_case - 1,
                })
            for name, expected in fixed_sample.items():
                if sample[name] != expected:
                    errors.append(
                        f"selection {selection} {name}=0x{sample[name]:x}, expected 0x{expected:x}")
            for hart in range(hart_count):
                row = rows[(selection, hart)]
                size = row["size_readback"]
                if case == RESERVED_SIZE_WARL:
                    if size > 9:
                        errors.append(f"selection {selection} hart {hart} illegal WARL SIZE {size}")
                        size = 0
                elif size != requested_size:
                    errors.append(
                        f"selection {selection} hart {hart} SIZE={size}, expected {requested_size}")
                cap = capacity(size)
                base = primary(hart)
                expected_ctl = ((base >> 12) << 10) | (size << 1) | int(logging_enabled(case))
                before_dirty = case == FULL_PREDIRTY_BYPASS
                final_pte = pte(target_page(case, hart), final_dirty(case))
                expected_fault = fault_count(case, hart)
                expected_primary0 = sentinel(hart, 0)
                expected_primary_last = sentinel(hart, cap - 1)
                expected_replacement0 = replacement_sentinel(hart, 0)
                if case == LAST_SLOT_COMMIT and hart == 0:
                    expected_primary_last = target_gpa(case, hart)
                if case in (STALE_D_FULL_OBSERVERS, STALE_D_SPACE_OBSERVERS) and hart == 0:
                    expected_primary0 = target_gpa(case, hart)
                if recovery(case) and expected_fault:
                    expected_replacement0 = target_gpa(case, hart)
                fixed_hart = {
                    "case": case, "status": 0, "size_requested": requested_size,
                    "capacity": cap, "base_readback": base,
                    "idx_before": initial_index(case, hart, cap),
                    "idx_at_fault": initial_index(case, hart, cap) if expected_fault else 0,
                    "idx_after": final_index(case, hart, cap), "ctl": expected_ctl,
                    "fault_count": expected_fault,
                    "fault_cause": 24 if expected_fault else 0,
                    "fault_sepc": store_pc if expected_fault else 0,
                    "pte_at_fault": pte(target_page(case, hart), False) if expected_fault else 0,
                    "data_at_fault": 0, "primary0_at_fault": sentinel(hart, 0) if expected_fault else 0,
                    "primary_last_at_fault": sentinel(hart, cap - 1) if expected_fault else 0,
                    "primary_guard_at_fault": sentinel(hart, cap) if expected_fault else 0,
                    "ecall_count": 1, "ecall_cause": 10,
                    "prefill_value": 0,
                    "pte_before": pte(target_page(case, hart), before_dirty),
                    "pte_final": final_pte,
                    "data_final": value(selection, value_hart(case, hart))
                    if store_succeeds(case) else 0,
                    "primary0_final": expected_primary0,
                    "primary_last_final": expected_primary_last,
                    "primary_guard_final": sentinel(hart, cap),
                    "replacement0_final": expected_replacement0,
                    "replacement_last_final": replacement_sentinel(hart, cap - 1),
                    "replacement_guard_final": replacement_sentinel(hart, cap),
                    "d_transitions": expected_d(case, hart),
                    "committed_logs": expected_log(case, hart),
                    "log_faults": expected_fault,
                }
                for name, expected in fixed_hart.items():
                    if row[name] != expected:
                        errors.append(
                            f"selection {selection} hart {hart} {name}=0x{row[name]:x}, "
                            f"expected 0x{expected:x}")
                if row["cycle_end"] < row["cycle_start"]:
                    errors.append(f"selection {selection} hart {hart} negative cycle interval")
                if row["instret_end"] < row["instret_start"]:
                    errors.append(f"selection {selection} hart {hart} negative instret interval")
                if profile == PROFILE_STRESS:
                    if expected_fault:
                        if not (row["cycle_start"] <= row["fault_entry_cycle"] <=
                                row["fault_resume_cycle"] <= row["cycle_end"]):
                            errors.append(
                                f"selection {selection} hart {hart} invalid fault timing order")
                    elif row["fault_entry_cycle"] != 0 or row["fault_resume_cycle"] != 0:
                        errors.append(
                            f"selection {selection} hart {hart} has timing for no fault")
                # stval/htval and CAS participation are intentionally diagnostic.
        return errors


def parse_lines(stream: TextIO) -> BoundaryReport:
    report = BoundaryReport()
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
            report.order.append(("SAMPLE", fields.get("selection", -1), None))
        elif tag == PREFIX + "_HART":
            report.harts.append(fields)
            report.order.append(("HART", fields.get("selection", -1), fields.get("hart", -1)))
        elif tag == PREFIX + "_END":
            if report.end is not None:
                raise ReportError("duplicate END")
            report.end = fields
        else:
            raise ReportError(f"unknown record {tag}")
    return report


def symbol_values(elf: Path) -> dict[str, int]:
    wanted = {"boundary_mc_guest_start", "boundary_mc_store",
              "boundary_mc_epoch_start", "boundary_mc_epoch_end"}
    try:
        output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReportError(f"cannot inspect ELF symbols: {error}") from error
    result: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted:
            result[parts[2]] = int(parts[0], 16)
    if set(result) != wanted:
        raise ReportError(f"ELF missing symbols: {sorted(wanted - set(result))}")
    return result


def expected_committed_logs(case: int, cap: int, hart_count: int) -> list[tuple[int, int, int, int, int]]:
    if case == LAST_SLOT_COMMIT:
        return [(0, primary(0) + (cap - 1) * 8, 8, target_gpa(case, 0), 0)]
    if case == REPLACE_AND_RETRY:
        return [(0, replacement(0), 8, target_gpa(case, 0), 0)]
    if case == PRIVATE_RECOVER_ALL:
        return [(hart, replacement(hart), 8, target_gpa(case, hart), 0)
                for hart in range(hart_count)]
    if case in (STALE_D_FULL_OBSERVERS, STALE_D_SPACE_OBSERVERS):
        return [(0, primary(0), 8, target_gpa(case, 0), 0)]
    return []


def expected_pte_stores(case: int, hart_count: int) -> list[tuple[int, int, int, int, int]]:
    result = []
    for hart in range(hart_count):
        if expected_d(case, hart):
            page = target_page(case, hart)
            result.append((hart, PTE_BASE + page * 8, 8, pte(page, True), 0))
    return result


def check_trace(stream: TextIO, epoch_start_pc: int, epoch_end_pc: int,
                hart_count: int, profile: int) -> dict[str, Any]:
    wanted_schedule = schedule(profile, hart_count)
    active: list[int | None] = [None] * hart_count
    next_selection = [0] * hart_count
    lifecycles: dict[tuple[int, int, int], dict[str, Any]] = {}
    stores: list[list[tuple[int, int, int, int, int]]] = [
        [] for _ in wanted_schedule]
    bad_markers: list[str] = []
    for raw in stream:
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
                if active[hart] is not None or next_selection[hart] >= len(wanted_schedule):
                    raise DiagnosticIncomplete(f"invalid epoch start hart={hart}")
                active[hart] = next_selection[hart]
                next_selection[hart] += 1
            elif hart < hart_count and pc == epoch_end_pc:
                if active[hart] is None:
                    raise DiagnosticIncomplete(f"epoch end without start hart={hart}")
                active[hart] = None
            continue
        match = PHYSICAL_RE.match(line)
        if match:
            hart, source, attempt, observed_cycle = map(int, match.group(1, 2, 3, 4))
            address, length = int(match.group(5), 16), int(match.group(6))
            data, error, state = int(match.group(7), 16), int(match.group(8)), match.group(9)
            key = (hart, source, attempt)
            if hart >= hart_count or (active[hart] is None and key not in lifecycles):
                raise DiagnosticIncomplete(f"unattributable physical lifecycle: {line}")
            row = lifecycles.setdefault(key, {
                "selection": active[hart], "hart": hart, "source": source,
                "attempt": attempt, "observed_cycle": observed_cycle,
                "address": address, "length": length, "data": data,
                "error": error, "states": [],
            })
            if any(row[name] != expected for name, expected in (
                    ("address", address), ("length", length), ("data", data),
                    ("error", error))):
                raise ReportError(f"physical lifecycle context changed for {key}")
            row["states"].append(state)
            continue
        match = STORE_RE.match(line)
        if match:
            hart = int(match.group(1))
            if hart >= hart_count or active[hart] is None:
                raise DiagnosticIncomplete(f"unattributable MMU store: {line}")
            stores[active[hart]].append((
                hart, int(match.group(2), 16), int(match.group(3)),
                int(match.group(4), 16), int(match.group(5))))
        elif line.startswith(("rv mmu physical-store", "rv mmu store")):
            raise DiagnosticIncomplete(f"malformed MMU record: {line}")
    if bad_markers:
        raise ReportError(f"trace failure marker: {bad_markers[0]}")
    if any(item is not None for item in active) or next_selection != [len(wanted_schedule)] * hart_count:
        raise DiagnosticIncomplete(
            f"incomplete epochs active={active} completed={next_selection}")

    lifecycle_rows = []
    per_selection = []
    for row in sorted(lifecycles.values(), key=lambda item: (
            item["selection"], item["hart"], item["source"], item["attempt"])):
        if row["states"] not in (["pending", "committed"], ["pending", "superseded"], ["error"]):
            raise ReportError(
                f"open/duplicate lifecycle {(row['hart'], row['source'], row['attempt'])} "
                f"states={row['states']}")
        lifecycle_rows.append({
            **row, "address": f"0x{row['address']:016x}",
            "data": f"0x{row['data']:016x}",
            "terminal_state": row["states"][-1],
        })
    for selection, (case, requested_size) in enumerate(wanted_schedule):
        cap = capacity(requested_size if requested_size <= 9 else 0)
        events = [row for row in lifecycles.values() if row["selection"] == selection]
        committed = [row for row in events if row["states"] == ["pending", "committed"]]
        superseded = [row for row in events if row["states"] == ["pending", "superseded"]]
        errors = [row for row in events if row["states"] == ["error"]]
        expected_logs = expected_committed_logs(case, cap, hart_count)
        observed_logs = [(row["hart"], row["address"], row["length"],
                          row["data"], row["error"]) for row in committed]
        if Counter(observed_logs) != Counter(expected_logs):
            raise ReportError(
                f"selection {selection} committed logger events {observed_logs!r}, "
                f"expected {expected_logs!r}")
        if errors:
            raise ReportError(f"selection {selection} has physical logger errors")
        if superseded and case not in (STALE_D_FULL_OBSERVERS, STALE_D_SPACE_OBSERVERS):
            raise ReportError(f"selection {selection} has unexpected superseded logger attempt")
        for row in superseded:
            expected_slot = cap if case == STALE_D_FULL_OBSERVERS else 0
            if (row["hart"] == 0 or row["length"] != 8 or row["error"] != 0 or
                    row["address"] != primary(row["hart"]) + expected_slot * 8 or
                    row["data"] != target_gpa(case, row["hart"])):
                raise ReportError(f"selection {selection} malformed superseded event")
        expected_stores = expected_logs + expected_pte_stores(case, hart_count)
        if Counter(stores[selection]) != Counter(expected_stores):
            raise ReportError(
                f"selection {selection} architectural MMU stores {stores[selection]!r}, "
                f"expected {expected_stores!r}")
        per_selection.append({
            "selection": selection, "case": case, "size_requested": requested_size,
            "physical_attempts": len(events), "committed": len(committed),
            "superseded": len(superseded), "errors": len(errors),
            "architectural_stores": len(stores[selection]),
        })
    return {
        "schema": "shdlt-buffer-boundary-phase4-trace-v1", "status": "PASS",
        "sample_segmentation": "per-hart HS selection epoch",
        "selections": per_selection, "lifecycles": lifecycle_rows,
        "totals": {name: sum(row[name] for row in per_selection) for name in (
            "physical_attempts", "committed", "superseded", "errors",
            "architectural_stores")},
    }


def diagnostic_trace_summary(stream: TextIO) -> dict[str, Any]:
    """Summarize raw lifecycle evidence without changing a firmware FAIL."""
    lifecycles: dict[tuple[int, int, int], list[str]] = {}
    state_counts: Counter[str] = Counter()
    mmu_stores = 0
    diagnostics: list[str] = []
    for raw in stream:
        line = raw.strip()
        lower = line.lower()
        if any(marker in lower for marker in (
                "rvls mismatch", "attribution error", "failure context",
                "residual mmustorequeue", "timeout")):
            diagnostics.append(f"trace failure marker: {line}")
        match = PHYSICAL_RE.match(line)
        if match:
            key = tuple(map(int, match.group(1, 2, 3)))
            state = match.group(9)
            lifecycles.setdefault(key, []).append(state)
            state_counts[state] += 1
            continue
        if STORE_RE.match(line):
            mmu_stores += 1
        elif line.startswith(("rv mmu physical-store", "rv mmu store")):
            diagnostics.append(f"malformed MMU record: {line}")
    terminal_counts: Counter[str] = Counter()
    for key, states in sorted(lifecycles.items()):
        if states in (["pending", "committed"], ["pending", "superseded"],
                      ["error"]):
            terminal_counts[states[-1]] += 1
        else:
            diagnostics.append(f"open/duplicate lifecycle {key}: {states}")
    return {
        "schema": "shdlt-buffer-boundary-phase4-trace-diagnostic-v1",
        "status": "PASS" if not diagnostics else "DIAGNOSTIC_INCOMPLETE",
        "architecture_verdict_independent": True,
        "totals": {
            "lifecycles": len(lifecycles),
            "pending_records": state_counts["pending"],
            "committed": terminal_counts["committed"],
            "superseded": terminal_counts["superseded"],
            "errors": terminal_counts["error"],
            "architectural_stores": mmu_stores,
        },
        "diagnostics": diagnostics,
    }


def stress_performance(report: BoundaryReport, hart_count: int) -> dict[str, Any]:
    rows = {(row["selection"], row["hart"]): row for row in report.harts}
    names = {
        LAST_SLOT_COMMIT: "LAST_SLOT_COMMIT",
        EXACT_FULL_FAULT: "EXACT_FULL_FAULT",
        REPLACE_AND_RETRY: "REPLACE_AND_RETRY",
        STALE_D_FULL_OBSERVERS: "STALE_D_FULL_OBSERVERS",
    }
    records: list[dict[str, Any]] = []
    for selection, (case, _) in enumerate(schedule(PROFILE_STRESS, hart_count)):
        active_harts = (range(hart_count) if case == STALE_D_FULL_OBSERVERS
                        else range(1))
        active = [rows[(selection, hart)] for hart in active_harts]
        starts = [row["cycle_start"] for row in active]
        ends = [row["cycle_end"] for row in active]
        start, end = min(starts), max(ends)
        successful_stores = (hart_count if case == STALE_D_FULL_OBSERVERS
                             else int(case != EXACT_FULL_FAULT))
        item: dict[str, Any] = {
            "selection": selection,
            "case": case,
            "case_name": names[case],
            "warmup": int(selection % STRESS_RUNS == 0),
            "repetition": (0 if selection % STRESS_RUNS == 0
                           else selection % STRESS_RUNS - 1),
            "active_harts": list(active_harts),
            "completion_cycles": end - start,
            "successful_stores": successful_stores,
            "stores_per_1000_cycles": (
                successful_stores * 1000.0 / (end - start)
                if end != start else 0.0),
            "hpm": {
                "d_transitions": sum(row["d_transitions"] for row in active),
                "committed_logs": sum(row["committed_logs"] for row in active),
                "cas_attempts": sum(row["cas_attempts"] for row in active),
                "log_faults": sum(row["log_faults"] for row in active),
                "cas_attempts_per_hart": [row["cas_attempts"] for row in active],
                "log_faults_per_hart": [row["log_faults"] for row in active],
            },
            "harts": [],
        }
        for row in active:
            hart_metrics: dict[str, Any] = {
                "hart": row["hart"],
                "timed_cycles": row["cycle_end"] - row["cycle_start"],
                "fault_delivery_cycles": 0,
                "handler_service_cycles": 0,
                "retry_or_return_cycles": 0,
            }
            if row["fault_count"]:
                hart_metrics.update({
                    "fault_delivery_cycles": (
                        row["fault_entry_cycle"] - row["cycle_start"]),
                    "handler_service_cycles": (
                        row["fault_resume_cycle"] - row["fault_entry_cycle"]),
                    "retry_or_return_cycles": (
                        row["cycle_end"] - row["fault_resume_cycle"]),
                })
            item["harts"].append(hart_metrics)
        records.append(item)

    summary: dict[str, Any] = {}
    for case, name in names.items():
        measured = [row for row in records
                    if row["case"] == case and not row["warmup"]]
        if not measured:
            continue
        fields = ["completion_cycles", "stores_per_1000_cycles"]
        if case == LAST_SLOT_COMMIT:
            fields.append("last_slot_commit_cycles")
            for row in measured:
                row["last_slot_commit_cycles"] = row["harts"][0]["timed_cycles"]
        elif case in (EXACT_FULL_FAULT, REPLACE_AND_RETRY):
            for row in measured:
                hart = row["harts"][0]
                row["fault_delivery_cycles"] = hart["fault_delivery_cycles"]
                row["handler_service_cycles"] = hart["handler_service_cycles"]
                row["retry_or_return_cycles"] = hart["retry_or_return_cycles"]
                row["fault_end_to_end_cycles"] = hart["timed_cycles"]
            fields.extend(("fault_delivery_cycles", "handler_service_cycles",
                           "retry_or_return_cycles", "fault_end_to_end_cycles"))
        statistics: dict[str, Any] = {"measured_samples": len(measured)}
        for field_name in fields:
            values = [row[field_name] for row in measured]
            statistics[field_name] = {
                "min": min(values), "median": median(values), "max": max(values),
            }
        statistics["cas_attempts"] = [row["hpm"]["cas_attempts"]
                                      for row in measured]
        statistics["log_faults"] = [row["hpm"]["log_faults"]
                                    for row in measured]
        summary[name] = statistics
    return {
        "schema": "shdlt-buffer-boundary-phase4-stress-performance-v1",
        "timing_note": (
            "fault_entry_cycle is sampled at the start of the C trap handler "
            "after the assembly save prologue; no absolute cycle threshold is applied"),
        "samples": records,
        "summary": summary,
    }


def write_outputs(report: BoundaryReport, output_dir: Path,
                  verdict: dict[str, Any], trace: dict[str, Any] | None,
                  hart_count: int, profile: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = {(row["selection"], row["hart"]): row for row in report.harts}
    samples = []
    for sample in report.samples:
        item: dict[str, Any] = dict(sample)
        # A simulator-side checker can abort between SAMPLE and HART records.
        # Preserve every complete row that was printed instead of making the
        # evidence writer fail a second time while handling that abort.
        item["harts"] = [
            rows[(sample["selection"], hart)]
            for hart in range(hart_count)
            if (sample["selection"], hart) in rows
        ]
        samples.append(item)
    (output_dir / "samples.json").write_text(json.dumps({
        "schema": "shdlt-buffer-boundary-phase4-samples-v1",
        "begin": report.begin, "samples": samples, "end": report.end,
    }, indent=2, sort_keys=True) + "\n")
    (output_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    if trace is not None:
        (output_dir / "trace-report.json").write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n")
    if profile == PROFILE_STRESS and verdict["status"] == "PASS":
        (output_dir / "performance.json").write_text(
            json.dumps(stress_performance(report, hart_count),
                       indent=2, sort_keys=True) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--hart-count", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--profile", type=int,
                        choices=(PROFILE_H1, PROFILE_MULTI, PROFILE_STRESS),
                        required=True)
    parser.add_argument("--tracer", type=Path)
    parser.add_argument("--elf", type=Path)
    args = parser.parse_args(argv)
    if (args.tracer is None) != (args.elf is None):
        parser.error("--tracer and --elf must be supplied together")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    verdict: dict[str, Any] = {
        "schema": "shdlt-buffer-boundary-phase4-verdict-v1", "status": "ERROR",
        "hart_count": args.hart_count, "profile": args.profile,
        "architecture_errors": [], "trace_status": "NOT_REQUESTED",
        "diagnostic_note": "CAS participation and stval/htval are not architecture requirements",
    }
    report = BoundaryReport()
    trace_report = None
    try:
        with args.console.open(encoding="utf-8", errors="replace") as stream:
            report = parse_lines(stream)
        symbols = symbol_values(args.elf) if args.elf else None
        store_pc = (symbols["boundary_mc_store"] - symbols["boundary_mc_guest_start"]
                    if symbols else 0)
        errors = report.architecture_errors(args.hart_count, args.profile, store_pc)
        verdict["architecture_errors"] = errors
        if args.tracer and symbols and errors:
            with args.tracer.open(encoding="utf-8", errors="replace") as stream:
                trace_report = diagnostic_trace_summary(stream)
            verdict["trace_status"] = trace_report["status"]
            verdict["status"] = "FAIL"
        elif errors:
            verdict["status"] = "FAIL"
        elif args.tracer and symbols:
            with args.tracer.open(encoding="utf-8", errors="replace") as stream:
                trace_report = check_trace(
                    stream, symbols["boundary_mc_epoch_start"],
                    symbols["boundary_mc_epoch_end"], args.hart_count, args.profile)
            verdict["trace_status"] = "PASS"
            verdict["status"] = "PASS"
        else:
            verdict["status"] = "PASS"
    except DiagnosticIncomplete as error:
        verdict["status"] = "DIAGNOSTIC_INCOMPLETE"
        verdict["trace_status"] = "DIAGNOSTIC_INCOMPLETE"
        verdict["error"] = str(error)
    except (OSError, ReportError) as error:
        verdict["status"] = "ERROR"
        verdict["error"] = str(error)
    # Shape/firmware validation can fail before the strict epoch-aware trace
    # pass is reached (for example, a simulator-side RVLS abort omits END).
    # Always retain an independent raw lifecycle summary in that case.  This
    # is diagnostic only and deliberately cannot upgrade the verdict.
    if args.tracer is not None and trace_report is None:
        try:
            with args.tracer.open(encoding="utf-8", errors="replace") as stream:
                trace_report = diagnostic_trace_summary(stream)
            verdict["trace_status"] = trace_report["status"]
        except OSError as error:
            verdict["trace_status"] = "DIAGNOSTIC_INCOMPLETE"
            verdict["trace_error"] = str(error)
    write_outputs(report, args.output_dir, verdict, trace_report,
                  args.hart_count, args.profile)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
