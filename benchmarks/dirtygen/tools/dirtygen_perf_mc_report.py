#!/usr/bin/env python3
"""ABI v2 firmware validation and separate HS-epoch trace diagnostics."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


PREFIX = "SHDLT_DIRTYGEN_PERF_MC"
RUNS = 6
ABI_VERSION = 2
MEASURED = 5
CAPACITY = 512
TRACKED_GPA = 0x10000
LOG_BASE = 0x82010000
HART_STRIDE = 0x800000
PTE_BASE = 0x81005080
TRACKED_PHYSICAL = 0x81200000
PTE_DIRTY_FLAGS = 0xD7
WORKLOADS = ("PRIVATE_STRONG", "PRIVATE_WEAK", "SAME_PTE",
             "PREFILLED_SAME_PTE")
BASELINES = ("B0", "B1", "B2", "B3")

SAMPLE_FIELDS = (
    "sample", "hart_count", "workload", "baseline", "warmup",
    "repetition", "total_operations", "max_local_cycles",
    "absolute_start_min", "absolute_end_max", "completion_cycles",
    "distinct_dirty_pages", "expected_dirty_pages", "actual_dirty_pages",
    "expected_log_entries", "actual_log_entries", "expected_pte_bitmap0",
    "expected_pte_bitmap1", "actual_pte_bitmap0", "actual_pte_bitmap1",
    "expected_log_bitmap0", "expected_log_bitmap1", "actual_log_bitmap0",
    "actual_log_bitmap1", "winner_hart",
    "missing", "extra", "duplicates", "tail_writes", "initial_pte_errors", "pte_errors",
    "data_errors", "buffer_errors", "control_errors", "d_transitions",
    "committed_appends", "pte_cas_attempts", "cas_retries", "status",
)
HART_FIELDS = (
    "sample", "hart", "warmup", "repetition", "cycle_start", "cycle_end",
    "workload_cycles", "instret_start", "instret_end", "workload_instret",
    "operations", "idx_before", "idx_after", "idx_delta",
    "expected_idx_delta", "valid_log_entries", "missing", "extra",
    "duplicates", "tail_writes", "tail_slot", "tail_value", "tail_errors",
    "data_errors", "control_errors", "d_transitions", "committed_appends",
    "pte_cas_attempts", "cas_retries", "scause", "sepc", "stval", "htval",
    "done", "status",
)
SAMPLE_STRING_FIELDS = {"workload", "baseline"}


class ReportError(RuntimeError):
    pass


class DiagnosticIncomplete(ReportError):
    """Insufficient/inconsistent implementation evidence, not an ISA verdict."""


def parse_value(value: str) -> int | str:
    try:
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError:
        return value


def parse_fields(tokens: list[str], context: str) -> dict[str, int | str]:
    fields: dict[str, int | str] = {}
    for token in tokens:
        if "=" not in token:
            raise ReportError(f"malformed {context} token {token!r}")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise ReportError(f"invalid or duplicate {context} field {key!r}")
        fields[key] = parse_value(value)
    return fields


def require_fields(record: dict[str, Any], expected: tuple[str, ...], context: str) -> None:
    missing = sorted(set(expected) - set(record))
    extra = sorted(set(record) - set(expected))
    if missing or extra:
        raise ReportError(f"{context} fields missing={missing} extra={extra}")


def integer(record: dict[str, Any], name: str, context: str) -> int:
    value = record.get(name)
    if not isinstance(value, int) or value < 0:
        raise ReportError(f"{context} requires nonnegative integer {name}")
    return value


def operations_per_hart(harts: int, workload: str) -> int:
    if workload == "PRIVATE_STRONG":
        return {1: 128, 2: 64, 4: 32}[harts]
    if workload == "PRIVATE_WEAK":
        return 32
    return 1


def distinct_pages(harts: int, workload: str) -> int:
    if workload == "PRIVATE_STRONG":
        return 128
    if workload == "PRIVATE_WEAK":
        return 32 * harts
    return 1


def shared_pte_workload(workload: str) -> bool:
    return workload in ("SAME_PTE", "PREFILLED_SAME_PTE")


def bitmap(pages: int) -> tuple[int, int]:
    return ((1 << min(pages, 64)) - 1,
            (1 << max(0, pages - 64)) - 1)


@dataclass
class McReport:
    begin: dict[str, int | str] | None = None
    samples: list[dict[str, int | str]] = field(default_factory=list)
    harts: list[dict[str, int | str]] = field(default_factory=list)
    end: dict[str, int | str] | None = None
    record_order: list[tuple[str, int, int | None]] = field(default_factory=list)
    hart_count: int | None = None
    workload: str | None = None
    baseline: str | None = None

    def validate(self, hart_count: int, workload: str, baseline: str) -> None:
        if hart_count not in (1, 2, 4):
            raise ReportError("hart_count must be 1, 2, or 4")
        if workload not in WORKLOADS or baseline not in BASELINES:
            raise ReportError("invalid workload or baseline")
        if workload == "PREFILLED_SAME_PTE" and (hart_count not in (2, 4) or baseline not in ("B2", "B3")):
            raise ReportError("PREFILLED_SAME_PTE requires 2/4 harts and baseline B2/B3")
        if self.begin is None or self.end is None:
            raise ReportError("missing BEGIN or END")
        require_fields(self.begin, ("abi", "hart_count", "workload", "baseline", "samples"), "BEGIN")
        require_fields(self.end, ("samples", "failures", "status"), "END")
        expected_begin = {"abi": ABI_VERSION, "hart_count": hart_count, "workload": workload,
                          "baseline": baseline, "samples": RUNS}
        for name, expected in expected_begin.items():
            if self.begin.get(name) != expected:
                raise ReportError(f"BEGIN {name}={self.begin.get(name)!r}, expected {expected!r}")
        for name, expected in (("samples", RUNS), ("failures", 0), ("status", 0)):
            if integer(self.end, name, "END") != expected:
                raise ReportError(f"END {name} must be {expected}")
        if len(self.samples) != RUNS or len(self.harts) != RUNS * hart_count:
            raise ReportError(f"record count samples={len(self.samples)} harts={len(self.harts)}")
        if self.record_order:
            expected_order = [item for sample in range(RUNS)
                              for item in ([('SAMPLE', sample, None)] +
                                           [('HART', sample, hart) for hart in range(hart_count)])]
            if self.record_order != expected_order:
                raise ReportError("SAMPLE/HART record order does not match firmware ABI")

        by_sample: dict[int, list[dict[str, int | str]]] = {}
        for ordinal, record in enumerate(self.harts):
            require_fields(record, HART_FIELDS, f"HART {ordinal}")
            for name in HART_FIELDS:
                integer(record, name, f"HART {ordinal}")
            by_sample.setdefault(int(record["sample"]), []).append(record)

        ops = operations_per_hart(hart_count, workload)
        distinct = distinct_pages(hart_count, workload)
        initial_d = baseline in ("B0", "B1")
        expected_dirty = 128 if initial_d else distinct
        expected_logs = distinct if baseline == "B3" else 0
        expected_bits = bitmap(expected_dirty)
        expected_log_bits = bitmap(expected_logs)
        for ordinal, sample in enumerate(self.samples):
            require_fields(sample, SAMPLE_FIELDS, f"SAMPLE {ordinal}")
            for name in SAMPLE_FIELDS:
                if name not in SAMPLE_STRING_FIELDS:
                    integer(sample, name, f"SAMPLE {ordinal}")
            expected_warmup = int(ordinal == 0)
            expected_rep = 0 if ordinal == 0 else ordinal - 1
            fixed = {
                "sample": ordinal, "hart_count": hart_count,
                "workload": workload, "baseline": baseline,
                "warmup": expected_warmup, "repetition": expected_rep,
                "total_operations": ops * hart_count,
                "distinct_dirty_pages": distinct,
                "expected_dirty_pages": expected_dirty,
                "actual_dirty_pages": expected_dirty,
                "expected_log_entries": expected_logs,
                "actual_log_entries": expected_logs,
                "expected_pte_bitmap0": expected_bits[0],
                "expected_pte_bitmap1": expected_bits[1],
                "actual_pte_bitmap0": expected_bits[0],
                "actual_pte_bitmap1": expected_bits[1],
                "expected_log_bitmap0": expected_log_bits[0],
                "expected_log_bitmap1": expected_log_bits[1],
                "actual_log_bitmap0": expected_log_bits[0],
                "actual_log_bitmap1": expected_log_bits[1],
            }
            for name, expected in fixed.items():
                if sample[name] != expected:
                    raise ReportError(f"sample {ordinal} {name}={sample[name]!r}, expected {expected!r}")
            for name in ("missing", "extra", "duplicates", "initial_pte_errors",
                         "pte_errors", "data_errors", "buffer_errors",
                         "control_errors", "status"):
                if integer(sample, name, f"sample {ordinal}") != 0:
                    raise ReportError(f"sample {ordinal} {name} must be zero")
            winner = integer(sample, "winner_hart", f"sample {ordinal}")
            if not initial_d and shared_pte_workload(workload):
                if winner >= hart_count:
                    raise ReportError(f"sample {ordinal} winner_hart is invalid")
            elif winner != (1 << 64) - 1:
                raise ReportError(f"sample {ordinal} unexpectedly names a winner")

            records = by_sample.get(ordinal, [])
            if len(records) != hart_count or sorted(int(r["hart"]) for r in records) != list(range(hart_count)):
                raise ReportError(f"sample {ordinal} has missing or duplicate hart records")
            starts: list[int] = []
            ends: list[int] = []
            cycles: list[int] = []
            idx_sum = 0
            hpm = [0, 0, 0, 0]
            hpm_winners: list[int] = []
            for record in sorted(records, key=lambda item: int(item["hart"])):
                hart = int(record["hart"])
                for name, expected in (("sample", ordinal), ("hart", hart),
                                       ("warmup", expected_warmup),
                                       ("repetition", expected_rep),
                                       ("operations", ops), ("idx_before", 0),
                                       ("scause", 10), ("stval", 0), ("htval", 0),
                                       ("done", 1), ("missing", 0), ("extra", 0),
                                       ("duplicates", 0), ("tail_errors", 0),
                                       ("data_errors", 0), ("control_errors", 0),
                                       ("status", 0)):
                    if integer(record, name, f"sample {ordinal} hart {hart}") != expected:
                        raise ReportError(f"sample {ordinal} hart {hart} {name} must be {expected}")
                start = int(record["cycle_start"]); end = int(record["cycle_end"])
                istart = int(record["instret_start"]); iend = int(record["instret_end"])
                if end < start or int(record["workload_cycles"]) != end - start:
                    raise ReportError(f"sample {ordinal} hart {hart} cycle delta mismatch")
                if iend < istart or int(record["workload_instret"]) != iend - istart:
                    raise ReportError(f"sample {ordinal} hart {hart} instret delta mismatch")
                if int(record["workload_instret"]) != 5 * ops + 5:
                    raise ReportError(f"sample {ordinal} hart {hart} ABI v2 instret must be 5*N+5")
                delta = int(record["idx_after"]) - int(record["idx_before"])
                if delta < 0 or int(record["idx_delta"]) != delta:
                    raise ReportError(f"sample {ordinal} hart {hart} INDEX delta mismatch")
                if int(record["expected_idx_delta"]) != delta:
                    raise ReportError(f"sample {ordinal} hart {hart} expected INDEX mismatch")
                if int(record["valid_log_entries"]) != delta:
                    raise ReportError(f"sample {ordinal} hart {hart} valid log mismatch")
                if baseline != "B3" and delta != 0:
                    raise ReportError(f"sample {ordinal} hart {hart} unexpected log")
                if baseline == "B3" and not shared_pte_workload(workload) and delta != ops:
                    raise ReportError(f"sample {ordinal} hart {hart} private log count mismatch")
                tail_writes = int(record["tail_writes"])
                if shared_pte_workload(workload) and baseline == "B3":
                    if tail_writes not in (0, 1):
                        raise ReportError(f"sample {ordinal} hart {hart} invalid tail count")
                    if tail_writes and (int(record["tail_slot"]) != 0 or int(record["tail_value"]) != TRACKED_GPA):
                        raise ReportError(f"sample {ordinal} hart {hart} invalid tail write")
                elif tail_writes != 0:
                    raise ReportError(f"sample {ordinal} hart {hart} unexpected tail write")
                starts.append(start); ends.append(end); cycles.append(end - start)
                idx_sum += delta
                for index, name in enumerate(("d_transitions", "committed_appends", "pte_cas_attempts", "cas_retries")):
                    hpm[index] += int(record[name])
                if shared_pte_workload(workload) and not initial_d:
                    attempt = int(record["pte_cas_attempts"])
                    retry = int(record["cas_retries"])
                    dirty = int(record["d_transitions"])
                    append = int(record["committed_appends"])
                    if attempt not in (0, 1) or retry not in (0, 1) or dirty not in (0, 1):
                        raise ReportError(f"sample {ordinal} hart {hart} prefilled counter range mismatch")
                    if dirty:
                        hpm_winners.append(hart)
                        valid = attempt == 1 and retry == 0
                    elif retry:
                        valid = attempt == 1
                    else:
                        valid = attempt == 0
                    if not valid or append != int(dirty != 0 and baseline == "B3"):
                        raise ReportError(f"sample {ordinal} hart {hart} prefilled role mismatch")
                    if baseline == "B3":
                        expected_tail = retry
                        if delta != dirty or tail_writes != expected_tail:
                            raise ReportError(f"sample {ordinal} hart {hart} prefilled log role mismatch")
                    elif delta != 0 or tail_writes != 0:
                        raise ReportError(f"sample {ordinal} hart {hart} prefilled B2 log mismatch")
            if baseline == "B3" and shared_pte_workload(workload) and idx_sum != 1:
                raise ReportError(f"sample {ordinal} shared-PTE INDEX sum must be one")
            if baseline == "B3" and shared_pte_workload(workload):
                observed_winner = next(int(record["hart"]) for record in records if int(record["idx_delta"]) == 1)
                if int(sample["winner_hart"]) != observed_winner:
                    raise ReportError(f"sample {ordinal} winner_hart does not match INDEX owner")
            if baseline != "B3" and idx_sum != 0:
                raise ReportError(f"sample {ordinal} INDEX sum must be zero")
            if shared_pte_workload(workload) and not initial_d:
                if len(hpm_winners) != 1 or int(sample["winner_hart"]) != hpm_winners[0]:
                    raise ReportError(f"sample {ordinal} prefilled winner classification mismatch")
            if int(sample["tail_writes"]) != sum(int(record["tail_writes"]) for record in records):
                raise ReportError(f"sample {ordinal} tail write aggregate mismatch")
            if int(sample["max_local_cycles"]) != max(cycles):
                raise ReportError(f"sample {ordinal} max_local_cycles mismatch")
            if int(sample["absolute_start_min"]) != min(starts) or int(sample["absolute_end_max"]) != max(ends):
                raise ReportError(f"sample {ordinal} absolute range mismatch")
            if int(sample["completion_cycles"]) != max(cycles):
                raise ReportError(f"sample {ordinal} completion cycle mismatch")
            names = ("d_transitions", "committed_appends", "pte_cas_attempts", "cas_retries")
            if tuple(int(sample[name]) for name in names) != tuple(hpm):
                raise ReportError(f"sample {ordinal} HPM aggregate mismatch")
            expected_d = 0 if initial_d else distinct
            expected_append = expected_d if baseline == "B3" else 0
            if hpm[0] != expected_d or hpm[1] != expected_append:
                raise ReportError(f"sample {ordinal} D/append HPM mismatch")
            if initial_d and (hpm[2] or hpm[3]):
                raise ReportError(f"sample {ordinal} unexpected PTE HPM")
            if not initial_d and not shared_pte_workload(workload) and (hpm[2] != distinct or hpm[3] != 0):
                raise ReportError(f"sample {ordinal} private CAS HPM mismatch")
            if not initial_d and workload == "SAME_PTE" and not (1 <= hpm[2] <= hart_count and hpm[3] == hpm[2] - 1):
                raise ReportError(f"sample {ordinal} SAME_PTE CAS HPM mismatch")
            if workload == "PREFILLED_SAME_PTE" and not (
                    1 <= hpm[2] <= hart_count and hpm[3] == hpm[2] - 1):
                raise ReportError(f"sample {ordinal} PREFILLED_SAME_PTE aggregate HPM mismatch")
        if sorted(by_sample) != list(range(RUNS)):
            raise ReportError("unexpected HART sample ids")
        self.hart_count, self.workload, self.baseline = hart_count, workload, baseline


def parse_lines(stream: TextIO) -> McReport:
    report = McReport()
    for line in stream:
        start = line.find(PREFIX)
        if start < 0:
            continue
        tokens = line[start:].strip().split()
        tag = tokens[0]
        fields = parse_fields(tokens[1:], tag)
        if tag == PREFIX + "_BEGIN":
            if report.begin is not None: raise ReportError("duplicate BEGIN")
            report.begin = fields
        elif tag == PREFIX + "_SAMPLE":
            report.samples.append(fields)
            report.record_order.append(("SAMPLE", integer(fields, "sample", "SAMPLE"), None))
        elif tag == PREFIX + "_HART":
            report.harts.append(fields)
            report.record_order.append(("HART", integer(fields, "sample", "HART"), integer(fields, "hart", "HART")))
        elif tag == PREFIX + "_END":
            if report.end is not None: raise ReportError("duplicate END")
            report.end = fields
        else: raise ReportError(f"unknown record {tag}")
    return report


def symbol_values(elf: Path) -> dict[str, int]:
    try:
        output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReportError(f"cannot inspect ELF symbols: {error}") from error
    values: dict[str, int] = {}
    wanted = {"dirtygen_perf_mc_guest_start", "dirtygen_perf_mc_timed_start", "dirtygen_perf_mc_timed_end",
              "dirtygen_perf_mc_epoch_start", "dirtygen_perf_mc_epoch_end"}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted:
            values[parts[2]] = int(parts[0], 16)
    if set(values) != wanted:
        raise ReportError(f"ELF missing timed-window symbols: {sorted(wanted - set(values))}")
    return values


PHYSICAL_RE = re.compile(r"^rv mmu physical-store (\d+) (\d+) (\d+) (\d+) ([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) (\d+) (pending|committed|superseded|error)$")
STORE_RE = re.compile(r"^rv mmu store (\d+) ([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) (\d+)$")
COMMIT_RE = re.compile(r"^rv commit (\d+) ([0-9a-fA-F]+) ")


def check_trace(lines: TextIO, report: McReport, start_pc: int, end_pc: int,
                epoch_start_pc: int, epoch_end_pc: int) -> dict[str, Any]:
    if report.hart_count is None or report.workload is None or report.baseline is None:
        raise ReportError("report must be validated before trace checking")
    harts = report.hart_count
    active: list[int | None] = [None] * harts
    next_sample = [0] * harts
    timed: list[int | None] = [None] * harts
    timed_count = [0] * harts
    outside_timed_events = 0
    lifecycle: dict[tuple[int, int, int], dict[str, Any]] = {}
    stores: list[list[list[tuple[int, int, int]]]] = [[[] for _ in range(harts)] for _ in range(RUNS)]
    bad_markers: list[str] = []
    for raw in lines:
        line = raw.strip()
        lower = line.lower()
        if any(marker in lower for marker in ("rvls mismatch", "attribution error", "failure context", "residual mmustorequeue", "timeout")):
            bad_markers.append(line)
        match = COMMIT_RE.match(line)
        if match:
            hart, pc = int(match.group(1)), int(match.group(2), 16)
            if hart < harts and pc == epoch_start_pc:
                if active[hart] is not None or next_sample[hart] >= RUNS:
                    raise DiagnosticIncomplete(f"invalid HS epoch start hart={hart}")
                active[hart] = next_sample[hart]; next_sample[hart] += 1
            elif hart < harts and pc == epoch_end_pc:
                if active[hart] is None:
                    raise DiagnosticIncomplete(f"HS epoch end without start hart={hart}")
                active[hart] = None
            elif hart < harts and pc == start_pc:
                if timed[hart] is not None or active[hart] is None:
                    raise DiagnosticIncomplete(f"invalid timed start hart={hart}")
                timed[hart] = active[hart]
                timed_count[hart] += 1
            elif hart < harts and pc == end_pc:
                if timed[hart] is None:
                    raise DiagnosticIncomplete(f"timed end without start hart={hart}")
                timed[hart] = None
            continue
        match = PHYSICAL_RE.match(line)
        if match:
            hart, source, attempt, cycle = map(int, match.group(1, 2, 3, 4))
            address, length, data, error, state = int(match.group(5), 16), int(match.group(6)), int(match.group(7), 16), int(match.group(8)), match.group(9)
            key = (hart, source, attempt)
            if hart >= harts or (active[hart] is None and key not in lifecycle):
                raise DiagnosticIncomplete(f"unattributable physical lifecycle outside HS epoch: {line}")
            if timed[hart] is None:
                outside_timed_events += 1
            entry = lifecycle.setdefault(key, {"hart": hart, "sample": active[hart], "source": source, "attempt": attempt, "cycle": cycle, "address": address, "length": length, "data": data, "error": error, "states": []})
            if any(entry[name] != value for name, value in (("address", address), ("length", length), ("data", data), ("error", error))):
                raise ReportError(f"lifecycle context changed for {key}")
            entry["states"].append(state)
            continue
        match = STORE_RE.match(line)
        if match:
            hart = int(match.group(1)); item = (int(match.group(2), 16), int(match.group(3)), int(match.group(4), 16), int(match.group(5)))
            if hart >= harts or active[hart] is None:
                raise DiagnosticIncomplete(f"unattributable MMU store outside HS epoch: {line}")
            if timed[hart] is None:
                outside_timed_events += 1
            stores[active[hart]][hart].append(item)
        elif line.startswith(("rv mmu physical-store", "rv mmu store")):
            raise DiagnosticIncomplete(f"malformed MMU record: {line}")
    if bad_markers:
        raise ReportError(f"RVLS failure marker: {bad_markers[0]}")
    if (any(item is not None for item in active + timed) or next_sample != [RUNS] * harts or
            timed_count != [RUNS] * harts):
        raise DiagnosticIncomplete(f"incomplete HS epochs/timed windows active={active} epochs={next_sample} timed={timed_count}")

    per_sample: list[dict[str, Any]] = []
    for sample in range(RUNS):
        events = [entry for entry in lifecycle.values() if entry["sample"] == sample]
        committed = superseded = errors = 0
        expected_arch: list[tuple[int, tuple[int, int, int, int]]] = []
        superseded_items: list[tuple[int, tuple[int, int, int, int]]] = []
        for entry in events:
            states = entry["states"]
            log_start = LOG_BASE + entry["hart"] * HART_STRIDE
            if (entry["length"] != 8 or entry["address"] < log_start or
                    entry["address"] >= log_start + CAPACITY * 8 or
                    (entry["address"] - log_start) % 8 or entry["error"] != 0 or
                    entry["data"] < TRACKED_GPA or entry["data"] >= TRACKED_GPA + 128 * 4096 or
                    entry["data"] % 4096):
                raise ReportError(f"sample {sample} malformed physical logger event")
            page = (entry["data"] - TRACKED_GPA) // 4096
            if shared_pte_workload(report.workload):
                expected_page = page == 0
            else:
                per_hart = operations_per_hart(harts, report.workload)
                expected_page = entry["hart"] * per_hart <= page < (entry["hart"] + 1) * per_hart
            if not expected_page:
                raise ReportError(f"sample {sample} physical logger data is outside the hart workload")
            if states == ["pending", "committed"]:
                committed += 1; final = "committed"
            elif states == ["pending", "superseded"]:
                superseded += 1; final = "superseded"
            elif states == ["error"]:
                errors += 1; final = "error"
            else:
                raise ReportError(f"open/duplicate lifecycle {entry['hart'], entry['source'], entry['attempt']} states={states}")
            item = (entry["address"], entry["length"], entry["data"], entry["error"])
            if final in ("committed", "error"): expected_arch.append((entry["hart"], item))
            else: superseded_items.append((entry["hart"], item))
        expected_attempts = 0
        expected_committed = 0
        expected_store_count = 0
        distinct = distinct_pages(harts, report.workload)
        if report.baseline == "B2": expected_store_count = distinct
        elif report.baseline == "B3":
            expected_committed = distinct
            expected_store_count = 2 * distinct
            if not shared_pte_workload(report.workload): expected_attempts = distinct
            elif report.workload == "PREFILLED_SAME_PTE":
                rows = [row for row in report.harts if int(row["sample"]) == sample]
                expected_attempts = sum(int(row["pte_cas_attempts"]) for row in rows)
        if report.workload == "PREFILLED_SAME_PTE" and report.baseline == "B3":
            if (len(events) != expected_attempts or committed != 1 or
                    superseded != expected_attempts - 1):
                raise ReportError(f"sample {sample} PREFILLED_SAME_PTE lifecycle counts invalid")
        elif report.workload == "SAME_PTE" and report.baseline == "B3":
            expected_attempts = sum(int(row["pte_cas_attempts"]) for row in report.harts if int(row["sample"]) == sample)
            if len(events) != expected_attempts or committed != 1 or superseded != len(events) - 1:
                raise ReportError(f"sample {sample} SAME_PTE lifecycle counts invalid")
        elif len(events) != expected_attempts or committed != expected_committed or superseded or errors:
            raise ReportError(f"sample {sample} lifecycle counts invalid")
        arch_count = sum(len(items) for items in stores[sample])
        if arch_count != expected_store_count:
            raise ReportError(f"sample {sample} architectural store count {arch_count}, expected {expected_store_count}")
        remaining = [(hart, item) for hart, items in enumerate(stores[sample]) for item in items]
        for wanted in expected_arch:
            if wanted not in remaining: raise ReportError(f"sample {sample} committed/error logger store absent from architectural stream")
            remaining.remove(wanted)
        for unwanted in superseded_items:
            if unwanted in [(hart, item) for hart, items in enumerate(stores[sample]) for item in items]:
                raise ReportError(f"sample {sample} superseded store entered architectural stream")

        records = {int(row["hart"]): row for row in report.harts if int(row["sample"]) == sample}
        pte_pages: set[int] = set()
        for owner, item in remaining:
            address, length, data, error = item
            if length != 8 or error != 0 or address < PTE_BASE or address >= PTE_BASE + 128 * 8 or (address - PTE_BASE) % 8:
                raise ReportError(f"sample {sample} malformed architectural PTE store {item}")
            page = (address - PTE_BASE) // 8
            ops = operations_per_hart(harts, report.workload)
            if shared_pte_workload(report.workload):
                if page != 0 or int(records[owner]["d_transitions"]) != 1:
                    raise ReportError(f"sample {sample} shared PTE update/HPM owner mismatch")
            elif not owner * ops <= page < (owner + 1) * ops:
                raise ReportError(f"sample {sample} PTE update outside hart workload")
            expected_data = (((TRACKED_PHYSICAL + page * 4096) >> 12) << 10) | PTE_DIRTY_FLAGS
            if data != expected_data or page in pte_pages:
                raise ReportError(f"sample {sample} wrong or duplicate architectural PTE store {item}")
            pte_pages.add(page)
        if len(pte_pages) != (distinct if report.baseline in ("B2", "B3") else 0):
            raise ReportError(f"sample {sample} architectural PTE page set is incomplete")

        records = {int(row["hart"]): row for row in report.harts if int(row["sample"]) == sample}
        for hart, row in records.items():
            hart_events = [entry for entry in events if entry["hart"] == hart]
            hart_committed = sum(entry["states"] == ["pending", "committed"] for entry in hart_events)
            hart_superseded = sum(entry["states"] == ["pending", "superseded"] for entry in hart_events)
            if report.baseline == "B3" and not shared_pte_workload(report.workload):
                if len(hart_events) != int(row["operations"]) or hart_committed != int(row["idx_delta"]) or hart_superseded:
                    raise ReportError(f"sample {sample} hart {hart} private lifecycle count mismatch")
            elif shared_pte_workload(report.workload) and report.baseline == "B3":
                if len(hart_events) != int(row["pte_cas_attempts"]):
                    raise ReportError(f"sample {sample} hart {hart} shared-PTE lifecycle/HPM mismatch")
                if hart_committed != int(row["idx_delta"]) or hart_superseded != int(row["tail_writes"]):
                    raise ReportError(f"sample {sample} hart {hart} shared-PTE lifecycle/buffer mismatch")
            elif hart_events:
                raise ReportError(f"sample {sample} hart {hart} unexpected logger lifecycle")
            if int(row["tail_writes"]) == 0: continue
            wanted = (hart, (LOG_BASE + hart * HART_STRIDE + int(row["tail_slot"]) * 8,
                             8, int(row["tail_value"]), 0))
            if wanted not in superseded_items:
                raise ReportError(f"sample {sample} hart {hart} tail write lacks matching superseded lifecycle")
        tail_items = {
            (hart, (LOG_BASE + hart * HART_STRIDE + int(row["tail_slot"]) * 8,
                    8, int(row["tail_value"]), 0))
            for hart, row in records.items() if int(row["tail_writes"]) != 0
        }
        for item in superseded_items:
            if item not in tail_items:
                raise ReportError(f"sample {sample} superseded lifecycle lacks matching physical tail write")
        records = {int(row["hart"]): row for row in report.harts
                   if int(row["sample"]) == sample}
        attempting = sorted(hart for hart, row in records.items()
                            if int(row["pte_cas_attempts"]) != 0)
        losers = sorted(hart for hart, row in records.items()
                        if int(row["cas_retries"]) != 0)
        winners = sorted(hart for hart, row in records.items()
                         if int(row["d_transitions"]) != 0)
        observers = sorted(set(range(harts)) - set(attempting))
        per_sample.append({
            "sample": sample,
            "cas_attempts": sum(int(row["pte_cas_attempts"])
                                for row in records.values()),
            "attempting_harts": attempting,
            "winner_hart": winners[0] if len(winners) == 1 else None,
            "loser_harts": losers,
            "observer_harts": observers,
            "physical_attempts": len(events), "committed": committed,
            "superseded": superseded, "errors": errors,
            "architectural_stores": arch_count,
            "append_amplification": (len(events) / committed
                                     if committed else None),
            "superseded_ratio": (superseded / len(events)
                                 if events else None),
        })
    lifecycle_rows = []
    for entry in sorted(lifecycle.values(), key=lambda item: (item["sample"], item["hart"], item["source"], item["attempt"])):
        lifecycle_rows.append({
            "sample": entry["sample"], "hart": entry["hart"],
            "source": entry["source"], "attempt": entry["attempt"],
            "observed_cycle": entry["cycle"],
            "address": f"0x{entry['address']:016x}", "length": entry["length"],
            "data": f"0x{entry['data']:016x}", "error": entry["error"],
            "states": entry["states"], "terminal_state": entry["states"][-1],
        })
    return {"schema": "shdlt-dirtygen-perf-mc-trace-report-v2", "status": "PASS",
            "sample_segmentation": "per-hart HS epoch; attempt identity owns terminal events",
            "outside_timed_events": outside_timed_events,
            "samples": per_sample, "lifecycles": lifecycle_rows,
            "totals": {name: sum(item[name] for item in per_sample) for name in ("physical_attempts", "committed", "superseded", "errors", "architectural_stores")}}


def documents(report: McReport) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    harts_by_sample = {sample: [row for row in report.harts if int(row["sample"]) == sample] for sample in range(RUNS)}
    samples = []
    for sample in report.samples:
        item = dict(sample); item["harts"] = sorted(harts_by_sample[int(sample["sample"])], key=lambda row: int(row["hart"])); samples.append(item)
        for hart in item["harts"]:
            rows.append({**{f"sample_{key}": value for key, value in sample.items()}, **{f"hart_{key}": value for key, value in hart.items()}})
    return ({"schema": "shdlt-dirtygen-perf-mc-samples-v2", "begin": report.begin, "samples": samples, "end": report.end}, rows)


def write_outputs(report: McReport, output_dir: Path, trace_report: dict[str, Any] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    document, rows = documents(report)
    (output_dir / "samples.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    with (output_dir / "samples.csv").open("w", newline="") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    if trace_report is not None:
        (output_dir / "trace-report.json").write_text(json.dumps(trace_report, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console", type=Path)
    parser.add_argument("--hart-count", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--workload", choices=("private-strong", "private-weak", "same-pte", "prefilled-same-pte"), required=True)
    parser.add_argument("--baseline", choices=BASELINES, required=True)
    parser.add_argument("--tracer", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if (args.tracer is None) != (args.elf is None): parser.error("--tracer and --elf must be supplied together")
    try:
        with args.console.open(errors="replace") as stream: report = parse_lines(stream)
        workload = args.workload.replace("-", "_").upper()
        report.validate(args.hart_count, workload, args.baseline)
        trace_report = None
        if args.tracer:
            symbols = symbol_values(args.elf)
            guest = symbols["dirtygen_perf_mc_guest_start"]
            try:
                with args.tracer.open(errors="replace") as stream:
                    trace_report = check_trace(stream, report, symbols["dirtygen_perf_mc_timed_start"] - guest,
                                               symbols["dirtygen_perf_mc_timed_end"] - guest,
                                               symbols["dirtygen_perf_mc_epoch_start"], symbols["dirtygen_perf_mc_epoch_end"])
            except ReportError as error:
                trace_report = {"schema": "shdlt-dirtygen-perf-mc-trace-report-v2",
                                "status": "INCOMPLETE", "error": str(error),
                                "architecture_status": "PASS"}
                if args.output_dir: write_outputs(report, args.output_dir, trace_report)
                print(f"MC firmware PASS; implementation diagnostic incomplete: {error}", file=sys.stderr)
                return 2
        if args.output_dir: write_outputs(report, args.output_dir, trace_report)
        print(f"dirtygen perf mc: PASS harts={args.hart_count} workload={workload} baseline={args.baseline} samples=6 measured=5")
        return 0
    except (OSError, ReportError, ValueError) as error:
        print(f"dirtygen perf mc report error: {error}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
