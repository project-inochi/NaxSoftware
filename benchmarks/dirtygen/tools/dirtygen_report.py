#!/usr/bin/env python3
"""Parse and validate machine-readable VexiiRiscv dirtygen ABI v4/v5 output."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, TextIO


PREFIX = "DIRTYGEN_"
NUMERIC_PREFIX = "0x"
ABI_VERSION = 5
V4_ABI_VERSION = 4
V4_CASE_COUNT = 24
V5_LEGACY_CASE_COUNT = 30
CASE_COUNT = 32
MEASURED_REPETITIONS = 5
BASE_CAPACITY = 512
ENTRY_BYTES = 8
BUFFER_COUNT = 4
MAX_LOG_SIZE = 2
MAX_EPOCHS = 8
DESC_BYTES = 128
SAMPLE_BYTES = 192
EPOCH_BYTES = 256
RESULT_BYTES = 2048
TRACKED_GPA_BASE = 0x10000
PAGE_SIZE = 4096
FAULT_CAUSE = 0x18
FAULT_STOP = 1
FAULT_REPLACE = 2
NO_BUFFER = 0xFFFFFFFF


@dataclass(frozen=True)
class CaseSpec:
    name: str
    kind: str
    touched: int
    stores: int
    predirty: int
    entries: int
    log_size: int = 0
    initial_idx: int = 0
    replacement_idx: int = 0
    buffers: int = 1
    final_indices: tuple[int, int, int, int] = (0, 0, 0, 0)
    fault_actions: tuple[int, ...] = ()
    epochs: int = 0
    epoch_touched: int = 0
    epoch_stores: int = 0
    epoch_stride: int = 0

    @property
    def capacity(self) -> int:
        return BASE_CAPACITY << self.log_size


CASE_SPECS: tuple[CaseSpec, ...] = (
    CaseSpec("sweep_off_d1", "workload", 128, 128, 128, 0),
    CaseSpec("sweep_off_d0", "workload", 128, 128, 0, 0),
    CaseSpec("sweep_on_d1", "workload", 128, 128, 128, 0),
    CaseSpec("sweep_on_d0", "workload", 128, 128, 0, 128,
             final_indices=(128, 0, 0, 0)),
    CaseSpec("repeat_on_d0", "workload", 1, 4096, 0, 1,
             final_indices=(1, 0, 0, 0)),
    CaseSpec("permute_on_d0", "workload", 128, 128, 0, 128,
             final_indices=(128, 0, 0, 0)),
    CaseSpec("random_dirty0", "workload", 128, 4224, 0, 128,
             final_indices=(128, 0, 0, 0)),
    CaseSpec("random_dirty25", "workload", 128, 4224, 32, 96,
             final_indices=(96, 0, 0, 0)),
    CaseSpec("random_dirty50", "workload", 128, 4224, 64, 64,
             final_indices=(64, 0, 0, 0)),
    CaseSpec("random_dirty75", "workload", 128, 4224, 96, 32,
             final_indices=(32, 0, 0, 0)),
    CaseSpec("random_dirty100", "workload", 128, 4224, 128, 0),
    CaseSpec("boundary_idx510", "boundary", 1, 1, 0, 1,
             initial_idx=510, final_indices=(511, 0, 0, 0)),
    CaseSpec("boundary_idx511", "boundary", 1, 1, 0, 1,
             initial_idx=511, final_indices=(512, 0, 0, 0)),
    CaseSpec("boundary_full_fault", "boundary", 1, 1, 0, 0,
             initial_idx=512, final_indices=(512, 0, 0, 0),
             fault_actions=(FAULT_STOP,)),
    CaseSpec("boundary_full_recover", "boundary", 1, 1, 0, 1,
             initial_idx=512, buffers=2, final_indices=(512, 1, 0, 0),
             fault_actions=(FAULT_REPLACE,)),
    CaseSpec("size1_idx1023", "boundary", 1, 1, 0, 1, log_size=1,
             initial_idx=1023, final_indices=(1024, 0, 0, 0)),
    CaseSpec("size1_full_fault", "boundary", 1, 1, 0, 0, log_size=1,
             initial_idx=1024, final_indices=(1024, 0, 0, 0),
             fault_actions=(FAULT_STOP,)),
    CaseSpec("size1_full_recover", "boundary", 1, 1, 0, 1, log_size=1,
             initial_idx=1024, buffers=2, final_indices=(1024, 1, 0, 0),
             fault_actions=(FAULT_REPLACE,)),
    CaseSpec("size2_idx2047", "boundary", 1, 1, 0, 1, log_size=2,
             initial_idx=2047, final_indices=(2048, 0, 0, 0)),
    CaseSpec("size2_full_fault", "boundary", 1, 1, 0, 0, log_size=2,
             initial_idx=2048, final_indices=(2048, 0, 0, 0),
             fault_actions=(FAULT_STOP,)),
    CaseSpec("size2_full_recover", "boundary", 1, 1, 0, 1, log_size=2,
             initial_idx=2048, buffers=2, final_indices=(2048, 1, 0, 0),
             fault_actions=(FAULT_REPLACE,)),
    CaseSpec("size2_base_mask", "boundary", 1, 1, 0, 1, log_size=2,
             final_indices=(1, 0, 0, 0)),
    CaseSpec("replace_chain_3fault", "chain", 4, 4, 0, 4,
             initial_idx=511, replacement_idx=511, buffers=4,
             final_indices=(512, 512, 512, 512),
             fault_actions=(FAULT_REPLACE, FAULT_REPLACE, FAULT_REPLACE)),
    CaseSpec("replace_chain_exhaust_stop", "chain", 5, 5, 0, 4,
             initial_idx=511, replacement_idx=511, buffers=4,
             final_indices=(512, 512, 512, 512),
             fault_actions=(FAULT_REPLACE, FAULT_REPLACE, FAULT_REPLACE,
                            FAULT_STOP)),
    CaseSpec("epoch_empty_8", "epoch", 0, 0, 0, 0,
             epochs=8),
    CaseSpec("epoch_rotate_1x8", "epoch", 8, 8, 0, 8,
             epochs=8, epoch_touched=1, epoch_stores=1, epoch_stride=1),
    CaseSpec("epoch_repeat32_8", "epoch", 8, 256, 0, 8,
             epochs=8, epoch_touched=1, epoch_stores=32, epoch_stride=1),
    CaseSpec("epoch_rotate_16x8", "epoch", 128, 128, 0, 128,
             epochs=8, epoch_touched=16, epoch_stores=16, epoch_stride=16),
    CaseSpec("epoch_rotate_64x8", "epoch", 128, 512, 0, 512,
             epochs=8, epoch_touched=64, epoch_stores=64, epoch_stride=17),
    CaseSpec("epoch_full_128x8", "epoch", 128, 1024, 0, 1024,
             epochs=8, epoch_touched=128, epoch_stores=128, epoch_stride=19),
    CaseSpec("boundary_overflow_fault", "boundary", 1, 1, 0, 0,
             initial_idx=513, final_indices=(513, 0, 0, 0),
             fault_actions=(FAULT_STOP,)),
    CaseSpec("boundary_log_off_full", "boundary", 1, 1, 0, 0,
             initial_idx=512, final_indices=(512, 0, 0, 0)),
)

STATIC_SAMPLE_FIELDS = (
    "case", "id", "tracked", "touched", "stores", "predirty", "entries",
    "unique", "duplicates", "missing", "extra", "log_size", "capacity",
    "initial_idx", "replacement_idx", "buffers", "idx0", "idx1", "idx2",
    "idx3", "faults", "ctl_size", "ctl_base", "epochs", "drained",
    "status",
)
SUMMARY_METRICS = (
    "cycles", "instret", "fault_cycles", "service_cycles", "retry_cycles",
    "guest_cycles", "end_to_end_cycles", "freeze_cycles", "drain_cycles",
    "reset_cycles", "fence_cycles", "resume_cycles",
)
V4_SUMMARY_METRICS = SUMMARY_METRICS[:7]
PHASE_METRICS = (
    "freeze_cycles", "drain_cycles", "reset_cycles", "fence_cycles",
    "resume_cycles",
)


def _parse_value(value: str) -> Any:
    if value.startswith(NUMERIC_PREFIX):
        return int(value, 16)
    return value


def _parse_record(line: str) -> tuple[str, dict[str, Any]] | None:
    start = line.find(PREFIX)
    if start < 0:
        return None
    tokens = line[start:].strip().split()
    kind = tokens[0][len(PREFIX):].lower()
    fields: dict[str, Any] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise ValueError(f"malformed dirtygen token: {token!r}")
        key, value = token.split("=", 1)
        if key in fields:
            raise ValueError(f"duplicate dirtygen field: {key!r}")
        fields[key] = _parse_value(value)
    return kind, fields


def _required_int(record: dict[str, Any], key: str, kind: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{kind} is missing numeric field {key!r}")
    return value


def _median(values: list[int]) -> int:
    return int(statistics.median(values))


@dataclass
class DirtygenReport:
    begin: dict[str, Any] | None = None
    end: dict[str, Any] | None = None
    samples: list[dict[str, Any]] = field(default_factory=list)
    faults: list[dict[str, Any]] = field(default_factory=list)
    epochs: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        if self.begin is None:
            raise ValueError("missing DIRTYGEN_BEGIN")
        if self.end is None:
            raise ValueError("missing DIRTYGEN_END")
        if self.errors:
            raise ValueError(f"dirtygen emitted {len(self.errors)} error record(s)")

        version = _required_int(self.begin, "version", "DIRTYGEN_BEGIN")
        if version not in (V4_ABI_VERSION, ABI_VERSION):
            raise ValueError(
                f"unsupported ABI version {version}; expected 4 or {ABI_VERSION}"
            )
        is_v5 = version == ABI_VERSION
        if is_v5:
            case_count = _required_int(self.begin, "cases", "DIRTYGEN_BEGIN")
            if case_count not in (V5_LEGACY_CASE_COUNT, CASE_COUNT):
                raise ValueError(
                    f"DIRTYGEN_BEGIN cases={case_count}, expected "
                    f"{V5_LEGACY_CASE_COUNT} or {CASE_COUNT}"
                )
        else:
            case_count = V4_CASE_COUNT
        case_first = (
            _required_int(self.begin, "case_first", "DIRTYGEN_BEGIN")
            if is_v5 else 0
        )
        case_limit = (
            _required_int(self.begin, "case_limit", "DIRTYGEN_BEGIN")
            if is_v5 else V4_CASE_COUNT
        )
        if not 0 <= case_first < case_limit <= case_count:
            raise ValueError(
                f"invalid DIRTYGEN_BEGIN case range {case_first}:{case_limit}"
            )
        expected_begin = {
            "cases": case_count,
            "warmup": 1,
            "reps": MEASURED_REPETITIONS,
            "capacity": BASE_CAPACITY,
            "entry_bytes": ENTRY_BYTES,
            "buffers": BUFFER_COUNT,
            "max_size": MAX_LOG_SIZE,
        }
        if is_v5:
            expected_begin.update({
                "max_epochs": MAX_EPOCHS,
                "desc_bytes": DESC_BYTES,
                "sample_bytes": SAMPLE_BYTES,
                "epoch_bytes": EPOCH_BYTES,
                "result_bytes": RESULT_BYTES,
            })
        for key, expected in expected_begin.items():
            actual = _required_int(self.begin, key, "DIRTYGEN_BEGIN")
            if actual != expected:
                raise ValueError(
                    f"DIRTYGEN_BEGIN {key}={actual}, expected {expected}"
                )

        selected_cases = range(case_first, case_limit)
        expected_samples = len(selected_cases) * MEASURED_REPETITIONS
        if len(self.samples) != expected_samples:
            raise ValueError(
                f"expected {expected_samples} samples, found {len(self.samples)}"
            )
        if len(self.summaries) != len(selected_cases):
            raise ValueError(
                f"expected {len(selected_cases)} summaries, "
                f"found {len(self.summaries)}"
            )

        actual_pairs: set[tuple[int, int]] = set()
        by_case: dict[int, list[dict[str, Any]]] = {}
        sample_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
        ctl_bases: set[int] = set()
        for sample in self.samples:
            case_id = _required_int(sample, "id", "DIRTYGEN_SAMPLE")
            repetition = _required_int(sample, "rep", "DIRTYGEN_SAMPLE")
            pair = (case_id, repetition)
            if pair in actual_pairs:
                raise ValueError(f"duplicate sample id/repetition: {pair}")
            if (case_id not in selected_cases or
                    repetition >= MEASURED_REPETITIONS):
                raise ValueError(f"out-of-range sample id/repetition: {pair}")
            actual_pairs.add(pair)
            by_case.setdefault(case_id, []).append(sample)
            sample_by_pair[pair] = sample
            self._validate_sample(sample, CASE_SPECS[case_id], is_v5)
            ctl_bases.add(_required_int(sample, "ctl_base", "DIRTYGEN_SAMPLE"))

        expected_pairs = {
            (case_id, repetition)
            for case_id in selected_cases
            for repetition in range(MEASURED_REPETITIONS)
        }
        if actual_pairs != expected_pairs:
            missing = sorted(expected_pairs - actual_pairs)
            extra = sorted(actual_pairs - expected_pairs)
            raise ValueError(f"sample matrix mismatch: missing={missing} extra={extra}")
        if len(ctl_bases) != 1 or 0 in ctl_bases:
            raise ValueError(f"HDLTCTL base set mismatch: {sorted(ctl_bases)}")

        for case_id, samples in by_case.items():
            samples.sort(key=lambda item: item["rep"])
            first = samples[0]
            for sample in samples[1:]:
                static_fields = (STATIC_SAMPLE_FIELDS if is_v5
                                 else tuple(key for key in STATIC_SAMPLE_FIELDS
                                            if key not in ("epochs", "drained")))
                for key in static_fields:
                    if sample.get(key) != first.get(key):
                        raise ValueError(
                            f"case {case_id} has non-static field {key!r}"
                        )

        self._validate_faults(sample_by_pair, selected_cases)
        if is_v5:
            self._validate_epochs(sample_by_pair, selected_cases)
        elif self.epochs:
            raise ValueError("ABI v4 log contains DIRTYGEN_EPOCH records")
        self._validate_summaries(by_case, selected_cases, is_v5)

        completed = _required_int(self.end, "completed", "DIRTYGEN_END")
        failures = _required_int(self.end, "failures", "DIRTYGEN_END")
        status = _required_int(self.end, "status", "DIRTYGEN_END")
        if completed != expected_samples:
            raise ValueError(
                f"DIRTYGEN_END completed={completed}, expected {expected_samples}"
            )
        if failures != 0 or status != 0:
            raise ValueError(f"DIRTYGEN_END failures={failures} status=0x{status:x}")

    @staticmethod
    def _validate_sample(sample: dict[str, Any], spec: CaseSpec,
                         is_v5: bool) -> None:
        case_id = _required_int(sample, "id", "DIRTYGEN_SAMPLE")
        if sample.get("case") != spec.name:
            raise ValueError(
                f"sample case {case_id} name={sample.get('case')!r}, "
                f"expected {spec.name!r}"
            )
        expected_fields = {
            "tracked": 128,
            "touched": spec.touched,
            "stores": spec.stores,
            "predirty": spec.predirty,
            "entries": spec.entries,
            "unique": spec.entries,
            "duplicates": 0,
            "missing": 0,
            "extra": 0,
            "log_size": spec.log_size,
            "capacity": spec.capacity,
            "initial_idx": spec.initial_idx,
            "replacement_idx": spec.replacement_idx,
            "buffers": spec.buffers,
            "faults": len(spec.fault_actions),
            "ctl_size": spec.log_size,
            "status": 0,
        }
        if is_v5:
            expected_fields.update({
                "epochs": spec.epochs,
                "drained": spec.entries if spec.kind == "epoch" else 0,
            })
        expected_fields.update(
            {f"idx{index}": value for index, value in enumerate(spec.final_indices)}
        )
        for key, expected in expected_fields.items():
            actual = sample.get(key)
            if actual != expected:
                raise ValueError(
                    f"sample case {case_id} {key}={actual!r}, expected {expected!r}"
                )

        ctl_base = _required_int(sample, "ctl_base", "DIRTYGEN_SAMPLE")
        if ctl_base == 0 or ctl_base % (spec.capacity * ENTRY_BYTES) != 0:
            raise ValueError(
                f"sample case {case_id} has misaligned ctl_base=0x{ctl_base:x}"
            )
        for key in ("cycles", "instret", "end_to_end_cycles"):
            if _required_int(sample, key, "DIRTYGEN_SAMPLE") == 0:
                raise ValueError(f"sample case {case_id} has zero {key}")

        cycles = _required_int(sample, "cycles", "DIRTYGEN_SAMPLE")
        end_to_end = _required_int(sample, "end_to_end_cycles", "DIRTYGEN_SAMPLE")
        fault = _required_int(sample, "fault_cycles", "DIRTYGEN_SAMPLE")
        service = _required_int(sample, "service_cycles", "DIRTYGEN_SAMPLE")
        retry = _required_int(sample, "retry_cycles", "DIRTYGEN_SAMPLE")
        guest = _required_int(sample, "guest_cycles", "DIRTYGEN_SAMPLE")
        phases = tuple(
            _required_int(sample, key, "DIRTYGEN_SAMPLE")
            for key in PHASE_METRICS
        ) if is_v5 else (0, 0, 0, 0, 0)
        if cycles != end_to_end:
            raise ValueError(f"sample case {case_id} cycles/end-to-end mismatch")
        if spec.kind == "epoch":
            if any((fault, service, retry)) or guest == 0 or any(
                    value == 0 for value in phases):
                raise ValueError(
                    f"sample case {case_id} has invalid epoch segments"
                )
            if end_to_end < guest + sum(phases):
                raise ValueError(
                    f"sample case {case_id} epoch segment sum exceeds end-to-end"
                )
        elif not spec.fault_actions:
            if any((fault, service, retry)) or guest != end_to_end:
                raise ValueError(f"sample case {case_id} has invalid no-fault segments")
            if any(phases):
                raise ValueError(f"sample case {case_id} has unexpected epoch phases")
        elif spec.fault_actions == (FAULT_STOP,):
            if fault == 0 or any((service, retry, guest)) or end_to_end != fault:
                raise ValueError(f"sample case {case_id} has invalid STOP segments")
        else:
            if fault == 0 or service == 0 or retry == 0:
                raise ValueError(f"sample case {case_id} has a zero recovery segment")
            if end_to_end != fault + service + guest:
                raise ValueError(f"sample case {case_id} segment sum mismatch")
            if retry > guest:
                raise ValueError(f"sample case {case_id} retry exceeds guest cycles")

    def _validate_faults(
        self, sample_by_pair: dict[tuple[int, int], dict[str, Any]],
        selected_cases: range,
    ) -> None:
        actual_keys: set[tuple[int, int, int]] = set()
        by_sample: dict[tuple[int, int], list[dict[str, Any]]] = {}
        fault_sepcs: set[int] = set()
        for event in self.faults:
            case_id = _required_int(event, "id", "DIRTYGEN_FAULT")
            repetition = _required_int(event, "rep", "DIRTYGEN_FAULT")
            ordinal = _required_int(event, "ordinal", "DIRTYGEN_FAULT")
            key = (case_id, repetition, ordinal)
            if key in actual_keys:
                raise ValueError(f"duplicate fault id/repetition/ordinal: {key}")
            if (case_id, repetition) not in sample_by_pair:
                raise ValueError(f"fault has no matching sample: {key}")
            actual_keys.add(key)
            by_sample.setdefault((case_id, repetition), []).append(event)
            fault_sepcs.add(_required_int(event, "sepc", "DIRTYGEN_FAULT"))

        expected_keys = {
            (case_id, repetition, ordinal)
            for case_id in selected_cases
            for spec in (CASE_SPECS[case_id],)
            for repetition in range(MEASURED_REPETITIONS)
            for ordinal in range(len(spec.fault_actions))
        }
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            raise ValueError(f"fault matrix mismatch: missing={missing} extra={extra}")
        if expected_keys and (len(fault_sepcs) != 1 or 0 in fault_sepcs):
            raise ValueError(f"faulting sepc set mismatch: {sorted(fault_sepcs)}")

        for pair, sample in sample_by_pair.items():
            case_id, _ = pair
            spec = CASE_SPECS[case_id]
            events = sorted(
                by_sample.get(pair, []), key=lambda event: event["ordinal"]
            )
            fault_sum = service_sum = retry_sum = 0
            for ordinal, (event, action) in enumerate(
                zip(events, spec.fault_actions)
            ):
                expected_buffer = ordinal if spec.kind == "chain" else 0
                expected_replacement = (
                    NO_BUFFER if action == FAULT_STOP else expected_buffer + 1
                )
                expected_gpa = TRACKED_GPA_BASE
                if spec.kind == "chain":
                    expected_gpa += (ordinal + 1) * PAGE_SIZE
                expected_index = (
                    spec.capacity if spec.kind == "chain" else spec.initial_idx
                )
                expected_fields = {
                    "case": spec.name,
                    "id": case_id,
                    "rep": pair[1],
                    "ordinal": ordinal,
                    "buffer": expected_buffer,
                    "index": expected_index,
                    "action": action,
                    "replacement_buffer": expected_replacement,
                    "replacement_idx": spec.replacement_idx,
                    "scause": FAULT_CAUSE,
                    "stval": expected_gpa,
                    "htval": expected_gpa >> 2,
                }
                for key, expected in expected_fields.items():
                    if event.get(key) != expected:
                        raise ValueError(
                            f"fault {case_id}/{pair[1]}/{ordinal} {key}="
                            f"{event.get(key)!r}, expected {expected!r}"
                        )
                event_fault = _required_int(event, "fault_cycles", "DIRTYGEN_FAULT")
                event_service = _required_int(
                    event, "service_cycles", "DIRTYGEN_FAULT"
                )
                event_retry = _required_int(event, "retry_cycles", "DIRTYGEN_FAULT")
                if event_fault == 0:
                    raise ValueError(f"fault {case_id}/{pair[1]}/{ordinal} has zero latency")
                if action == FAULT_STOP:
                    if event_service != 0 or event_retry != 0:
                        raise ValueError(
                            f"fault {case_id}/{pair[1]}/{ordinal} STOP has service/retry"
                        )
                elif event_service == 0 or event_retry == 0:
                    raise ValueError(
                        f"fault {case_id}/{pair[1]}/{ordinal} replace has zero segment"
                    )
                fault_sum += event_fault
                service_sum += event_service
                retry_sum += event_retry
            expected_sums = {
                "fault_cycles": fault_sum,
                "service_cycles": service_sum,
                "retry_cycles": retry_sum,
            }
            for key, expected in expected_sums.items():
                actual = _required_int(sample, key, "DIRTYGEN_SAMPLE")
                if actual != expected:
                    raise ValueError(
                        f"sample {pair} {key}={actual}, event sum={expected}"
                    )

    def _validate_epochs(
        self, sample_by_pair: dict[tuple[int, int], dict[str, Any]],
        selected_cases: range,
    ) -> None:
        actual_keys: set[tuple[int, int, int]] = set()
        by_sample: dict[tuple[int, int], list[dict[str, Any]]] = {}

        for event in self.epochs:
            case_id = _required_int(event, "id", "DIRTYGEN_EPOCH")
            repetition = _required_int(event, "rep", "DIRTYGEN_EPOCH")
            ordinal = _required_int(event, "epoch", "DIRTYGEN_EPOCH")
            key = (case_id, repetition, ordinal)
            if key in actual_keys:
                raise ValueError(f"duplicate epoch id/repetition/ordinal: {key}")
            if (case_id, repetition) not in sample_by_pair:
                raise ValueError(f"epoch has no matching sample: {key}")
            actual_keys.add(key)
            by_sample.setdefault((case_id, repetition), []).append(event)

        expected_keys = {
            (case_id, repetition, ordinal)
            for case_id in selected_cases
            for repetition in range(MEASURED_REPETITIONS)
            for ordinal in range(CASE_SPECS[case_id].epochs)
        }
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            raise ValueError(f"epoch matrix mismatch: missing={missing} extra={extra}")

        for pair, sample in sample_by_pair.items():
            case_id, repetition = pair
            spec = CASE_SPECS[case_id]
            events = sorted(
                by_sample.get(pair, []), key=lambda event: event["epoch"]
            )
            if spec.kind != "epoch":
                if events:
                    raise ValueError(f"non-epoch sample {pair} has epoch events")
                continue
            sums = {
                "entries": 0,
                "unique": 0,
                "duplicates": 0,
                "missing": 0,
                "extra": 0,
                "guest_cycles": 0,
                "instret": 0,
                "end_to_end_cycles": 0,
                **{metric: 0 for metric in PHASE_METRICS},
            }
            for ordinal, event in enumerate(events):
                start = (ordinal * spec.epoch_stride) & 127
                bitmap = [0, 0]
                for index in range(spec.epoch_touched):
                    page = (start + index) & 127
                    bitmap[page >> 6] |= 1 << (page & 63)
                ctl = ((sample["ctl_base"] >> 12) << 10) | (
                    spec.log_size << 1
                )
                expected_fields = {
                    "case": spec.name,
                    "id": case_id,
                    "rep": repetition,
                    "epoch": ordinal,
                    "expected": spec.epoch_touched,
                    "idx_before": spec.epoch_touched,
                    "idx_after": 0,
                    "entries": spec.epoch_touched,
                    "unique": spec.epoch_touched,
                    "duplicates": 0,
                    "missing": 0,
                    "extra": 0,
                    "bitmap0": bitmap[0],
                    "bitmap1": bitmap[1],
                    "pte_missing": 0,
                    "pte_extra": 0,
                    "pte_after_clear": 0,
                    "data_errors": 0,
                    "control_errors": 0,
                    "traps": 0,
                    "frozen_ctl": ctl,
                    "resumed_ctl": ctl | 1,
                    "status": 0,
                }
                for key, expected in expected_fields.items():
                    if event.get(key) != expected:
                        raise ValueError(
                            f"epoch {case_id}/{repetition}/{ordinal} {key}="
                            f"{event.get(key)!r}, expected {expected!r}"
                        )
                phase_values = [
                    _required_int(event, metric, "DIRTYGEN_EPOCH")
                    for metric in PHASE_METRICS
                ]
                guest = _required_int(event, "guest_cycles", "DIRTYGEN_EPOCH")
                guest_instret = _required_int(
                    event, "guest_instret", "DIRTYGEN_EPOCH"
                )
                end_to_end = _required_int(
                    event, "end_to_end_cycles", "DIRTYGEN_EPOCH"
                )
                if guest == 0 or guest_instret == 0 or any(
                    value == 0 for value in phase_values
                ):
                    raise ValueError(
                        f"epoch {case_id}/{repetition}/{ordinal} has zero cycle segment"
                    )
                if end_to_end < guest + sum(phase_values):
                    raise ValueError(
                        f"epoch {case_id}/{repetition}/{ordinal} segment sum mismatch"
                    )
                for key in ("entries", "unique", "duplicates", "missing", "extra"):
                    sums[key] += event[key]
                sums["guest_cycles"] += guest
                sums["instret"] += guest_instret
                sums["end_to_end_cycles"] += end_to_end
                for metric, value in zip(PHASE_METRICS, phase_values):
                    sums[metric] += value

            expected_sample_sums = {
                "epochs": len(events),
                "drained": sums["entries"],
                "cycles": sums["end_to_end_cycles"],
                **sums,
            }
            for key, expected in expected_sample_sums.items():
                actual = _required_int(sample, key, "DIRTYGEN_SAMPLE")
                if actual != expected:
                    raise ValueError(
                        f"sample {pair} {key}={actual}, epoch sum={expected}"
                    )

    def _validate_summaries(
        self, by_case: dict[int, list[dict[str, Any]]],
        selected_cases: range,
        is_v5: bool,
    ) -> None:
        summary_ids: set[int] = set()
        for summary in self.summaries:
            case_id = _required_int(summary, "id", "DIRTYGEN_SUMMARY")
            if case_id in summary_ids:
                raise ValueError(f"duplicate summary id: {case_id}")
            if case_id not in selected_cases:
                raise ValueError(f"summary has out-of-range case id {case_id}")
            summary_ids.add(case_id)
            if summary.get("case") != CASE_SPECS[case_id].name:
                raise ValueError(f"summary case name mismatch for id {case_id}")
            if _required_int(summary, "status", "DIRTYGEN_SUMMARY") != 0:
                raise ValueError(f"summary {case_id} has nonzero status")
            samples = by_case[case_id]
            metrics = SUMMARY_METRICS if is_v5 else V4_SUMMARY_METRICS
            for metric in metrics:
                values = [
                    _required_int(sample, metric, "DIRTYGEN_SAMPLE")
                    for sample in samples
                ]
                expected = (min(values), _median(values), max(values))
                actual = tuple(
                    _required_int(
                        summary, f"{metric}_{suffix}", "DIRTYGEN_SUMMARY"
                    )
                    for suffix in ("min", "median", "max")
                )
                if actual != expected:
                    raise ValueError(
                        f"summary {case_id} {metric}={actual}, expected {expected}"
                    )
        if summary_ids != set(selected_cases):
            raise ValueError(f"summary id set mismatch: {sorted(summary_ids)}")

    def summary_rows(self) -> list[dict[str, Any]]:
        first_sample = {sample["id"]: sample for sample in self.samples}
        rows: list[dict[str, Any]] = []
        for summary in sorted(self.summaries, key=lambda item: item["id"]):
            sample = first_sample[summary["id"]]
            case_samples = [
                item for item in self.samples if item["id"] == summary["id"]
            ]
            stores = sample["stores"]
            entries = sample["entries"]
            median = summary["cycles_median"]
            lifecycle_values = [
                sum(item.get(metric, 0) for metric in PHASE_METRICS)
                for item in case_samples
            ]
            transition_values = [
                item["end_to_end_cycles"] - item["guest_cycles"] - lifecycle
                for item, lifecycle in zip(case_samples, lifecycle_values)
            ]
            epochs = sample.get("epochs", 0)
            rows.append(
                {
                    "case": summary["case"],
                    "id": summary["id"],
                    "kind": CASE_SPECS[summary["id"]].kind,
                    "log_size": sample["log_size"],
                    "capacity": sample["capacity"],
                    "predirty": sample["predirty"],
                    "stores": stores,
                    "touched": sample["touched"],
                    "entries": entries,
                    "buffers": sample["buffers"],
                    "initial_idx": sample["initial_idx"],
                    "replacement_idx": sample["replacement_idx"],
                    "idx0": sample["idx0"],
                    "idx1": sample["idx1"],
                    "idx2": sample["idx2"],
                    "idx3": sample["idx3"],
                    "faults": sample["faults"],
                    "epochs": epochs,
                    "drained": sample.get("drained", 0),
                    "cycles_min": summary["cycles_min"],
                    "cycles_median": median,
                    "cycles_max": summary["cycles_max"],
                    "fault_cycles_median": summary["fault_cycles_median"],
                    "service_cycles_median": summary["service_cycles_median"],
                    "retry_cycles_median": summary["retry_cycles_median"],
                    "guest_cycles_median": summary["guest_cycles_median"],
                    "end_to_end_cycles_median": summary[
                        "end_to_end_cycles_median"
                    ],
                    "instret_median": summary["instret_median"],
                    "freeze_cycles_median": summary.get(
                        "freeze_cycles_median", 0
                    ),
                    "drain_cycles_median": summary.get(
                        "drain_cycles_median", 0
                    ),
                    "reset_cycles_median": summary.get(
                        "reset_cycles_median", 0
                    ),
                    "fence_cycles_median": summary.get(
                        "fence_cycles_median", 0
                    ),
                    "resume_cycles_median": summary.get(
                        "resume_cycles_median", 0
                    ),
                    "lifecycle_cycles_median": _median(lifecycle_values),
                    "transition_cycles_median": _median(transition_values),
                    "cycles_per_store": median / stores if stores else None,
                    "cycles_per_entry": median / entries if entries else None,
                    "cycles_per_epoch": median / epochs if epochs else None,
                    "drain_cycles_per_entry": (
                        summary.get("drain_cycles_median", 0) / entries
                        if entries else None
                    ),
                    "status": summary["status"],
                }
            )
        return rows


def parse_lines(lines: Iterable[str]) -> DirtygenReport:
    report = DirtygenReport()
    for line in lines:
        parsed = _parse_record(line)
        if parsed is None:
            continue
        kind, fields = parsed
        if kind == "begin":
            if report.begin is not None:
                raise ValueError("duplicate DIRTYGEN_BEGIN")
            report.begin = fields
        elif kind == "sample":
            report.samples.append(fields)
        elif kind == "fault":
            report.faults.append(fields)
        elif kind == "epoch":
            report.epochs.append(fields)
        elif kind == "summary":
            report.summaries.append(fields)
        elif kind == "error":
            report.errors.append(fields)
        elif kind == "end":
            if report.end is not None:
                raise ValueError("duplicate DIRTYGEN_END")
            report.end = fields
        else:
            raise ValueError(f"unknown dirtygen record type: {kind!r}")
    return report


def _format_ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def emit_table(report: DirtygenReport, output: TextIO) -> None:
    rows = report.summary_rows()
    output.write("workload cases\n")
    output.write(
        "case               predirty entries stores  cycles_med cyc/store instret_med\n"
    )
    for row in rows:
        if row["kind"] != "workload":
            continue
        output.write(
            f"{row['case']:<18} {row['predirty']:<8} {row['entries']:<7} "
            f"{row['stores']:<7} {row['cycles_median']:<10} "
            f"{_format_ratio(row['cycles_per_store']):<9} {row['instret_median']}\n"
        )

    output.write("\nboundary and replacement cases\n")
    output.write(
        "case                       sz cap  bufs idx0 idx1 idx2 idx3 faults entries "
        "cycles_med fault_med service_med retry_med guest_med\n"
    )
    for row in rows:
        if row["kind"] in ("workload", "epoch"):
            continue
        output.write(
            f"{row['case']:<26} {row['log_size']:<2} {row['capacity']:<4} "
            f"{row['buffers']:<4} {row['idx0']:<4} {row['idx1']:<4} "
            f"{row['idx2']:<4} {row['idx3']:<4} {row['faults']:<6} "
            f"{row['entries']:<7} {row['cycles_median']:<10} "
            f"{row['fault_cycles_median']:<9} "
            f"{row['service_cycles_median']:<11} "
            f"{row['retry_cycles_median']:<9} {row['guest_cycles_median']}\n"
        )

    output.write("\ndrain/reuse epoch cases\n")
    output.write(
        "case                     epochs entries cycles_med cyc/epoch "
        "freeze_med drain_med reset_med fence_med resume_med lifecycle_med "
        "transition_med\n"
    )
    for row in rows:
        if row["kind"] != "epoch":
            continue
        output.write(
            f"{row['case']:<24} {row['epochs']:<6} {row['entries']:<7} "
            f"{row['cycles_median']:<10} "
            f"{_format_ratio(row['cycles_per_epoch']):<9} "
            f"{row['freeze_cycles_median']:<10} "
            f"{row['drain_cycles_median']:<9} "
            f"{row['reset_cycles_median']:<9} "
            f"{row['fence_cycles_median']:<9} "
            f"{row['resume_cycles_median']:<10} "
            f"{row['lifecycle_cycles_median']:<13} "
            f"{row['transition_cycles_median']}\n"
        )


def emit_csv(report: DirtygenReport, output: TextIO) -> None:
    rows = report.summary_rows()
    fieldnames = list(rows[0]) if rows else []
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


def emit_json(report: DirtygenReport, output: TextIO) -> None:
    json.dump(
        {
            "begin": report.begin,
            "end": report.end,
            "samples": report.samples,
            "faults": report.faults,
            "epochs": report.epochs,
            "summaries": report.summaries,
            "rows": report.summary_rows(),
        },
        output,
        indent=2,
        sort_keys=True,
    )
    output.write("\n")


def _open_input(path: str) -> TextIO:
    if path == "-":
        return sys.stdin
    return Path(path).open("r", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="Mill log or '-' for stdin")
    parser.add_argument(
        "--format", choices=("table", "csv", "json"), default="table"
    )
    args = parser.parse_args(argv)

    try:
        input_file = _open_input(args.input)
        try:
            report = parse_lines(input_file)
        finally:
            if input_file is not sys.stdin:
                input_file.close()
        report.validate()
        if args.format == "csv":
            emit_csv(report, sys.stdout)
        elif args.format == "json":
            emit_json(report, sys.stdout)
        else:
            emit_table(report, sys.stdout)
    except (OSError, ValueError) as error:
        print(f"dirtygen_report: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
