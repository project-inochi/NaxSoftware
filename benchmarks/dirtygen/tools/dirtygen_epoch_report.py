#!/usr/bin/env python3
"""Validate dirty-epoch ABI v1 output and its physical MMU trace."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, TextIO


RUNS = 6
MEASURED = 5
ABI_VERSION = 1
TRACKED_PAGES = 128
TRACKED_GPA = 0x10000
PAGE_SIZE = 4096
LOG_CAPACITY = 512
SINGLE_PREFIX = "SHDLT_DIRTYGEN_PERF_EPOCH"
MC_PREFIX = "SHDLT_DIRTYGEN_PERF_MC_EPOCH"
BACKENDS = {"pte-scan-serial": ("PTE_SCAN_SERIAL", "B2", 0),
            "shdlt-log": ("SHDLT_LOG", "B3", 1)}
SINGLE_WORKLOADS = {"unique": "UNIQUE", "repeat": "REPEAT"}
MC_WORKLOADS = {"private-strong": "PRIVATE_STRONG",
                "private-weak": "PRIVATE_WEAK", "same-pte": "SAME_PTE"}

SINGLE_BEGIN_FIELDS = (
    "abi", "harvest_backend", "runtime_mode", "pattern", "hart_count",
    "tracked_pages", "dirty_pages", "operations", "samples",
)
SINGLE_SAMPLE_FIELDS = (
    "sample", "warmup", "repetition", "pattern", "harvest_backend",
    "runtime_mode", "hart_count", "tracked_pages", "dirty_pages",
    "operations", "workload_cycle_start", "workload_cycle_end",
    "workload_cycles", "workload_instret", "quiesce_cycles",
    "discover_cycles", "normalize_cycles", "clear_d_cycles",
    "hfence_cycles", "backend_reset_cycles", "resume_cycles",
    "harvest_cycles", "pause_cycles", "epoch_cycles",
    "pte_entries_scanned", "raw_log_entries", "committed_log_entries",
    "canonical_dirty_pages", "missing", "extra", "duplicates",
    "expected_bitmap0", "expected_bitmap1", "canonical_bitmap0",
    "canonical_bitmap1", "idx_before", "idx_after", "idx_reset",
    "hfence_acks", "reset_acks", "rearm_pages", "invalid_log_entries",
    "reserved_bit_errors", "index_errors", "initial_pte_errors",
    "pte_errors", "data_errors", "control_errors", "rearm_errors",
    "timing_errors", "actual_cause", "status",
)
MC_BEGIN_FIELDS = (
    "abi", "hart_count", "workload", "harvest_backend", "runtime_mode",
    "tracked_pages", "samples",
)
MC_SAMPLE_FIELDS = (
    "sample", "warmup", "repetition", "hart_count", "workload",
    "harvest_backend", "runtime_mode", "tracked_pages", "total_operations",
    "distinct_dirty_pages", "workload_cycles", "hart0_cycle_start",
    "quiesce_boundary", "quiesce_cycles", "discover_cycles",
    "normalize_cycles", "clear_d_cycles", "hfence_cycles",
    "backend_reset_cycles", "resume_cycles", "harvest_cycles",
    "pause_cycles", "epoch_cycles", "pte_entries_scanned",
    "raw_log_entries", "committed_log_entries", "canonical_dirty_pages",
    "missing", "extra", "duplicates", "expected_bitmap0",
    "expected_bitmap1", "canonical_bitmap0", "canonical_bitmap1",
    "idx_before_total", "idx_after_total", "idx_reset_total",
    "hfence_acks", "reset_acks", "rearm_pages", "invalid_log_entries",
    "reserved_bit_errors", "index_errors", "initial_pte_errors",
    "pte_errors", "data_errors", "control_errors", "rearm_errors",
    "timing_errors", "sync_errors", "d_transitions", "committed_appends",
    "pte_cas_attempts", "cas_retries", "status",
)
MC_HART_FIELDS = (
    "sample", "hart", "warmup", "repetition", "operations",
    "cycle_start", "cycle_end", "workload_cycles", "instret_start",
    "instret_end", "workload_instret", "idx_before", "idx_after",
    "idx_reset", "d_transitions", "committed_appends", "pte_cas_attempts",
    "cas_retries", "scause", "sepc", "stval", "htval", "hfence_done",
    "reset_done", "done", "control_errors", "status",
)
END_FIELDS = ("samples", "failures", "status")
STRING_FIELDS = {"pattern", "workload", "harvest_backend", "runtime_mode"}
ZERO_SAMPLE_FIELDS = (
    "missing", "extra", "duplicates", "invalid_log_entries",
    "reserved_bit_errors", "index_errors", "initial_pte_errors",
    "pte_errors", "data_errors", "control_errors", "rearm_errors",
    "timing_errors", "status",
)

PHYSICAL_RE = re.compile(
    r"^rv mmu physical-store (\d+) (\d+) (\d+) (\d+) "
    r"([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) (\d+) "
    r"(pending|committed|superseded|error)$")
STORE_RE = re.compile(
    r"^rv mmu store (\d+) ([0-9a-fA-F]+) (\d+) "
    r"([0-9a-fA-F]+) (\d+)$")
PTE_CAS_RE = re.compile(
    r"^rv mmu pte-cas (\d+) (\d+) (\d+) (\d+) "
    r"([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) "
    r"([0-9a-fA-F]+) ([0-9a-fA-F]+) (\d+) ([01])$")
COMMIT_RE = re.compile(r"^rv commit (\d+) ([0-9a-fA-F]+) ")
BAD_MARKERS = ("rvls mismatch", "attribution error", "failure context",
               "residual mmustorequeue", "residual pte cas",
               "missing pte cas reservation", "host_timeout", "timeout")


class ReportError(RuntimeError):
    pass


class DiagnosticIncomplete(ReportError):
    """Trace evidence is incomplete; this is not an ISA verdict."""


def parse_value(value: str) -> int | str:
    try:
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError:
        return value


def parse_fields(tokens: list[str], context: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            raise ReportError(f"malformed {context} token {token!r}")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise ReportError(f"invalid or duplicate {context} field {key!r}")
        fields[key] = parse_value(value)
    return fields


def require_fields(record: dict[str, Any], expected: Iterable[str], context: str) -> None:
    wanted = set(expected)
    missing, extra = sorted(wanted - set(record)), sorted(set(record) - wanted)
    if missing or extra:
        raise ReportError(f"{context} fields missing={missing} extra={extra}")


def integer(record: dict[str, Any], name: str, context: str) -> int:
    value = record.get(name)
    if not isinstance(value, int) or value < 0:
        raise ReportError(f"{context} requires nonnegative integer {name}")
    return value


def bitmap(pages: int) -> tuple[int, int]:
    return ((1 << min(pages, 64)) - 1,
            (1 << max(0, pages - 64)) - 1)


def mc_operations(harts: int, workload: str) -> int:
    if workload == "PRIVATE_STRONG":
        return {1: 128, 2: 64, 4: 32}[harts]
    if workload == "PRIVATE_WEAK":
        return 32
    return 1


def mc_dirty_pages(harts: int, workload: str) -> int:
    if workload == "PRIVATE_STRONG":
        return 128
    if workload == "PRIVATE_WEAK":
        return 32 * harts
    return 1


def parse_console(stream: TextIO, profile: str) -> dict[str, Any]:
    prefix = SINGLE_PREFIX if profile == "single" else MC_PREFIX
    document: dict[str, Any] = {"begin": None, "samples": [], "harts": [],
                                "end": None, "order": []}
    for raw in stream:
        start = raw.find(prefix)
        if start < 0:
            continue
        tokens = raw[start:].strip().split()
        tag, fields = tokens[0], parse_fields(tokens[1:], tokens[0])
        if tag == prefix + "_BEGIN":
            if document["begin"] is not None or document["order"] or document["end"] is not None:
                raise ReportError("duplicate BEGIN")
            document["begin"] = fields
        elif tag == prefix + "_SAMPLE":
            if document["begin"] is None or document["end"] is not None:
                raise ReportError("SAMPLE outside BEGIN/END")
            document["samples"].append(fields)
            document["order"].append(("sample", integer(fields, "sample", tag), None))
        elif profile == "mc" and tag == prefix + "_HART":
            if document["begin"] is None or document["end"] is not None:
                raise ReportError("HART outside BEGIN/END")
            document["harts"].append(fields)
            document["order"].append(("hart", integer(fields, "sample", tag),
                                      integer(fields, "hart", tag)))
        elif tag == prefix + "_END":
            if document["begin"] is None or document["end"] is not None:
                raise ReportError("duplicate END")
            document["end"] = fields
        elif tag == prefix + "_ERROR":
            raise ReportError(f"firmware emitted {tag}: {fields}")
        else:
            raise ReportError(f"unknown epoch record {tag}")
    return document


def _fixed_sample(record: dict[str, Any], ordinal: int, backend: str,
                  common: dict[str, Any]) -> None:
    expected = {"sample": ordinal, "warmup": int(ordinal == 0),
                "repetition": 0 if ordinal == 0 else ordinal - 1,
                "harvest_backend": BACKENDS[backend][0],
                "runtime_mode": BACKENDS[backend][1], "tracked_pages": 128,
                **common}
    for name, value in expected.items():
        if record.get(name) != value:
            raise ReportError(
                f"sample {ordinal} {name}={record.get(name)!r}, expected {value!r}")
    for name in ZERO_SAMPLE_FIELDS:
        if integer(record, name, f"sample {ordinal}") != 0:
            raise ReportError(f"sample {ordinal} {name} must be zero")
    if (integer(record, "canonical_bitmap0", f"sample {ordinal}") !=
            integer(record, "expected_bitmap0", f"sample {ordinal}") or
            integer(record, "canonical_bitmap1", f"sample {ordinal}") !=
            integer(record, "expected_bitmap1", f"sample {ordinal}")):
        raise ReportError(f"sample {ordinal} canonical bitmap differs from oracle")
    canonical = (integer(record, "canonical_bitmap0", f"sample {ordinal}").bit_count() +
                 integer(record, "canonical_bitmap1", f"sample {ordinal}").bit_count())
    for name in ("canonical_dirty_pages", "rearm_pages"):
        if integer(record, name, f"sample {ordinal}") != canonical:
            raise ReportError(f"sample {ordinal} {name} does not match bitmap")
    harvest = sum(integer(record, name, f"sample {ordinal}") for name in
                  ("discover_cycles", "normalize_cycles", "clear_d_cycles",
                   "hfence_cycles", "backend_reset_cycles"))
    pause = (integer(record, "quiesce_cycles", f"sample {ordinal}") + harvest +
             integer(record, "resume_cycles", f"sample {ordinal}"))
    epoch = integer(record, "workload_cycles", f"sample {ordinal}") + pause
    if integer(record, "harvest_cycles", f"sample {ordinal}") != harvest:
        raise ReportError(f"sample {ordinal} harvest timing identity failed")
    if integer(record, "pause_cycles", f"sample {ordinal}") != pause:
        raise ReportError(f"sample {ordinal} pause timing identity failed")
    if integer(record, "epoch_cycles", f"sample {ordinal}") != epoch:
        raise ReportError(f"sample {ordinal} epoch timing identity failed")


def validate_console(document: dict[str, Any], profile: str, workload_arg: str,
                     value: int | None, harts: int, backend: str) -> dict[str, Any]:
    begin, end = document["begin"], document["end"]
    if begin is None or end is None:
        raise ReportError("missing BEGIN or END")
    if backend not in BACKENDS:
        raise ReportError("unknown backend")
    require_fields(end, END_FIELDS, "END")
    for name, expected in (("samples", RUNS), ("failures", 0), ("status", 0)):
        if integer(end, name, "END") != expected:
            raise ReportError(f"END {name} must be {expected}")
    if len(document["samples"]) != RUNS:
        raise ReportError(f"expected {RUNS} samples, got {len(document['samples'])}")

    if profile == "single":
        if workload_arg not in SINGLE_WORKLOADS or value is None or harts != 1:
            raise ReportError("invalid single-hart selection")
        pattern = SINGLE_WORKLOADS[workload_arg]
        pages = value if workload_arg == "unique" else 1
        operations = value
        require_fields(begin, SINGLE_BEGIN_FIELDS, "BEGIN")
        expected_begin = {"abi": ABI_VERSION, "harvest_backend": BACKENDS[backend][0],
                          "runtime_mode": BACKENDS[backend][1], "pattern": pattern,
                          "hart_count": 1, "tracked_pages": 128,
                          "dirty_pages": pages, "operations": operations,
                          "samples": RUNS}
        for name, expected in expected_begin.items():
            if begin.get(name) != expected:
                raise ReportError(f"BEGIN {name}={begin.get(name)!r}, expected {expected!r}")
        if document["harts"]:
            raise ReportError("single-hart ABI contains HART records")
        if document["order"] != [("sample", sample, None) for sample in range(RUNS)]:
            raise ReportError("single-hart sample order is invalid")
        for ordinal, sample in enumerate(document["samples"]):
            require_fields(sample, SINGLE_SAMPLE_FIELDS, f"SAMPLE {ordinal}")
            for name in SINGLE_SAMPLE_FIELDS:
                if name not in STRING_FIELDS:
                    integer(sample, name, f"sample {ordinal}")
            _fixed_sample(sample, ordinal, backend,
                          {"pattern": pattern, "hart_count": 1,
                           "dirty_pages": pages, "operations": operations})
            expected_bits = bitmap(pages)
            if (sample["expected_bitmap0"], sample["expected_bitmap1"]) != expected_bits:
                raise ReportError(f"sample {ordinal} expected bitmap is wrong")
            if sample["workload_cycle_end"] < sample["workload_cycle_start"] or \
                    sample["workload_cycle_end"] - sample["workload_cycle_start"] != sample["workload_cycles"]:
                raise ReportError(f"sample {ordinal} workload cycle delta mismatch")
            if sample["actual_cause"] != 10 or sample["hfence_acks"] != 1 or sample["reset_acks"] != 1:
                raise ReportError(f"sample {ordinal} trap/fence/reset contract failed")
            _validate_backend_counts(sample, ordinal, backend, pages, single=True)
        normalized_harts: dict[int, list[dict[str, Any]]] = {}
    else:
        if workload_arg not in MC_WORKLOADS or value is not None or harts not in (1, 2, 4):
            raise ReportError("invalid multi-hart selection")
        workload = MC_WORKLOADS[workload_arg]
        per_hart_ops = mc_operations(harts, workload)
        dirty = mc_dirty_pages(harts, workload)
        require_fields(begin, MC_BEGIN_FIELDS, "BEGIN")
        expected_begin = {"abi": ABI_VERSION, "hart_count": harts,
                          "workload": workload, "harvest_backend": BACKENDS[backend][0],
                          "runtime_mode": BACKENDS[backend][1],
                          "tracked_pages": 128, "samples": RUNS}
        for name, expected in expected_begin.items():
            if begin.get(name) != expected:
                raise ReportError(f"BEGIN {name}={begin.get(name)!r}, expected {expected!r}")
        if len(document["harts"]) != RUNS * harts:
            raise ReportError("multi-hart HART record count is invalid")
        expected_order = [item for sample in range(RUNS) for item in
                          ([('sample', sample, None)] +
                           [('hart', sample, hart) for hart in range(harts)])]
        if document["order"] != expected_order:
            raise ReportError("SAMPLE/HART record order is invalid")
        normalized_harts = defaultdict(list)
        for ordinal, hart in enumerate(document["harts"]):
            require_fields(hart, MC_HART_FIELDS, f"HART {ordinal}")
            for name in MC_HART_FIELDS:
                integer(hart, name, f"HART {ordinal}")
            sample_id, hart_id = hart["sample"], hart["hart"]
            if sample_id >= RUNS or hart_id >= harts:
                raise ReportError("HART record id is out of range")
            normalized_harts[sample_id].append(hart)
        for ordinal, sample in enumerate(document["samples"]):
            require_fields(sample, MC_SAMPLE_FIELDS, f"SAMPLE {ordinal}")
            for name in MC_SAMPLE_FIELDS:
                if name not in STRING_FIELDS:
                    integer(sample, name, f"sample {ordinal}")
            _fixed_sample(sample, ordinal, backend,
                          {"workload": workload, "hart_count": harts})
            records = sorted(normalized_harts[ordinal], key=lambda row: row["hart"])
            if [row["hart"] for row in records] != list(range(harts)):
                raise ReportError(f"sample {ordinal} has missing/duplicate harts")
            expected_bits = bitmap(dirty)
            fixed = {"total_operations": per_hart_ops * harts,
                     "distinct_dirty_pages": dirty,
                     "canonical_dirty_pages": dirty,
                     "expected_bitmap0": expected_bits[0],
                     "expected_bitmap1": expected_bits[1],
                     "hfence_acks": harts, "reset_acks": harts}
            for name, expected in fixed.items():
                if sample[name] != expected:
                    raise ReportError(f"sample {ordinal} {name} must be {expected}")
            _validate_backend_counts(sample, ordinal, backend, dirty, single=False)
            idx = [0, 0, 0]
            hpm = [0, 0, 0, 0]
            cycles: list[int] = []
            for hart in records:
                hid = hart["hart"]
                fixed_hart = {"sample": ordinal, "hart": hid,
                              "warmup": int(ordinal == 0),
                              "repetition": 0 if ordinal == 0 else ordinal - 1,
                              "operations": per_hart_ops, "scause": 10,
                              "hfence_done": ordinal + 1,
                              "reset_done": ordinal + 1, "done": 1,
                              "control_errors": 0, "status": 0}
                for name, expected in fixed_hart.items():
                    if hart[name] != expected:
                        raise ReportError(f"sample {ordinal} hart {hid} {name} must be {expected}")
                if hart["cycle_end"] < hart["cycle_start"] or \
                        hart["cycle_end"] - hart["cycle_start"] != hart["workload_cycles"]:
                    raise ReportError(f"sample {ordinal} hart {hid} cycle delta mismatch")
                if hart["instret_end"] < hart["instret_start"] or \
                        hart["instret_end"] - hart["instret_start"] != hart["workload_instret"] or \
                        hart["workload_instret"] != 5 * per_hart_ops + 5:
                    raise ReportError(f"sample {ordinal} hart {hid} instret contract failed")
                if hart["idx_before"] != 0 or hart["idx_reset"] != 0:
                    raise ReportError(f"sample {ordinal} hart {hid} INDEX boundary failed")
                if backend == "pte-scan-serial" and hart["idx_after"] != 0:
                    raise ReportError(f"sample {ordinal} hart {hid} scan INDEX changed")
                idx[0] += hart["idx_before"]; idx[1] += hart["idx_after"]; idx[2] += hart["idx_reset"]
                for index, name in enumerate(("d_transitions", "committed_appends",
                                              "pte_cas_attempts", "cas_retries")):
                    hpm[index] += hart[name]
                cycles.append(hart["workload_cycles"])
            if idx != [sample["idx_before_total"], sample["idx_after_total"], sample["idx_reset_total"]]:
                raise ReportError(f"sample {ordinal} INDEX aggregate mismatch")
            if hpm != [sample["d_transitions"], sample["committed_appends"],
                       sample["pte_cas_attempts"], sample["cas_retries"]]:
                raise ReportError(f"sample {ordinal} HPM aggregate mismatch")
            if sample["workload_cycles"] != max(cycles):
                raise ReportError(f"sample {ordinal} global workload is not max local delta")
            if sample["quiesce_boundary"] < sample["hart0_cycle_start"] or \
                    sample["quiesce_boundary"] - sample["hart0_cycle_start"] != \
                    sample["workload_cycles"] + sample["quiesce_cycles"]:
                raise ReportError(f"sample {ordinal} quiesce boundary identity failed")
            if sample["d_transitions"] != dirty or sample["committed_appends"] != (dirty if backend == "shdlt-log" else 0):
                raise ReportError(f"sample {ordinal} HPM D/log count mismatch")
            if workload == "SAME_PTE":
                if not 1 <= sample["pte_cas_attempts"] <= harts or \
                        sample["cas_retries"] != sample["pte_cas_attempts"] - 1:
                    raise ReportError(f"sample {ordinal} SAME_PTE CAS count mismatch")
            elif sample["pte_cas_attempts"] != dirty or sample["cas_retries"] != 0:
                raise ReportError(f"sample {ordinal} private CAS count mismatch")

    samples = []
    for sample in document["samples"]:
        item = dict(sample)
        item["harts"] = sorted(normalized_harts.get(sample["sample"], []),
                               key=lambda row: row["hart"])
        samples.append(item)
    return {"schema": "shdlt-dirtygen-epoch-samples-v1", "profile": profile,
            "begin": begin, "samples": samples, "end": end}


def _validate_backend_counts(sample: dict[str, Any], ordinal: int, backend: str,
                             dirty: int, single: bool) -> None:
    before = sample["idx_before" if single else "idx_before_total"]
    after = sample["idx_after" if single else "idx_after_total"]
    reset = sample["idx_reset" if single else "idx_reset_total"]
    if before != 0 or reset != 0:
        raise ReportError(f"sample {ordinal} INDEX boundary must be zero")
    if backend == "pte-scan-serial":
        expected = {"pte_entries_scanned": 128, "raw_log_entries": 0,
                    "committed_log_entries": 0}
        if after != 0:
            raise ReportError(f"sample {ordinal} scan INDEX changed")
    else:
        expected = {"pte_entries_scanned": 0, "raw_log_entries": dirty,
                    "committed_log_entries": dirty}
        if after != dirty:
            raise ReportError(f"sample {ordinal} log INDEX must equal dirty pages")
    for name, value in expected.items():
        if sample[name] != value:
            raise ReportError(f"sample {ordinal} {name} must be {value}")


def symbol_values(elf: Path, profile: str, workload: str) -> dict[str, int]:
    if profile == "single":
        timed = ("dirtygen_perf_unique_timed_start" if workload == "unique"
                 else "dirtygen_perf_repeat_timed_start")
        wanted = {"dirtygen_perf_epoch_trace_start", "dirtygen_perf_epoch_trace_end",
                  timed, "dirtygen_perf_timed_end", "gpt", "tracked_data",
                  "dirty_log_buffers"}
    else:
        wanted = {"dirtygen_perf_mc_guest_start", "dirtygen_perf_mc_timed_start",
                  "dirtygen_perf_mc_timed_end", "dirtygen_perf_mc_epoch_start",
                  "dirtygen_perf_mc_epoch_end"}
    try:
        output = subprocess.check_output(["riscv64-elf-nm", "-n", str(elf)], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReportError(f"cannot inspect ELF symbols: {error}") from error
    symbols: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in wanted:
            symbols[parts[2]] = int(parts[0], 16)
    if set(symbols) != wanted:
        raise ReportError(f"ELF lacks symbols {sorted(wanted - set(symbols))}")
    return symbols


def trace_layout(symbols: dict[str, int], profile: str,
                 workload: str, harts: int) -> dict[str, Any]:
    if profile == "single":
        timed = ("dirtygen_perf_unique_timed_start" if workload == "unique"
                 else "dirtygen_perf_repeat_timed_start")
        return {"harts": 1, "epoch_start": symbols["dirtygen_perf_epoch_trace_start"],
                "epoch_end": symbols["dirtygen_perf_epoch_trace_end"],
                "timed_start": symbols[timed] & 0xfff,
                "timed_end": symbols["dirtygen_perf_timed_end"] & 0xfff,
                "pte_base": symbols["gpt"] + 2 * PAGE_SIZE +
                            (TRACKED_GPA >> 12) * 8,
                "tracked_physical": symbols["tracked_data"],
                "log_bases": [symbols["dirty_log_buffers"]]}
    start = symbols["dirtygen_perf_mc_guest_start"]
    return {"harts": harts, "epoch_start": symbols["dirtygen_perf_mc_epoch_start"],
            "epoch_end": symbols["dirtygen_perf_mc_epoch_end"],
            "timed_start": symbols["dirtygen_perf_mc_timed_start"] - start,
            "timed_end": symbols["dirtygen_perf_mc_timed_end"] - start,
            "pte_base": 0x81005080, "tracked_physical": 0x81200000,
            "log_bases": [0x82010000 + hart * 0x800000 for hart in range(harts)]}


def check_trace(lines: TextIO, samples: dict[str, Any], backend: str,
                layout: dict[str, Any]) -> dict[str, Any]:
    harts = layout["harts"]
    active: list[int | None] = [None] * harts
    timed: list[int | None] = [None] * harts
    next_sample = [0] * harts
    timed_count = [0] * harts
    stores: list[list[dict[str, Any]]] = [[] for _ in range(RUNS)]
    cases: list[list[dict[str, Any]]] = [[] for _ in range(RUNS)]
    physical: dict[tuple[int, int, int], dict[str, Any]] = {}
    bad: list[str] = []

    for raw in lines:
        line, lower = raw.strip(), raw.lower()
        if any(marker in lower for marker in BAD_MARKERS):
            bad.append(line)
        match = COMMIT_RE.match(line)
        if match:
            hart, pc = int(match.group(1)), int(match.group(2), 16)
            if hart >= harts:
                continue
            if pc == layout["epoch_start"]:
                if active[hart] is not None or next_sample[hart] >= RUNS:
                    raise DiagnosticIncomplete(f"invalid epoch start hart={hart}")
                active[hart] = next_sample[hart]
                next_sample[hart] += 1
            elif pc == layout["epoch_end"]:
                if active[hart] is None or timed[hart] is not None:
                    raise DiagnosticIncomplete(f"invalid epoch end hart={hart}")
                active[hart] = None
            elif pc == layout["timed_start"]:
                if active[hart] is None or timed[hart] is not None:
                    raise DiagnosticIncomplete(f"invalid timed start hart={hart}")
                timed[hart] = active[hart]
                timed_count[hart] += 1
            elif pc == layout["timed_end"]:
                if timed[hart] is None:
                    raise DiagnosticIncomplete(f"timed end without start hart={hart}")
                timed[hart] = None
            continue
        match = PTE_CAS_RE.match(line)
        if match:
            hart, source, attempt, cycle = map(int, match.group(1, 2, 3, 4))
            if hart >= harts or active[hart] is None:
                raise DiagnosticIncomplete(f"unattributable PTE CAS: {line}")
            event = {"hart": hart, "sample": active[hart], "source": source,
                     "attempt": attempt, "cycle": cycle,
                     "address": int(match.group(5), 16), "length": int(match.group(6)),
                     "expected": int(match.group(7), 16),
                     "desired": int(match.group(8), 16),
                     "observed": int(match.group(9), 16),
                     "error": int(match.group(10)), "updated": int(match.group(11))}
            key = (hart, source, attempt)
            if any(item["hart"] == hart and item["source"] == source and
                   item["attempt"] == attempt for group in cases for item in group):
                raise ReportError(f"duplicate PTE CAS identity {key}")
            cases[event["sample"]].append(event)
            continue
        match = PHYSICAL_RE.match(line)
        if match:
            hart, source, attempt, cycle = map(int, match.group(1, 2, 3, 4))
            key = (hart, source, attempt)
            if hart >= harts or (active[hart] is None and key not in physical):
                raise DiagnosticIncomplete(f"unattributable physical lifecycle: {line}")
            values = {"hart": hart, "sample": active[hart], "source": source,
                      "attempt": attempt, "cycle": cycle,
                      "address": int(match.group(5), 16), "length": int(match.group(6)),
                      "data": int(match.group(7), 16), "error": int(match.group(8)),
                      "states": []}
            entry = physical.setdefault(key, values)
            for name in ("hart", "source", "attempt", "cycle", "address", "length", "data", "error"):
                if entry[name] != values[name]:
                    raise ReportError(f"physical lifecycle context changed for {key}")
            entry["states"].append(match.group(9))
            continue
        match = STORE_RE.match(line)
        if match:
            hart = int(match.group(1))
            if hart >= harts or active[hart] is None:
                raise DiagnosticIncomplete(f"unattributable architectural MMU store: {line}")
            stores[active[hart]].append({"hart": hart,
                "address": int(match.group(2), 16), "length": int(match.group(3)),
                "data": int(match.group(4), 16), "error": int(match.group(5))})
        elif line.startswith(("rv mmu pte-cas", "rv mmu physical-store", "rv mmu store")):
            raise DiagnosticIncomplete(f"malformed MMU trace record: {line}")

    if bad:
        raise ReportError(f"RVLS/timeout failure marker: {bad[0]}")
    if any(value is not None for value in active + timed) or \
            next_sample != [RUNS] * harts or timed_count != [RUNS] * harts:
        raise DiagnosticIncomplete(
            f"incomplete epochs/timed windows active={active} timed={timed} "
            f"epochs={next_sample} timed_count={timed_count}")

    trace_samples = []
    lifecycle_rows = []
    for sample_id, firmware in enumerate(samples["samples"]):
        expected_pages = {page for page in range(TRACKED_PAGES)
                          if firmware["canonical_bitmap" + str(page // 64)] &
                          (1 << (page % 64))}
        sample_cases = cases[sample_id]
        success, mismatch = [], []
        identities = {(item["hart"], item["source"], item["attempt"]): item
                      for item in sample_cases}
        for item in sample_cases:
            address = item["address"]
            if item["length"] != 8 or item["error"] != 0 or \
                    address < layout["pte_base"] or address >= layout["pte_base"] + TRACKED_PAGES * 8 or \
                    (address - layout["pte_base"]) % 8:
                raise ReportError(f"sample {sample_id} malformed PTE CAS")
            page = (address - layout["pte_base"]) // 8
            clean = (((layout["tracked_physical"] + page * PAGE_SIZE) >> 12) << 10) | 0x57
            dirty = clean | 0x80
            if item["expected"] != clean or item["desired"] != dirty:
                raise ReportError(f"sample {sample_id} CAS full-width expected/desired mismatch")
            if item["updated"]:
                if item["observed"] != clean:
                    raise ReportError(f"sample {sample_id} successful CAS observed mismatch")
                success.append(item | {"page": page})
            else:
                if item["observed"] != dirty:
                    raise ReportError(f"sample {sample_id} invalid CAS mismatch outcome")
                mismatch.append(item | {"page": page})
        pages = [item["page"] for item in success]
        if len(pages) != len(set(pages)) or set(pages) != expected_pages:
            raise ReportError(f"sample {sample_id} successful CAS page set differs from canonical bitmap")

        sample_physical = [entry for entry in physical.values()
                           if entry["sample"] == sample_id]
        committed, superseded = [], []
        for entry in sample_physical:
            key = (entry["hart"], entry["source"], entry["attempt"])
            if key not in identities:
                raise ReportError(f"sample {sample_id} physical attempt lacks matching CAS")
            if entry["states"] == ["pending", "committed"]:
                terminal = "committed"; committed.append(entry)
                if identities[key]["updated"] != 1:
                    raise ReportError(f"sample {sample_id} committed logger attempt lost CAS")
            elif entry["states"] == ["pending", "superseded"]:
                terminal = "superseded"; superseded.append(entry)
                if identities[key]["updated"] != 0:
                    raise ReportError(f"sample {sample_id} superseded logger attempt won CAS")
            else:
                raise ReportError(f"open/duplicate physical lifecycle {key}: {entry['states']}")
            base = layout["log_bases"][entry["hart"]]
            if entry["length"] != 8 or entry["error"] != 0 or \
                    entry["address"] < base or entry["address"] >= base + LOG_CAPACITY * 8 or \
                    (entry["address"] - base) % 8 or entry["data"] not in \
                    {TRACKED_GPA + page * PAGE_SIZE for page in expected_pages}:
                raise ReportError(f"sample {sample_id} malformed physical logger attempt")
            lifecycle_rows.append({"sample": sample_id, "hart": entry["hart"],
                "source": entry["source"], "attempt": entry["attempt"],
                "observed_cycle": entry["cycle"],
                "address": f"0x{entry['address']:016x}",
                "data": f"0x{entry['data']:016x}", "states": entry["states"],
                "terminal_state": terminal})

        if backend == "pte-scan-serial" and sample_physical:
            raise ReportError(f"sample {sample_id} scan backend emitted physical logger stores")
        if backend == "shdlt-log":
            if {(entry["hart"], entry["source"], entry["attempt"])
                    for entry in sample_physical} != set(identities):
                raise ReportError(f"sample {sample_id} logger/CAS attempt identities differ")
            if len(committed) != firmware["committed_log_entries"] or \
                    {entry["data"] for entry in committed} != \
                    {TRACKED_GPA + page * PAGE_SIZE for page in expected_pages}:
                raise ReportError(f"sample {sample_id} committed logger set mismatch")
            for entry in committed:
                slot = (entry["address"] - layout["log_bases"][entry["hart"]]) // 8
                hart_rows = firmware.get("harts", [])
                limit = (next(row["idx_after"] for row in hart_rows if row["hart"] == entry["hart"])
                         if hart_rows else firmware["idx_after"])
                if slot >= limit:
                    raise ReportError(f"sample {sample_id} committed logger entry lies outside INDEX")

        remaining = list(stores[sample_id])
        for entry in committed:
            wanted = {"hart": entry["hart"], "address": entry["address"],
                      "length": entry["length"], "data": entry["data"],
                      "error": entry["error"]}
            if wanted not in remaining:
                raise ReportError(f"sample {sample_id} committed logger store missing from architecture stream")
            remaining.remove(wanted)
        superseded_arch = [{"hart": entry["hart"], "address": entry["address"],
                            "length": entry["length"], "data": entry["data"],
                            "error": entry["error"]} for entry in superseded]
        if any(item in stores[sample_id] for item in superseded_arch):
            raise ReportError(f"sample {sample_id} superseded logger store became architectural")
        for item in success:
            wanted = {"hart": item["hart"], "address": item["address"],
                      "length": item["length"], "data": item["desired"], "error": 0}
            if wanted not in remaining:
                raise ReportError(f"sample {sample_id} successful CAS lacks one PTE store")
            remaining.remove(wanted)
        if remaining:
            raise ReportError(f"sample {sample_id} unexpected architectural MMU stores: {remaining}")
        if any({"hart": item["hart"], "address": item["address"], "length": 8,
                "data": item["desired"], "error": 0} in stores[sample_id]
               for item in mismatch):
            raise ReportError(f"sample {sample_id} CAS mismatch emitted a PTE store")

        if samples["profile"] == "mc":
            if len(sample_cases) != firmware["pte_cas_attempts"] or \
                    len(mismatch) != firmware["cas_retries"] or \
                    len(committed) != firmware["committed_appends"]:
                raise ReportError(f"sample {sample_id} trace/HPM counts disagree")
            for hart in firmware["harts"]:
                hid = hart["hart"]
                hart_cases = [item for item in sample_cases if item["hart"] == hid]
                hart_mismatch = [item for item in mismatch if item["hart"] == hid]
                hart_committed = [item for item in committed if item["hart"] == hid]
                if (len(hart_cases) != hart["pte_cas_attempts"] or
                        len(hart_mismatch) != hart["cas_retries"] or
                        len(hart_committed) != hart["committed_appends"]):
                    raise ReportError(f"sample {sample_id} hart {hid} trace/HPM attribution differs")
        elif mismatch:
            raise ReportError(f"sample {sample_id} single-hart run has a CAS mismatch")
        trace_samples.append({"sample": sample_id, "pte_cas_attempts": len(sample_cases),
            "pte_cas_success": len(success), "pte_cas_mismatch": len(mismatch),
            "physical_attempts": len(sample_physical), "committed": len(committed),
            "superseded": len(superseded),
            "architectural_stores": len(stores[sample_id]),
            "successful_pages": sorted(expected_pages),
            "winner_harts": sorted({item["hart"] for item in success}),
            "observer_harts": sorted(set(range(harts)) -
                                     {item["hart"] for item in sample_cases})})
    return {"schema": "shdlt-dirtygen-epoch-trace-v1", "status": "PASS",
            "profile": samples["profile"], "backend": backend,
            "sample_segmentation": "per-hart epoch markers; CAS identity owns logger terminal",
            "samples": trace_samples, "lifecycles": lifecycle_rows,
            "totals": {name: sum(row[name] for row in trace_samples) for name in
                       ("pte_cas_attempts", "pte_cas_success", "pte_cas_mismatch",
                        "physical_attempts", "committed", "superseded",
                        "architectural_stores")}}


def csv_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for sample in document["samples"]:
        base = {key: value for key, value in sample.items() if key != "harts"}
        if sample["harts"]:
            for hart in sample["harts"]:
                rows.append(base | {f"hart_{key}": value for key, value in hart.items()})
        else:
            rows.append(base)
    return rows


def write_outputs(samples: dict[str, Any], trace: dict[str, Any], output: Path) -> None:
    if output.exists():
        raise ReportError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.mkdir()
        for name, document in (("samples.json", samples), ("trace-report.json", trace)):
            with (temporary / name).open("w", encoding="utf-8") as stream:
                json.dump(document, stream, indent=2, sort_keys=True)
                stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        rows = csv_rows(samples)
        with (temporary / "samples.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("console", type=Path)
    parser.add_argument("--profile", choices=("single", "mc"), required=True)
    parser.add_argument("--workload", choices=tuple(SINGLE_WORKLOADS | MC_WORKLOADS), required=True)
    parser.add_argument("--value", type=int)
    parser.add_argument("--hart-count", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--backend", choices=tuple(BACKENDS), required=True)
    parser.add_argument("--tracer", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.profile == "single" and (args.workload not in SINGLE_WORKLOADS or args.value is None or args.hart_count != 1):
        parser.error("single profile requires unique|repeat, --value, and --hart-count 1")
    if args.profile == "mc" and (args.workload not in MC_WORKLOADS or args.value is not None):
        parser.error("mc profile requires an MC workload and no --value")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with args.console.open(encoding="utf-8", errors="replace") as stream:
            parsed = parse_console(stream, args.profile)
        samples = validate_console(parsed, args.profile, args.workload,
                                   args.value, args.hart_count, args.backend)
        symbols = symbol_values(args.elf, args.profile, args.workload)
        layout = trace_layout(symbols, args.profile, args.workload, args.hart_count)
        with args.tracer.open(encoding="utf-8", errors="replace") as stream:
            trace = check_trace(stream, samples, args.backend, layout)
        write_outputs(samples, trace, args.output_dir)
        print(f"dirtygen epoch report: PASS profile={args.profile} "
              f"backend={args.backend} samples={RUNS}")
        return 0
    except (OSError, ValueError, ReportError) as error:
        print(f"dirtygen epoch report: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
