#!/usr/bin/env python3
"""Validate the privileged SHDLT result ABI and optional RVLS diagnostics.

The firmware result records are the portable contract for this campaign.  An
RVLS ``tracer.log`` can add useful simulation-only attribution evidence, but a
hardware or Linux backend does not necessarily have that file.  The parser
therefore carries an explicit availability bit instead of treating a missing
trace as an empty, successful trace.  Callers which require the diagnostic
backend can use ``--require-trace`` (or ``require_trace=True``).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path


CASE_NAMES = (
    "hgatp_rw_warl",
    "hgatp_permissions",
    "hdltctl_rw_warl",
    "hdltidx_mask",
    "hdlt_permissions",
)
SMOKE_CASES = {
    "load_only": 1, "log_off": 2, "predirty": 3, "widths": 4,
    "nonzero_index": 5, "freeze": 6, "reset_resume": 7,
}


def number(value: str) -> int:
    return int(value, 16 if value.lower().startswith("0x") else 10)


def fields(line: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for token in line.strip().split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = number(value)
    return result


@dataclass
class TraceSummary:
    cpus: int
    mmu_stores: int
    appends: int
    pte_updates: int
    traps: int
    dirty_log_faults: int
    attribution_errors: int
    # Kept last with a default so old callers constructing the seven original
    # positional fields remain source compatible.
    available: bool = True


def empty_trace(cpus: int) -> TraceSummary:
    """Return an explicitly unavailable trace summary.

    Numeric fields are zero only as a storage convenience; consumers must
    inspect ``available`` before drawing conclusions from those fields.
    """
    return TraceSummary(cpus, 0, 0, 0, 0, 0, 0, available=False)


def buffer_region(family: str, hart: int) -> tuple[int, int] | None:
    if family == "smoke":
        return 0x81050000 + hart * 0x01000000, 0x1000
    if family == "race":
        return 0x82010000 + hart * 0x00800000, 0x1000
    if family == "ctc":
        return 0x83010000 + hart * 0x00800000, 0x1000
    if family == "dirtygen" and hart == 0:
        # The preserved ABI-v5 ELF has four adjacent 16 KiB replacement
        # slots at dirty_log_buffers=0x8000c000.  Its SHA-256 is pinned by
        # binaries.sha256, so this architectural layout cannot silently drift.
        return 0x8000C000, 4 * 0x4000
    return None


def parse_trace(path: Path | None, family: str, cpus: int,
                require_trace: bool = True) -> TraceSummary:
    """Parse an RVLS trace, or return an unavailable summary when optional.

    ``require_trace`` defaults to ``True`` for compatibility with the former
    strict API.  Architecture-only callers pass ``False`` and may omit the
    path entirely.  A present trace is always parsed strictly; malformed or
    incomplete CPU attribution is never silently downgraded to unavailable.
    """
    if path is None or not Path(path).is_file():
        if require_trace:
            location = "<none>" if path is None else str(path)
            raise ValueError(f"RVLS trace is missing: {location}")
        return empty_trace(cpus)
    path = Path(path)
    cpu_ids: set[int] = set()
    mmu_stores = appends = pte_updates = traps = dirty_faults = errors = 0
    mmu_re = re.compile(
        r"^rv mmu store (\d+) ([0-9a-fA-F]+) (\d+) ([0-9a-fA-F]+) ([01])$"
    )
    trap_re = re.compile(r"^rv trap (\d+) ([01]) (\d+)$")
    new_re = re.compile(r"^rv new (\d+) ")
    for line in path.read_text(errors="replace").splitlines():
        if match := new_re.match(line):
            cpu_ids.add(int(match.group(1)))
            continue
        if match := mmu_re.match(line):
            hart = int(match.group(1))
            address = int(match.group(2), 16)
            length = int(match.group(3))
            data = int(match.group(4), 16)
            error = int(match.group(5))
            mmu_stores += 1
            if hart >= cpus or length != 8 or error:
                errors += 1
            owner = None
            for candidate in range(cpus):
                region = buffer_region(family, candidate)
                if (region is not None and region[0] <= address <
                        region[0] + region[1]):
                    owner = candidate
                    break
            if owner is not None:
                appends += 1
                if owner != hart or data & 0xFFF:
                    errors += 1
            else:
                pte_updates += 1
            continue
        if match := trap_re.match(line):
            hart = int(match.group(1))
            interrupt = int(match.group(2))
            cause = int(match.group(3))
            traps += 1
            if hart >= cpus:
                errors += 1
            if not interrupt and cause == 24:
                dirty_faults += 1
    if cpu_ids != set(range(cpus)):
        raise ValueError(f"RVLS trace CPU set {sorted(cpu_ids)} != expected {list(range(cpus))}")
    return TraceSummary(cpus, mmu_stores, appends, pte_updates, traps,
                        dirty_faults, errors, available=True)


def validate_csr(text: str, trace: TraceSummary) -> dict[str, object]:
    records = [fields(line) for line in text.splitlines()
               if line.startswith("SHDLT_RTL_HART ")]
    ends = [fields(line) for line in text.splitlines()
            if line.startswith("SHDLT_RTL_END ")]
    if len(records) != len(CASE_NAMES) or {r.get("case") for r in records} != set(range(5)):
        raise ValueError("CSR result case set is incomplete")
    if len(ends) != 1 or ends[0].get("cases") != 5 or ends[0].get("failures") != 0:
        raise ValueError("CSR end record is invalid")
    for record in records:
        if record.get("abi") != 1 or record.get("status") != 0:
            raise ValueError(f"CSR case failed: {record}")
    by_case = {r["case"]: r for r in records}
    if (by_case[1].get("trap_count") != 4 or by_case[1].get("cause") != 2 or
            by_case[1].get("trap_target") != 3):
        raise ValueError("HGATP permission trap contract failed")
    if (by_case[4].get("trap_count") != 4 or by_case[4].get("cause") != 22 or
            by_case[4].get("trap_target") != 1):
        raise ValueError("HDLT permission trap contract failed")
    if (trace.available and
            (trace.dirty_log_faults or trace.mmu_stores or
             trace.attribution_errors)):
        raise ValueError("CSR-only image emitted unexpected MMU/fault events")
    return {"cases": len(records), "case_names": list(CASE_NAMES)}


def validate_smoke(text: str, cpus: int, case: str) -> dict[str, object]:
    # The preserved multicore smoke images intentionally let every hart write
    # the same byte-wide UART.  Their human-readable SAMPLE lines can therefore
    # be character-interleaved even though the result structures in RAM are
    # complete.  Hart 0 checks every result structure before it enters `pass`,
    # and every secondary hart also has to enter `pass`; run_matrix invokes the
    # TestBench with --pass-policy all.  Treat the successful TestBench terminal
    # result as the authoritative old-image ABI, while still checking any SAMPLE
    # records that happened to remain intact.
    if "[Done] Simulation done" not in text or "SUCCESS] mill" not in text:
        raise ValueError("smoke TestBench all-hart success marker is missing")
    records = [fields(line) for line in text.splitlines()
               if line.startswith("SHDLT_MC_SAMPLE ")]
    expected_case = SMOKE_CASES[case]
    decoded_harts = [r.get("hart") for r in records]
    if (len(records) > cpus or len(set(decoded_harts)) != len(decoded_harts) or
            any(hart not in range(cpus) for hart in decoded_harts)):
        raise ValueError("smoke decoded hart set is invalid")
    for record in records:
        if (record.get("case") != expected_case or
                record.get("status") != 0x600D):
            raise ValueError(f"smoke result failed: {record}")
    return {
        "harts": cpus,
        "decoded_uart_records": len(records),
        "result_contract": "firmware-RAM-check+TestBench-pass-policy-all",
        "entries_decoded": sum(r.get("entries", 0) for r in records),
    }


def validate_log(family: str, text: str, cpus: int, case: str,
                 trace: TraceSummary) -> dict[str, object]:
    fatal = ("INTEGER WRITE MISSMATCH", "RVLS MISMATCH", "[error]", " FAILED]")
    if any(marker in text for marker in fatal):
        raise ValueError("simulation log contains a fatal/RVLS marker")
    if trace.available and trace.attribution_errors:
        raise ValueError(f"RVLS attribution errors: {trace.attribution_errors}")
    if family == "csr":
        return validate_csr(text, trace)
    if family == "smoke":
        return validate_smoke(text, cpus, case)
    if family == "race" and "SHDLT_RACE_END " not in text:
        raise ValueError("race end record missing")
    if family == "ctc" and "SHDLT_CTC_END " not in text:
        raise ValueError("CTC end record missing")
    if family == "dirtygen" and "DIRTYGEN_END " not in text:
        raise ValueError("dirtygen end record missing")
    return {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", required=True,
                        choices=("csr", "smoke", "race", "ctc", "dirtygen"))
    parser.add_argument("--cpus", required=True, type=int)
    parser.add_argument("--case", default="all")
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument(
        "--trace", type=Path,
        help="optional RVLS tracer.log; required when --require-trace is used")
    parser.add_argument(
        "--require-trace", action="store_true",
        help="fail when tracer.log is absent (simulation diagnostic mode)")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if not args.log.is_file():
        raise SystemExit("log is missing")
    try:
        trace = parse_trace(args.trace, args.family, args.cpus,
                            require_trace=args.require_trace)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    details = validate_log(args.family, args.log.read_text(errors="replace"),
                           args.cpus, args.case, trace)
    result = {
        "family": args.family, "case": args.case, "cpus": args.cpus,
        "status": "PASS", "trace": asdict(trace),
        "trace_available": trace.available, "details": details,
    }
    encoded = json.dumps(result, sort_keys=True)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded + "\n")
    print(encoded)


if __name__ == "__main__":
    main()
