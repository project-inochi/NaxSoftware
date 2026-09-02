#!/usr/bin/env python3
"""Check architectural SHDLT invariants from an existing run.

The checker intentionally consumes only committed architectural records.  It
does not infer or require a particular CAS/FIFO/cache implementation.  An
RVLS trace is optional diagnostic evidence; architecture-only backends can
still run the checks which are represented by the firmware ABI.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

try:
    from rtl_report import TraceSummary, parse_trace
except ModuleNotFoundError:  # direct invocation from the tools directory
    _spec = importlib.util.spec_from_file_location(
        "rtl_report", Path(__file__).with_name("rtl_report.py"))
    if _spec is None or _spec.loader is None:
        raise
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["rtl_report"] = _module
    _spec.loader.exec_module(_module)
    TraceSummary = _module.TraceSummary
    parse_trace = _module.parse_trace


INVARIANTS = (
    "d_transition_at_most_one_log_per_hart",
    "d_transition_all_required_harts_logged",
    "predirty_repeat_no_append",
    "logger_disabled_or_frozen_no_append",
    "index_within_capacity",
    "fault_no_invalid_entry",
    "cas_preserves_pte_bits",
    "hart_isolation",
    "retry_no_duplicate_architectural_commit",
)


class InvariantError(ValueError):
    pass


def _records(arch: Any) -> list[dict[str, Any]]:
    """Normalize one-family architectural report to a list of hart records."""
    if isinstance(arch, dict) and isinstance(arch.get("harts"), list):
        return [r for r in arch["harts"] if isinstance(r, dict)]
    if isinstance(arch, list):
        result: list[dict[str, Any]] = []
        for report in arch:
            if isinstance(report, dict):
                result.extend(r for r in report.get("harts", [])
                              if isinstance(r, dict))
        return result
    return []


def _nonzero(records: list[dict[str, Any]], *names: str) -> bool:
    return any(record.get(name, 0) != 0 for record in records for name in names)


def _check_arch(family: str, case: str, cpus: int, arch: Any,
                checks: dict[str, bool], violations: list[str]) -> None:
    records = _records(arch)
    if family in ("race", "ctc"):
        if len(records) != cpus:
            violations.append(f"architectural hart records={len(records)} expected={cpus}")
            for name in INVARIANTS:
                checks[name] = False
            return
        hart_ids = [int(r.get("hart", -1)) for r in records]
        if sorted(hart_ids) != list(range(cpus)):
            violations.append(f"architectural hart ownership={hart_ids} expected={list(range(cpus))}")
            for name in INVARIANTS:
                checks[name] = False
            return
        entries = [int(r.get("entries", 0)) for r in records]
        # A race on a single PTE may have one winner globally; all other
        # multicore cases must produce one transition per participating hart.
        shared_pte = family == "race" and case == "same_pte"
        cas_retry = (family == "ctc" and case == "cas_retry")
        single_pte = shared_pte or cas_retry
        checks["d_transition_at_most_one_log_per_hart"] = (
            all(e <= 1 for e in entries) if single_pte else True)
        if not checks["d_transition_at_most_one_log_per_hart"]:
            violations.append(f"per-hart entries exceed one: {entries}")
        checks["d_transition_all_required_harts_logged"] = (
            (sum(entries) >= 1 if shared_pte or cas_retry else all(e >= 1 for e in entries))
        )
        if not checks["d_transition_all_required_harts_logged"]:
            violations.append(f"missing required hart log: {entries}")
        checks["predirty_repeat_no_append"] = (
            all(e == 0 for e in entries) if case in ("predirty", "same_page") else True
        )
        checks["logger_disabled_or_frozen_no_append"] = True
        checks["index_within_capacity"] = all(
            int(r.get("initial", r.get("initial_index", 0))) <=
            int(r.get("final", r.get("final_index", 0))) <=
            int(r.get("entry_max", 512)) for r in records
        )
        checks["fault_no_invalid_entry"] = not _nonzero(
            records, "faults", "unexpected", "extra", "tail_writes")
        checks["cas_preserves_pte_bits"] = not _nonzero(records, "pte_errors")
        if family == "ctc":
            # A committed dirty transition may change only architectural A/D;
            # V, permissions, and PPN must remain byte-for-byte identical.
            checks["cas_preserves_pte_bits"] = checks["cas_preserves_pte_bits"] and all(
                ((int(r.get("pte_before", 0)) ^ int(r.get("pte_after", 0))) & ~0xC0) == 0
                for r in records)
        checks["hart_isolation"] = not _nonzero(
            records, "foreign", "buffer_errors", "result_errors", "isolation_errors")
        checks["retry_no_duplicate_architectural_commit"] = (
            not _nonzero(records, "duplicates") and
            (not single_pte or all(e <= 1 for e in entries)) and
            (not shared_pte or sum(entries) <= 1)
        )
        return

    if family == "dirtygen":
        if not isinstance(arch, dict):
            # Unlike the preserved smoke image, dirtygen has a complete
            # machine-readable architectural report.  Do not let a missing
            # report turn all of its quantified checks into vacuous truths.
            violations.append("dirtygen architectural report is missing")
            for name in INVARIANTS:
                checks[name] = False
            return
        samples = arch.get("samples", []) if isinstance(arch, dict) else []
        faults = arch.get("faults", []) if isinstance(arch, dict) else []
        epochs = arch.get("epochs", []) if isinstance(arch, dict) else []
        checks["d_transition_at_most_one_log_per_hart"] = True
        checks["d_transition_all_required_harts_logged"] = True
        checks["predirty_repeat_no_append"] = all(
            int(s.get("duplicates", 0)) == 0 for s in samples)
        checks["logger_disabled_or_frozen_no_append"] = all(
            not (("off" in str(s.get("case", "")) or
                  "frozen" in str(s.get("case", ""))) and
                 int(s.get("entries", 0))) for s in samples)
        # An overflow-fault case is deliberately initialized one past the
        # capacity to exercise the fault path.  That pre-existing invalid
        # control value is allowed only while the sample records a fault and no
        # architectural entry is committed; successful samples must never
        # advance any index beyond capacity.
        checks["index_within_capacity"] = all(
            (int(s.get("faults", 0)) and not int(s.get("entries", 0))) or
            all(0 <= int(s.get(f"idx{i}", 0)) <= int(s.get("capacity", 512))
                for i in range(4))
            for s in samples)
        checks["fault_no_invalid_entry"] = all(
            int(s.get("extra", 0)) == 0 and int(s.get("buffer_corruptions", 0)) == 0
            for s in samples) and all(
                int(f.get("index", 0)) >= 0 and int(f.get("scause", 0)) == 0x18
                for f in faults)
        checks["cas_preserves_pte_bits"] = all(
            int(s.get("pte_errors", 0)) == 0 for s in samples)
        checks["hart_isolation"] = True  # single-hart ABI; trace owns attribution
        checks["retry_no_duplicate_architectural_commit"] = (
            all(int(s.get("duplicates", 0)) == 0 for s in samples) and
            all(int(e.get("duplicates", 0)) == 0 for e in epochs)
        )
        return

    # smoke has no separate machine-readable architectural file in the
    # preserved images; its result structures are checked by the firmware before
    # --pass-policy all.  Trace count checks below provide the independent
    # invariant evidence.
    for name in INVARIANTS:
        checks[name] = True


def check_invariants(family: str, case: str, cpus: int,
                     trace: TraceSummary, arch: Any | None = None) -> dict[str, Any]:
    checks = {name: False for name in INVARIANTS}
    violations: list[str] = []
    trace_available = getattr(trace, "available", True)
    trace_checks_skipped: list[str] = []
    if trace_available:
        if trace.attribution_errors:
            violations.append(f"RVLS attribution_errors={trace.attribution_errors}")
        if trace.mmu_stores != trace.appends + trace.pte_updates:
            violations.append("MMU store classification does not balance")
        if trace.appends and trace.cpus != cpus:
            violations.append("append trace CPU count mismatch")
    else:
        # Do not turn unavailable diagnostics into trustworthy zero counts.
        # Architectural records are checked below; only these trace-specific
        # consistency checks are skipped.
        trace_checks_skipped = [
            "trace_balance", "trace_attribution", "trace_event_counts",
        ]
    _check_arch(family, case, cpus, arch, checks, violations)

    # Keep the evidence source explicit in machine-readable output.  This is
    # particularly important for the legacy smoke ELF: its UART records can
    # interleave, so the architecture result is established by the firmware's
    # RAM self-check plus TestBench's all-hart pass policy rather than by a
    # private observer trace.
    if arch is not None:
        architecture_evidence = "firmware-architecture-record"
    elif family == "smoke":
        architecture_evidence = "firmware-result+pass-policy-all"
    elif family == "csr":
        architecture_evidence = "firmware-csr-record+rtl-report"
    else:
        architecture_evidence = "missing"

    if family == "smoke":
        expected = {
            "load_only": (cpus, 0, cpus),
            "log_off": (cpus, 0, cpus),
            "predirty": (0, 0, 0),
            "widths": (8 * cpus, 4 * cpus, 4 * cpus),
            "nonzero_index": (4 * cpus, 2 * cpus, 2 * cpus),
            "freeze": (2 * cpus, cpus, cpus),
            "reset_resume": (4 * cpus, 2 * cpus, 2 * cpus),
        }
        if trace_available and case in expected:
            stores, appends, ptes = expected[case]
            if (trace.mmu_stores, trace.appends, trace.pte_updates) != (stores, appends, ptes):
                violations.append(
                    f"{case} committed events={(trace.mmu_stores, trace.appends, trace.pte_updates)} "
                    f"expected={(stores, appends, ptes)}")
        if trace_available:
            checks["d_transition_at_most_one_log_per_hart"] = trace.appends <= cpus * 4
            checks["d_transition_all_required_harts_logged"] = (
                case in ("load_only", "log_off", "predirty") or
                trace.appends >= cpus)
            checks["predirty_repeat_no_append"] = case != "predirty" or trace.appends == 0
            checks["logger_disabled_or_frozen_no_append"] = (
                case not in ("log_off", "freeze") or
                trace.appends == (0 if case == "log_off" else cpus))
            checks["index_within_capacity"] = True
            checks["fault_no_invalid_entry"] = trace.dirty_log_faults == 0
            checks["cas_preserves_pte_bits"] = True
            checks["hart_isolation"] = trace.attribution_errors == 0
            checks["retry_no_duplicate_architectural_commit"] = trace.appends <= 4 * cpus

    if trace_available and trace.attribution_errors:
        for name in ("hart_isolation", "fault_no_invalid_entry"):
            checks[name] = False
    failed = [name for name, passed in checks.items() if not passed]
    violations.extend(f"{name} failed" for name in failed if name not in violations)
    return {
        "abi": 1,
        "status": "PASS" if not violations else "FAIL",
        "family": family,
        "case": case,
        "cpus": cpus,
        "checks": checks,
        "violations": violations,
        "trace_available": trace_available,
        "architecture_evidence": architecture_evidence,
        "trace_checks_skipped": trace_checks_skipped,
        "trace": {
            "available": trace_available,
            "mmu_stores": trace.mmu_stores,
            "appends": trace.appends,
            "pte_updates": trace.pte_updates,
            "traps": trace.traps,
            "dirty_log_faults": trace.dirty_log_faults,
            "attribution_errors": trace.attribution_errors,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", required=True,
                        choices=("csr", "smoke", "race", "ctc", "dirtygen"))
    parser.add_argument("--case", default="all")
    parser.add_argument("--cpus", required=True, type=int)
    parser.add_argument(
        "--trace", type=Path,
        help="optional RVLS tracer.log; required with --require-trace")
    parser.add_argument(
        "--require-trace", action="store_true",
        help="fail when tracer.log is absent (simulation diagnostic mode)")
    parser.add_argument("--arch", type=Path)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    try:
        trace = parse_trace(args.trace, args.family, args.cpus,
                            require_trace=args.require_trace)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    arch = json.loads(args.arch.read_text()) if args.arch and args.arch.is_file() else None
    report = check_invariants(args.family, args.case, args.cpus, trace, arch)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
