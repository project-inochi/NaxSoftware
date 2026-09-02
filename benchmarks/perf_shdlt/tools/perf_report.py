#!/usr/bin/env python3
"""Strict parser, aggregator, and baseline comparator for perf_shdlt."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

WARMUP = 5
MEASURED = 63
TOTAL = WARMUP + MEASURED

ARCH_METRICS = (
    "cycles", "instret", "first_touch_cycles", "steady_cycles",
    "guest_cycles", "service_cycles", "freeze_cycles", "drain_cycles",
    "freeze_total_cycles", "recovery_cycles", "end_to_end_cycles",
)
OBSERVER_METRICS = (
    "first_d_update_cycles", "fault_detection_cycles",
    "observer_recovery_cycles", "retry_store_cycles",
    "pte_cas_attempt_cycles", "pte_cas_transaction_cycles",
    "dirty_log_append_cycles", "store_issue_to_log_cmd_cycles",
    "log_rsp_to_cas_cmd_cycles", "coherence_retry_count",
    "cas_attempt", "cas_redo", "cas_mismatch", "cas_success", "log_write",
    "tlb_hit", "tlb_miss", "tlb_refill", "acquire", "probe", "release",
    "writeback", "grant", "grant_ack", "stall_a", "stall_b", "stall_c",
    "stall_d", "stall_e",
)
HPM_EVENT_NAMES = {
    0x30: "shdlt_d_transition",
    0x31: "shdlt_log_append",
    0x32: "shdlt_pte_cas_attempt",
    0x33: "shdlt_pte_cas_retry",
    0x34: "shdlt_log_fault",
    0x35: "shdlt_hfence_gvma",
    0x36: "shdlt_shadow_tlb_refill",
    0x37: "shdlt_shadow_tlb_invalidate",
    0x38: "lsu_store_access",
    0x39: "lsu_store_miss",
    0x3A: "lsu_coherence_retry",
    0x3B: "mmu_tlb_refill",
    0x3C: "mmu_tlb_miss",
    0x3D: "shdlt_update_busy_cycles",
    0x3E: "shdlt_log_busy_cycles",
    0x3F: "shdlt_cas_busy_cycles",
}
HPM_METRICS = tuple(f"hpm_{name}" for name in HPM_EVENT_NAMES.values())
HPM_ABI_VERSION = 1
HPM_SCHEMA_VERSION = 1
HPM_SLOT_COUNT = 4
GATE_METRICS = (
    "cycles_per_store", "first_d_update_cycles",
    "pte_cas_transaction_cycles", "dirty_log_append_cycles",
    "service_cycles", "freeze_total_cycles", "end_to_end_cycles",
)
CONFIG_KEYS = (
    "profile", "cache", "seed", "ready", "latency", "cpus", "suite",
    "logger", "order", "phase_mode", "scaling", "case", "hpm",
    "hpm_backend", "hpm_schema_version", "hpm_event_mask", "hpm_event0",
    "hpm_event1", "hpm_event2", "hpm_event3",
)


class ReportError(RuntimeError):
    pass


def parse_number(value: str) -> int:
    return int(value, 16 if value.lower().startswith("0x") else 10)


def parse_fields(line: str) -> dict[str, int | str]:
    fields: dict[str, int | str] = {}
    for token in line.strip().split()[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        try:
            fields[key] = parse_number(value)
        except ValueError:
            fields[key] = value
    return fields


def nearest_rank(values: list[float], percent: int) -> float:
    if not values:
        raise ReportError("percentile of empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * percent / 100.0))
    return ordered[rank - 1]


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    return {
        "count": len(values),
        "min": min(values),
        "median": median,
        "p95": nearest_rank(values, 95),
        "max": max(values),
        "mad": statistics.median(deviations),
    }


def latency_average(observer: dict[str, int | str], prefix: str) -> float:
    count = int(observer.get(f"{prefix}_count", 0))
    total = int(observer.get(f"{prefix}_sum", 0))
    return total / count if count else 0.0


def _hpm_event_mask(meta: dict[str, int | str]) -> int:
    """Return the slot mask advertised by HPM metadata.

    The mask is deliberately a slot mask (not an event-id bitset): this keeps
    the ABI usable when a backend multiplexes or renumbers physical counters.
    """
    slots = int(meta.get("slots", 0))
    mask = int(meta.get("event_mask", 0))
    if slots < 1 or slots > HPM_SLOT_COUNT:
        raise ReportError(f"invalid HPM slot count {slots}")
    expected = (1 << slots) - 1
    if mask != expected:
        raise ReportError(
            f"HPM metadata event_mask=0x{mask:x} does not match slots={slots}"
        )
    return mask


def _validate_hpm_meta(meta: dict[str, int | str]) -> int:
    if int(meta.get("abi_version", 0)) != HPM_ABI_VERSION:
        raise ReportError("unsupported HPM ABI")
    if int(meta.get("schema_version", 0)) != HPM_SCHEMA_VERSION:
        raise ReportError("unsupported HPM schema")
    # Backend is part of the measurement identity.  Firmware CSR (1) and a
    # future Linux perf adapter (2) may expose the same event IDs, but their
    # timing domains and availability semantics must not be compared as one
    # baseline.
    backend = int(meta.get("backend", 0))
    if backend not in (1, 2):
        raise ReportError(f"unsupported HPM backend {backend}")
    mask = _hpm_event_mask(meta)
    # A slot group is a descriptor, not an implementation trace.  Reject an
    # ambiguous group up front so two counters cannot silently represent the
    # same event (which would make cross-backend comparisons meaningless).
    seen: set[int] = set()
    for slot in range(HPM_SLOT_COUNT):
        if not (mask & (1 << slot)):
            continue
        key = f"event{slot}"
        if key not in meta:
            raise ReportError(f"HPM metadata missing {key}")
        event_id = int(meta[key])
        if event_id < 0 or event_id > 0xFFFF:
            raise ReportError(f"HPM metadata {key}=0x{event_id:x} out of range")
        if event_id in seen:
            raise ReportError(
                f"HPM metadata duplicate event id 0x{event_id:x} at {key}"
            )
        seen.add(event_id)
    return mask


def _validate_hpm_sample(item: dict[str, int | str], meta: dict[str, int | str],
                         path: Path, key: tuple[int, int, int], require_hpm: bool) -> None:
    if int(item.get("abi_version", 0)) != HPM_ABI_VERSION:
        raise ReportError(f"{path}: sample {key} unsupported HPM ABI")
    if int(item.get("schema_version", 0)) != HPM_SCHEMA_VERSION:
        raise ReportError(f"{path}: sample {key} unsupported HPM schema")
    expected_mask = _hpm_event_mask(meta)
    event_mask = int(item.get("event_mask", -1))
    available_mask = int(item.get("available_mask", -1))
    if event_mask != expected_mask:
        raise ReportError(
            f"{path}: HPM sample {key} event_mask=0x{event_mask:x} "
            f"expected 0x{expected_mask:x}"
        )
    if available_mask < 0 or available_mask & ~event_mask:
        raise ReportError(f"{path}: HPM sample {key} invalid available_mask")
    if require_hpm and available_mask != event_mask:
        raise ReportError(
            f"{path}: HPM sample {key} unavailable selected counter(s) "
            f"mask=0x{available_mask:x} expected=0x{event_mask:x}"
        )
    enabled = int(item.get("time_enabled", -1))
    running = int(item.get("time_running", -1))
    if enabled < 0 or running < 0 or enabled < running:
        raise ReportError(f"{path}: HPM sample {key} invalid time_enabled/time_running")

    # A hardware or Linux PMU may be unable to schedule one or more selected
    # events.  Such a sample is still useful to the architecture-only report as
    # long as the producer advertises the unavailable mask (and, for a stopped
    # group, time_running=0).  Strict HPM mode remains intentionally lossless:
    # every selected slot must run and the sample status must be zero.
    unavailable = available_mask != event_mask or running == 0
    status = int(item.get("status", 1))
    if status < 0 or status > 1:
        raise ReportError(f"{path}: HPM sample {key} invalid status={status}")
    if require_hpm and (unavailable or status != 0):
        raise ReportError(
            f"{path}: HPM sample {key} unavailable/failed status={status} "
            f"available=0x{available_mask:x} running={running}"
        )
    if status != 0 and not unavailable:
        raise ReportError(f"{path}: HPM sample {key} status={status}")

    seen_ids: set[int] = set()
    for slot in range(HPM_SLOT_COUNT):
        bit = 1 << slot
        event_id = int(item.get(f"event{slot}", 0))
        expected_id = int(meta.get(f"event{slot}", 0))
        if bit & event_mask and event_id != expected_id:
            raise ReportError(
                f"{path}: HPM sample {key} event{slot}=0x{event_id:x} "
                f"does not match metadata 0x{expected_id:x}"
            )
        if bit & available_mask:
            if event_id in seen_ids:
                raise ReportError(f"{path}: HPM sample {key} duplicate event id 0x{event_id:x}")
            seen_ids.add(event_id)
            if int(item.get(f"value{slot}", -1)) < 0:
                raise ReportError(f"{path}: HPM sample {key} missing value{slot}")


def _merge_hpm_row(row: dict[str, int | str], item: dict[str, int | str]) -> None:
    """Expose HPM values under stable event-name fields in a report row."""
    row["hpm_schema_version"] = int(item.get("schema_version", 0))
    row["hpm_event_mask"] = int(item.get("event_mask", 0))
    row["hpm_available_mask"] = int(item.get("available_mask", 0))
    row["hpm_time_enabled"] = int(item.get("time_enabled", 0))
    row["hpm_time_running"] = int(item.get("time_running", 0))
    available = int(item.get("available_mask", 0))
    for slot in range(HPM_SLOT_COUNT):
        row[f"hpm_event{slot}"] = int(item.get(f"event{slot}", 0))
        if not (available & (1 << slot)):
            continue
        event_id = int(item.get(f"event{slot}", 0))
        value = int(item.get(f"value{slot}", 0))
        name = HPM_EVENT_NAMES.get(event_id, f"raw_0x{event_id:02x}")
        row[f"hpm_{name}"] = value


def load_log(path: Path, require_observer: bool = False,
             require_hpm: bool = False) -> dict:
    run: dict[str, int | str] = {}
    meta: dict[str, int | str] | None = None
    result: dict[str, int | str] | None = None
    samples: dict[tuple[int, int, int], dict[str, int | str]] = {}
    observers: dict[tuple[int, int, int], dict[str, int | str]] = {}
    global_observers: dict[tuple[int, int], dict[str, int | str]] = {}
    hpm_meta: dict[str, int | str] | None = None
    hpm_samples: dict[tuple[int, int, int], dict[str, int | str]] = {}

    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            if line.startswith("SHDLT_PERF_RUN "):
                if run:
                    raise ReportError(f"{path}: duplicate SHDLT_PERF_RUN")
                run = parse_fields(line)
            elif line.startswith("SHDLT_PERF_META "):
                if meta is not None:
                    raise ReportError(f"{path}: duplicate SHDLT_PERF_META")
                meta = parse_fields(line)
            elif line.startswith("SHDLT_PERF_SAMPLE "):
                item = parse_fields(line)
                key = (int(item["case"]), int(item["sample"]), int(item["hart"]))
                if key in samples:
                    raise ReportError(f"{path}: duplicate sample {key}")
                samples[key] = item
            elif line.startswith("SHDLT_PERF_OBSERVER_GLOBAL "):
                item = parse_fields(line)
                key = (int(item["case"]), int(item["sample"]))
                if key in global_observers:
                    raise ReportError(f"{path}: duplicate global observer {key}")
                global_observers[key] = item
            elif line.startswith("SHDLT_PERF_OBSERVER "):
                item = parse_fields(line)
                key = (int(item["case"]), int(item["sample"]), int(item["hart"]))
                if key in observers:
                    raise ReportError(f"{path}: duplicate observer {key}")
                observers[key] = item
            elif line.startswith("SHDLT_HPM_META "):
                if hpm_meta is not None:
                    raise ReportError(f"{path}: duplicate SHDLT_HPM_META")
                hpm_meta = parse_fields(line)
            elif line.startswith("SHDLT_HPM_SAMPLE "):
                item = parse_fields(line)
                key = (int(item["case"]), int(item["sample"]), int(item["hart"]))
                if key in hpm_samples:
                    raise ReportError(f"{path}: duplicate HPM sample {key}")
                hpm_samples[key] = item
            elif line.startswith("SHDLT_PERF_RESULT "):
                if result is not None:
                    raise ReportError(f"{path}: duplicate SHDLT_PERF_RESULT")
                result = parse_fields(line)

    if meta is None or result is None:
        raise ReportError(f"{path}: missing META or RESULT")
    if int(meta.get("abi_version", 0)) != 1 or int(result.get("abi_version", 0)) != 1:
        raise ReportError(f"{path}: unsupported ABI")
    if int(result.get("status", 1)) != 0 or int(result.get("failures", 1)) != 0:
        raise ReportError(f"{path}: firmware reported failure: {result}")
    cpus = int(meta["cpus"])
    cases = sorted({key[0] for key in samples})
    if not cases:
        raise ReportError(f"{path}: no samples")
    hpm_enabled = hpm_meta is not None or bool(hpm_samples)
    hpm_mask = None
    if hpm_enabled:
        if hpm_meta is None:
            raise ReportError(f"{path}: HPM samples present without HPM_META")
        hpm_mask = _validate_hpm_meta(hpm_meta)
        for key, item in hpm_samples.items():
            _validate_hpm_sample(item, hpm_meta, path, key, require_hpm)
        if set(hpm_samples) != set(samples):
            missing = sorted(set(samples) - set(hpm_samples))
            extra = sorted(set(hpm_samples) - set(samples))
            raise ReportError(
                f"{path}: HPM/sample mismatch missing={missing[:4]} extra={extra[:4]}"
            )
    elif require_hpm:
        raise ReportError(f"{path}: missing HPM_META/SAMPLE records")
    for case in cases:
        for hart in range(cpus):
            ids = sorted(key[1] for key in samples if key[0] == case and key[2] == hart)
            if ids != list(range(TOTAL)):
                raise ReportError(f"{path}: case {case} hart {hart} sample ids {ids}")
    for key, sample in samples.items():
        expected_warmup = int(key[1] < WARMUP)
        if int(sample.get("warmup", -1)) != expected_warmup:
            raise ReportError(f"{path}: bad warmup flag for {key}")
        if int(sample.get("status", 1)) != 0:
            raise ReportError(f"{path}: sample {key} status={sample.get('status')}")
        for counter in ("cycles", "instret", "end_to_end_cycles"):
            if int(sample.get(counter, 0)) <= 0:
                raise ReportError(f"{path}: sample {key} invalid {counter}")
        if require_observer and key not in observers:
            raise ReportError(f"{path}: sample {key} missing observer")
        if hpm_enabled and key not in hpm_samples:
            raise ReportError(f"{path}: sample {key} missing HPM sample")
    if require_observer and set(observers) != set(samples):
        extra = sorted(set(observers) - set(samples))
        raise ReportError(f"{path}: observer/sample mismatch, extra={extra[:4]}")

    rows = []
    for key, sample in sorted(samples.items()):
        row = dict(run)
        row.update(sample)
        # Old logs predate the explicit run-level HPM mode.  Derive a stable
        # value so they remain parseable without conflating them with a
        # complete HPM campaign.
        row.setdefault("hpm", "on" if hpm_enabled else "off")
        row.setdefault("hpm_backend", "none")
        row.setdefault("hpm_schema_version", 0)
        row.setdefault("hpm_event_mask", 0)
        for slot in range(HPM_SLOT_COUNT):
            row.setdefault(f"hpm_event{slot}", 0)
        observer = observers.get(key, {})
        if hpm_enabled:
            _merge_hpm_row(row, hpm_samples[key])
            row["hpm_backend"] = int(hpm_meta.get("backend", 0))
        row["observer_available_mask"] = int(observer.get("available_mask", 0))
        row["observer_valid_mask"] = int(observer.get("valid_mask", 0))
        valid = row["observer_valid_mask"]
        if valid & 0x02:
            row["first_d_update_cycles"] = int(observer.get("first_d_update_cycles", 0))
            row["cas_attempt"] = int(observer.get("cas_attempt", 0))
            row["cas_redo"] = int(observer.get("cas_redo", 0))
            row["cas_mismatch"] = int(observer.get("cas_mismatch", 0))
            row["cas_success"] = int(observer.get("cas_success", 0))
            row["pte_cas_attempt_cycles"] = latency_average(observer, "cas_attempt_cycles")
            row["pte_cas_transaction_cycles"] = latency_average(observer, "cas_transaction_cycles")
        if valid & 0x04:
            row["log_write"] = int(observer.get("log_write", 0))
            row["dirty_log_append_cycles"] = latency_average(observer, "append_cycles")
            row["store_issue_to_log_cmd_cycles"] = latency_average(observer, "store_to_log_cycles")
            row["log_rsp_to_cas_cmd_cycles"] = latency_average(observer, "log_to_cas_cycles")
        if valid & 0x08:
            row["fault_detection_cycles"] = int(observer.get("fault_detection_cycles", 0))
            row["observer_recovery_cycles"] = int(observer.get("recovery_cycles", 0))
            row["retry_store_cycles"] = int(observer.get("retry_store_cycles", 0))
        if valid & 0x10:
            for name in (
                "coherence_retry_count", "tlb_hit", "tlb_miss", "tlb_refill",
                "acquire", "probe", "release", "writeback", "grant", "grant_ack",
                "stall_a", "stall_b", "stall_c", "stall_d", "stall_e",
            ):
                row[name] = int(observer.get(name, 0))
        stores = int(row.get("stores", 0))
        entries = int(row.get("entries", 0))
        row["cycles_per_store"] = int(row["cycles"]) / stores if stores else 0.0
        row["instret_per_store"] = int(row["instret"]) / stores if stores else 0.0
        row["cycles_per_entry"] = int(row["cycles"]) / entries if entries else 0.0
        rows.append(row)
    return {
        "path": str(path), "run": run, "meta": meta, "result": result,
        "rows": rows, "global_observers": list(global_observers.values()),
        "hpm_meta": hpm_meta, "hpm_samples": hpm_samples,
        "hpm_enabled": hpm_enabled, "hpm_event_mask": hpm_mask,
    }


def config_key(row: dict) -> tuple:
    return tuple(row.get(key, "unknown") for key in CONFIG_KEYS)


def aggregate(logs: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for log in logs:
        for row in log["rows"]:
            if int(row["warmup"]) == 0:
                grouped[config_key(row)].append(row)
    output = []
    metrics = ARCH_METRICS + OBSERVER_METRICS + HPM_METRICS + (
        "cycles_per_store", "instret_per_store", "cycles_per_entry",
    )
    for key, rows in sorted(grouped.items(), key=lambda item: repr(item[0])):
        item = {name: value for name, value in zip(CONFIG_KEYS, key)}
        item["sample_count"] = len(rows)
        item["hart_count"] = len({int(row["hart"]) for row in rows})
        for metric in metrics:
            values = [float(row[metric]) for row in rows if metric in row]
            item[metric] = summarize(values)
        per_hart = defaultdict(list)
        for row in rows:
            per_hart[int(row["hart"])].append(float(row["cycles"]))
        hart_medians = [statistics.median(values) for values in per_hart.values()]
        if hart_medians:
            total = sum(hart_medians)
            square_sum = sum(value * value for value in hart_medians)
            item["hart_skew"] = max(hart_medians) - min(hart_medians)
            item["jain_fairness"] = (total * total) / (len(hart_medians) * square_sum) if square_sum else 1.0
        output.append(item)
    add_comparisons(output)
    return output


def median_of(item: dict, metric: str) -> float | None:
    summary = item.get(metric, {})
    return float(summary["median"]) if summary.get("count", 0) else None


def compatible(left: dict, right: dict, ignored: set[str]) -> bool:
    return all(left.get(key) == right.get(key) for key in CONFIG_KEYS
               if key not in ignored)


def add_comparisons(items: list[dict]) -> None:
    for item in items:
        item["logger_overhead_percent"] = None
        item["coherent_overhead_percent"] = None
        item["speedup_vs_1hart"] = None
        item["scaling_efficiency"] = None
        cycles = median_of(item, "cycles_per_store")
        if cycles is None or cycles <= 0:
            continue
        for candidate in items:
            candidate_cycles = median_of(candidate, "cycles_per_store")
            if candidate_cycles is None or candidate_cycles <= 0:
                continue
            if int(item.get("logger", 0)) == 1 and int(candidate.get("logger", 1)) == 0 and \
                    compatible(item, candidate, {"logger"}):
                item["logger_overhead_percent"] = (cycles / candidate_cycles - 1.0) * 100.0
            if int(item.get("cpus", 0)) == 1 and item.get("cache") == "coherent_l1" and \
                    candidate.get("cache") == "l1" and compatible(item, candidate, {"cache"}):
                item["coherent_overhead_percent"] = (cycles / candidate_cycles - 1.0) * 100.0
            if int(candidate.get("cpus", 0)) == 1 and compatible(item, candidate, {"cpus"}):
                speedup = candidate_cycles / cycles
                item["speedup_vs_1hart"] = speedup
                item["scaling_efficiency"] = speedup / int(item.get("cpus", 1))


def baseline_fingerprint(logs: list[dict]) -> dict:
    values = defaultdict(set)
    for log in logs:
        for key in ("profile", "cache", "seed", "ready", "latency"):
            values[key].add(str(log["run"].get(key, "unknown")))
        values["abi_version"].add(str(log["meta"].get("abi_version", "unknown")))
        values["hpm_enabled"].add(str(bool(log.get("hpm_enabled", False))))
        if log.get("hpm_meta") is not None:
            hpm_meta = log["hpm_meta"]
            values["hpm_backend"].add(str(hpm_meta.get("backend", "unknown")))
            values["hpm_schema_version"].add(
                str(hpm_meta.get("schema_version", "unknown"))
            )
            values["hpm_event_mask"].add(
                str(hpm_meta.get("event_mask", "unknown"))
            )
            for slot in range(HPM_SLOT_COUNT):
                values[f"hpm_event{slot}"].add(
                    str(hpm_meta.get(f"event{slot}", "unknown"))
                )
    return {key: sorted(data) for key, data in values.items()}


def baseline_document(logs: list[dict], summaries: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "fingerprint": baseline_fingerprint(logs),
        "summaries": summaries,
    }


def compare_baseline(current: dict, baseline: dict, threshold: float | None) -> list[str]:
    if current.get("schema_version") != baseline.get("schema_version"):
        raise ReportError("baseline schema mismatch")
    old_by_key = {tuple(item.get(key) for key in CONFIG_KEYS): item
                  for item in baseline["summaries"]}
    regressions = []
    for item in current["summaries"]:
        key = tuple(item.get(name) for name in CONFIG_KEYS)
        old = old_by_key.get(key)
        if old is None:
            continue
        for metric in GATE_METRICS:
            for statistic_name in ("median", "p95"):
                new_summary = item.get(metric, {})
                old_summary = old.get(metric, {})
                if not new_summary.get("count") or not old_summary.get("count"):
                    continue
                old_value = float(old_summary[statistic_name])
                new_value = float(new_summary[statistic_name])
                if old_value == 0:
                    continue
                change = (new_value / old_value - 1.0) * 100.0
                if threshold is not None and change > threshold:
                    regressions.append(
                        f"{key} {metric}.{statistic_name} regressed {change:.2f}%"
                    )
    return regressions


def write_outputs(output_dir: Path, logs: list[dict], summaries: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "samples.jsonl").open("w", encoding="utf-8") as stream:
        for log in logs:
            for row in log["rows"]:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
    document = baseline_document(logs, summaries)
    (output_dir / "summary.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    flat_rows = []
    for item in summaries:
        flat = {key: item.get(key) for key in CONFIG_KEYS}
        flat["sample_count"] = item["sample_count"]
        for metric in ARCH_METRICS + OBSERVER_METRICS + HPM_METRICS + ("cycles_per_store",):
            summary = item.get(metric, {})
            for name in ("count", "min", "median", "p95", "max", "mad"):
                flat[f"{metric}_{name}"] = summary.get(name)
        for name in ("logger_overhead_percent", "coherent_overhead_percent",
                     "speedup_vs_1hart", "scaling_efficiency", "hart_skew",
                     "jain_fairness"):
            flat[name] = item.get(name)
        flat_rows.append(flat)
    if flat_rows:
        with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(flat_rows[0]))
            writer.writeheader()
            writer.writerows(flat_rows)
    has_hpm = any(
        item.get(metric, {}).get("count", 0)
        for item in summaries for metric in HPM_METRICS
    )
    with (output_dir / "summary.md").open("w", encoding="utf-8") as stream:
        columns = [
            "profile", "cache", "cpus", "case", "logger", "order", "phase",
            "scaling", "cycles/store median", "p95",
        ]
        if has_hpm:
            columns.extend([
                "D transitions median", "log appends median",
                "CAS retries median", "log faults median",
            ])
        stream.write("| " + " | ".join(columns) + " |\n")
        stream.write("|" + "|".join("---:" if i >= 2 else "---" for i in range(len(columns))) + "|\n")
        for item in summaries:
            metric = item["cycles_per_store"]
            values = [
                item.get("profile"), item.get("cache"), item.get("cpus"),
                item.get("case"), item.get("logger"), item.get("order"),
                item.get("phase_mode"), item.get("scaling"),
                f"{metric.get('median', 0):.3f}", f"{metric.get('p95', 0):.3f}",
            ]
            if has_hpm:
                for event_name in (
                    "hpm_shdlt_d_transition", "hpm_shdlt_log_append",
                    "hpm_shdlt_pte_cas_retry", "hpm_shdlt_log_fault",
                ):
                    values.append(f"{median_of(item, event_name) or 0:.3f}")
            stream.write("| " + " | ".join(str(value) for value in values) + " |\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument(
        "--require-observer", action="store_true",
        help="require the legacy simulation-only observer records",
    )
    parser.add_argument(
        "--require-hpm", action="store_true",
        help="require complete portable HPM metadata and one sample per architecture sample",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--baseline-out", type=Path)
    parser.add_argument("--compare-baseline", type=Path)
    parser.add_argument("--max-regression-percent", type=float)
    args = parser.parse_args(argv)
    try:
        logs = [load_log(path, args.require_observer, args.require_hpm) for path in args.logs]
        summaries = aggregate(logs)
        document = baseline_document(logs, summaries)
        if args.output_dir:
            write_outputs(args.output_dir, logs, summaries)
        if args.baseline_out:
            args.baseline_out.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        regressions = []
        if args.compare_baseline:
            baseline = json.loads(args.compare_baseline.read_text(encoding="utf-8"))
            regressions = compare_baseline(document, baseline, args.max_regression_percent)
        for log in logs:
            print(f"PASS {log['path']} samples={len(log['rows'])}")
        print(f"CAMPAIGN PASS logs={len(logs)} groups={len(summaries)}")
        for regression in regressions:
            print(f"REGRESSION {regression}", file=sys.stderr)
        return 1 if regressions else 0
    except (OSError, KeyError, ValueError, ReportError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
