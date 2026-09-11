#!/usr/bin/env python3
"""Collect reproducible Phase-3 RVLS-gate and MC performance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "shdlt-dirtygen-perf-mc-phase3-inputs-v1"
RESULT_SCHEMA = "shdlt-dirtygen-perf-mc-phase3-results-v1"
EXPECTED_WINDOW_SHA256 = (
    "43350c303f71381027e8f379d5197cf6cce61c2a7ace927f493c980348e75761"
)


def repository_root(path: Path) -> Path:
    for candidate in (path.resolve(), *path.resolve().parents):
        if (candidate / "ext" / "NaxSoftware" / "benchmarks" /
                "dirtygen" / "Makefile").is_file():
            return candidate
    raise RuntimeError("VexiiRiscv repository root was not found")


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(root: Path, path: Path | str) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(root.resolve()))
    except ValueError:
        return str(resolved)


def reference(root: Path, path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"required evidence does not exist: {path}")
    return {"path": relative(root, path), "sha256": sha256(path)}


def passed_runs(manifest: dict[str, Any], expected: int) -> list[dict[str, Any]]:
    runs = manifest.get("runs", [])
    if manifest.get("status") != "passed" or len(runs) != expected:
        raise RuntimeError(
            f"campaign {manifest.get('experiment_id')} is not a complete "
            f"{expected}-selection PASS")
    bad = [run for run in runs if run.get("status") != "passed"]
    if bad:
        raise RuntimeError(f"campaign contains {len(bad)} non-PASS selections")
    return runs


def last_run_path(root: Path, campaign_root: Path,
                  run: dict[str, Any]) -> Path:
    attempts = run.get("attempts", [])
    if not attempts or attempts[-1].get("status") != "passed":
        raise RuntimeError(f"selection lacks a final PASS attempt: {run.get('key')}")
    return campaign_root / attempts[-1]["path"]


def regression_log(root: Path, path: Path, expected: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in", text)
    if not match or int(match.group(1)) != expected or not text.rstrip().endswith("OK"):
        raise RuntimeError(f"unit-test evidence is not {expected}/{expected} PASS: {path}")
    result: dict[str, Any] = reference(root, path)
    result.update({"status": "PASS", "passed": expected, "total": expected})
    return result


def normalize_gate_pairs(root: Path, document: dict[str, Any]) -> list[dict[str, Any]]:
    pairs = []
    for item in document["pairs"]:
        normalized = dict(item)
        normalized["architecture"] = relative(root, item["architecture"])
        normalized["rvls"] = relative(root, item["rvls"])
        pairs.append(normalized)
    return pairs


def artifact_inventory(root: Path,
                       campaigns: list[tuple[str, Path, list[dict[str, Any]]]],
                       ) -> list[dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for phase, campaign_root, runs in campaigns:
        for run in runs:
            run_root = last_run_path(root, campaign_root, run)
            metadata = load_json(run_root / "metadata.json")
            artifact = metadata["artifact"]
            elf = Path(artifact["elf"])
            if sha256(elf) != artifact["elf_sha256"]:
                raise RuntimeError(f"ELF changed after measurement: {elf}")
            use = {
                "phase": phase,
                "mode": run["mode"],
                "hart_count": run["harts"],
                "workload": run["workload"],
                "baseline": run["baseline"],
            }
            key = artifact["elf_sha256"]
            if key not in artifacts:
                artifacts[key] = {
                    "path": relative(root, elf),
                    "sha256": key,
                    "selection_sha256": artifact["selection_sha256"],
                    "selection": artifact["selection"],
                    "text_init_sha256": artifact["text_init_sha256"],
                    "text_sha256": artifact["text_sha256"],
                    "workload_code_sha256": artifact["workload_code_sha256"],
                    "workload_symbol_range": artifact["workload_symbol_range"],
                    "timed_window_sha256": artifact["timed_window_sha256"],
                    "uses": [],
                }
            artifacts[key]["uses"].append(use)
    values = sorted(artifacts.values(), key=lambda item: item["path"])
    windows = {item["timed_window_sha256"] for item in values}
    if windows != {EXPECTED_WINDOW_SHA256}:
        raise RuntimeError(f"unexpected timed-window hashes: {sorted(windows)}")
    for item in values:
        item["uses"] = sorted(item["uses"], key=lambda use: (
            use["phase"], use["mode"], use["hart_count"],
            use["workload"], use["baseline"]))
    return values


def sample_counts(campaign_root: Path, runs: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for run in runs:
        samples = load_json(last_run_path(campaign_root, campaign_root, run) /
                            "report" / "samples.json")["samples"]
        if len(samples) != 6:
            raise RuntimeError(f"selection has {len(samples)} rather than six samples")
        counts["files"] += 1
        counts["raw_samples"] += len(samples)
        counts["warmup_samples"] += sum(item["warmup"] == 1 for item in samples)
        counts["measured_samples"] += sum(item["warmup"] == 0 for item in samples)
        counts["bad_status_samples"] += sum(item["status"] != 0 for item in samples)
    return dict(counts)


def comparable_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "baselines": summary["baselines"],
        "deltas": summary["deltas"],
    }
    if "scaling" in summary:
        compact["scaling"] = summary["scaling"]
    if "physical_logger" in summary:
        compact["physical_logger"] = summary["physical_logger"]
    return compact


def performance_summary(comparison: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for summary in comparison["summaries"]:
        if summary["hart_count"] in (2, 4):
            grouped[(summary["hart_count"], summary["workload"])].append(summary)

    rows = []
    for (harts, workload), values in sorted(grouped.items()):
        values.sort(key=lambda value: value["isolation_block_id"])
        blocks = [value["isolation_block_id"] for value in values]
        if blocks != ["I0", "I1", "I2", "I3"]:
            raise RuntimeError(f"incomplete isolation blocks for H{harts} {workload}")
        representative = comparable_summary(values[0])
        identical = all(comparable_summary(value) == representative
                        for value in values[1:])
        rows.append({
            "hart_count": harts,
            "workload": workload,
            "isolation_blocks": blocks,
            "statistics_identical_across_blocks": identical,
            **representative,
        })

    contention = []
    for harts in (2, 4):
        values = [pair["physical_logger"]["B3"]
                  for pair in comparison["pairings"]
                  if pair["hart_count"] == harts and
                  pair["workload"] == "same-pte"]
        attempts = Counter(value["physical_attempts"] for value in values)
        superseded = Counter(value["superseded"] for value in values)
        if len(values) != 20 or any(value["committed"] != 1 for value in values):
            raise RuntimeError(f"invalid SAME_PTE B3 physical evidence for H{harts}")
        contention.append({
            "hart_count": harts,
            "measured_samples": len(values),
            "committed_total": sum(value["committed"] for value in values),
            "physical_attempts_total": sum(value["physical_attempts"] for value in values),
            "superseded_total": sum(value["superseded"] for value in values),
            "physical_attempt_distribution": [
                {"value": value, "count": count}
                for value, count in sorted(attempts.items())
            ],
            "superseded_distribution": [
                {"value": value, "count": count}
                for value, count in sorted(superseded.items())
            ],
        })
    return {
        "statistics": rows,
        "same_pte_b3_physical_distribution": contention,
        "cross_block_distributions": comparison["cross_block_distributions"],
    }


def protected_check(root: Path, phase2: dict[str, Any]) -> dict[str, Any]:
    baseline = phase2["protected_before"]
    mismatches = []
    for name, expected in baseline["files"].items():
        path = root / name
        actual = sha256(path) if path.is_file() else None
        if actual != expected:
            mismatches.append({"path": name, "expected": expected, "actual": actual})
    current_gitlinks = subprocess.run(
        ["git", "ls-tree", "HEAD", "ext/NaxSoftware", "ext/riscv-isa-sim", "ext/rvls"],
        cwd=root, text=True, capture_output=True, check=True).stdout
    return {
        "protected_file_count": len(baseline["files"]),
        "protected_files_match": not mismatches,
        "mismatches": mismatches,
        "frozen_manifest_entries": sum(
            1 for line in (root / "ext" / "NaxSoftware" / "baremetal" /
                           "rtl_directed_shdlt" / "binaries.sha256").read_text().splitlines()
            if line.strip()),
        "top_level_gitlinks_match": current_gitlinks == baseline["gitlinks"],
        "top_level_gitlinks": current_gitlinks,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-root", type=Path)
    parser.add_argument("--architecture-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--inputs-output", type=Path)
    parser.add_argument("--results-output", type=Path)
    args = parser.parse_args()

    root = repository_root(Path(__file__))
    dirtygen = root / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen"
    campaign_parent = dirtygen / "build" / "campaign" / "dirtygen-perf-mc-phase3"
    gate_root = (args.gate_root or
                 campaign_parent / "phase3-20260909-rvls-gate-fixed").resolve()
    architecture_root = (args.architecture_root or
                         campaign_parent / "phase3-20260909-architecture-fixed").resolve()
    evidence_root = (args.evidence_root or
                     dirtygen / "build" / "audit" / "phase3-final").resolve()
    inputs_output = (args.inputs_output or dirtygen / "audit" /
                     "shdlt_dirtygen_perf_mc_phase3_inputs.json").resolve()
    results_output = (args.results_output or dirtygen / "audit" /
                      "shdlt_dirtygen_perf_mc_phase3_results.json").resolve()

    gate_manifest_path = gate_root / "manifest.json"
    architecture_manifest_path = architecture_root / "manifest.json"
    gate_manifest = load_json(gate_manifest_path)
    architecture_manifest = load_json(architecture_manifest_path)
    gate_runs = passed_runs(gate_manifest, 24)
    architecture_runs = passed_runs(architecture_manifest, 108)
    if gate_manifest["source_fingerprint"] != architecture_manifest["source_fingerprint"]:
        raise RuntimeError("RVLS gate and architecture source fingerprints differ")
    if gate_manifest.get("forced_cas_required") or architecture_manifest.get("forced_cas_required"):
        raise RuntimeError("campaign unexpectedly required FORCED_CAS")

    gate_path = gate_root / gate_manifest["rvls_gate"]
    gate = load_json(gate_path)
    h1_path = architecture_root / architecture_manifest["h1_compatibility"]
    h1 = load_json(h1_path)
    comparison_path = (architecture_root /
                       architecture_manifest["architecture_comparison"] /
                       "comparison.json")
    comparison = load_json(comparison_path)
    if gate["status"] != "PASS" or h1["status"] != "PASS" or comparison["status"] != "PASS":
        raise RuntimeError("a Phase-3 gate, H1 check, or comparison did not pass")

    phase2_path = dirtygen / "audit" / "shdlt_isa_consistency_inputs.json"
    phase2 = load_json(phase2_path)
    spike_results_path = evidence_root / "spike-minimals" / "results.json"
    spike_results = load_json(spike_results_path)
    spike_statuses = Counter(item["status"] for item in spike_results["results"])
    if len(spike_results["results"]) != 12 or spike_statuses != {"PASS": 12}:
        raise RuntimeError("Spike default-path minima are not 12/12 PASS")

    unit_logs = {
        "dirtygen": regression_log(root, evidence_root / "unit-dirtygen.log", 171),
        "ctc": regression_log(root, evidence_root / "unit-ctc.log", 7),
        "race": regression_log(root, evidence_root / "unit-race.log", 12),
        "rtl": regression_log(root, evidence_root / "unit-rtl.log", 32),
    }
    minimal_path = evidence_root / "rvls-pte-cas-minimal.log"
    if minimal_path.read_text(encoding="utf-8").strip() != "RVLS_PTE_CAS_MINIMAL PASS":
        raise RuntimeError("RVLS PTE-CAS minimum reproducer did not pass")

    inventory = artifact_inventory(root, [
        ("rvls-gate", gate_root, gate_runs),
        ("architecture", architecture_root, architecture_runs),
    ])
    if len(inventory) != 40:
        raise RuntimeError(f"expected 40 legal MC ELFs, found {len(inventory)}")

    architecture_samples = sample_counts(architecture_root, architecture_runs)
    gate_samples = sample_counts(gate_root, gate_runs)
    if architecture_samples != {
            "files": 108, "raw_samples": 648, "warmup_samples": 108,
            "measured_samples": 540, "bad_status_samples": 0}:
        raise RuntimeError(f"unexpected architecture sample counts: {architecture_samples}")
    if gate_samples != {
            "files": 24, "raw_samples": 144, "warmup_samples": 24,
            "measured_samples": 120, "bad_status_samples": 0}:
        raise RuntimeError(f"unexpected RVLS-gate sample counts: {gate_samples}")

    first_run = last_run_path(root, architecture_root, architecture_runs[0])
    first_metadata = load_json(first_run / "metadata.json")
    protected = protected_check(root, phase2)
    if not protected["protected_files_match"] or not protected["top_level_gitlinks_match"]:
        raise RuntimeError("a frozen Phase-2 input or top-level gitlink changed")
    if protected["frozen_manifest_entries"] != 43:
        raise RuntimeError("the frozen ELF manifest is not 43 entries")

    commands = {
        "rvls_pte_cas_minimum": [
            "python3", "ext/NaxSoftware/benchmarks/dirtygen/tools/run_rvls_pte_cas_minimal.py"],
        "spike_default_minima": [
            "python3", "ext/NaxSoftware/benchmarks/dirtygen/tools/run_spike_isa_minimals.py",
            "--spike", "ext/riscv-isa-sim/build/spike", "--output-root",
            "ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-final/spike-minimals"],
        "rvls_gate": [
            "python3", "ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_perf_mc_phase3.py",
            "--phase", "rvls-gate", "--experiment-id",
            gate_manifest["experiment_id"], "--jobs", "2"],
        "architecture_resume": [
            "python3", "ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_perf_mc_phase3.py",
            "--phase", "architecture", "--experiment-id",
            architecture_manifest["experiment_id"], "--jobs", "2", "--resume"],
        "collect": [
            "python3", "ext/NaxSoftware/benchmarks/dirtygen/tools/collect_dirtygen_perf_mc_phase3.py"],
    }
    unit_commands = {
        "dirtygen": "python3 -m unittest discover -s ext/NaxSoftware/benchmarks/dirtygen/tests -p test_*.py",
        "ctc": "python3 -m unittest discover -s ext/NaxSoftware/benchmarks/cache_tlb_shdlt/tests -p test_*.py",
        "race": "python3 -m unittest discover -s ext/NaxSoftware/baremetal/multicore_race_shdlt/tests -p test_*.py",
        "rtl": "python3 -m unittest discover -s ext/NaxSoftware/baremetal/rtl_directed_shdlt/tests -p test_*.py",
    }

    inputs = {
        "schema": INPUT_SCHEMA,
        "scope": "phase3-rvls-cas-and-multihart-performance",
        "recorded_at": architecture_manifest["end_time"],
        "normative": phase2["normative"],
        "source_fingerprint": architecture_manifest["source_fingerprint"],
        "toolchain": first_metadata["toolchain"],
        "counter_contract": {
            "abi_version": 2,
            "instret": "5*N+5",
            "ordering": "CSR-I-fences",
            "timed_window_bytes": 48,
            "timed_window_sha256": EXPECTED_WINDOW_SHA256,
        },
        "campaigns": {
            "rvls_gate": {
                "manifest": reference(root, gate_manifest_path),
                "result": reference(root, gate_path),
                "experiment_id": gate_manifest["experiment_id"],
                "start_time": gate_manifest["start_time"],
                "end_time": gate_manifest["end_time"],
                "maximum_parallel_jobs": gate_manifest["maximum_parallel_jobs"],
                "seed": gate_manifest["seed"],
                "planned_selection_count": gate_manifest["planned_selection_count"],
                "planned_raw_sample_count": gate_manifest["planned_raw_sample_count"],
            },
            "architecture": {
                "manifest": reference(root, architecture_manifest_path),
                "comparison": reference(root, comparison_path),
                "h1_compatibility": reference(root, h1_path),
                "experiment_id": architecture_manifest["experiment_id"],
                "start_time": architecture_manifest["start_time"],
                "end_time": architecture_manifest["end_time"],
                "maximum_parallel_jobs": architecture_manifest["maximum_parallel_jobs"],
                "seed": architecture_manifest["seed"],
                "planned_selection_count": architecture_manifest["planned_selection_count"],
                "planned_raw_sample_count": architecture_manifest["planned_raw_sample_count"],
            },
        },
        "commands": commands,
        "unit_test_commands": unit_commands,
        "mc_elf_count": len(inventory),
        "mc_elfs": inventory,
        "executables": {
            "spike": reference(root, root / "ext" / "riscv-isa-sim" / "build" / "spike"),
            "rvls": reference(root, root / "ext" / "rvls" / "build" / "apps" / "rvls.so"),
            "rvls_pte_cas_minimum": reference(
                root, dirtygen / "build" / "audit" / "rvls-pte-cas-minimal" /
                "pte_cas_callbacks"),
        },
        "regression_evidence": {
            "rvls_pte_cas_minimum": reference(root, minimal_path),
            "spike_minima": reference(root, spike_results_path),
            "unit_tests": unit_logs,
        },
        "protected_baseline": reference(root, phase2_path),
        "outputs": {
            "inputs": relative(root, inputs_output),
            "results": relative(root, results_output),
            "report": "ext/NaxSoftware/benchmarks/dirtygen/SHDLT_DIRTYGEN_PERF_MC_REPORT.md",
        },
        "large_artifacts_ignored": True,
    }

    interrupted = []
    for run in architecture_runs:
        if len(run["attempts"]) > 1:
            interrupted.append({
                "key": run["key"],
                "attempts": [{
                    "status": attempt["status"],
                    "path": attempt["path"],
                    "start_time": attempt["start_time"],
                    "end_time": attempt["end_time"],
                    "exit_code": attempt["exit_code"],
                } for attempt in run["attempts"]],
            })

    results = {
        "schema": RESULT_SCHEMA,
        "status": "PASS",
        "recorded_at": architecture_manifest["end_time"],
        "source_fingerprint_sha256": architecture_manifest["source_fingerprint"]["digest"],
        "forced_cas_required": False,
        "regressions": {
            "rvls_pte_cas_minimum": {
                "status": "PASS", **reference(root, minimal_path)},
            "spike_default_path": {
                "status": "PASS", "passed": 12, "total": 12,
                "spike_sha256": spike_results["spike_sha256"],
                "results": reference(root, spike_results_path),
            },
            "unit_tests": {
                "status": "PASS",
                "passed": sum(item["passed"] for item in unit_logs.values()),
                "total": sum(item["total"] for item in unit_logs.values()),
                "suites": unit_logs,
            },
        },
        "rvls_gate": {
            "status": gate["status"],
            "process_count": gate["process_count"],
            "pair_count": gate["pair_count"],
            "raw_sample_count": gate["raw_sample_count"],
            "sample_counts": gate_samples,
            "forced_cas_required": gate["forced_cas_required"],
            "pairs": normalize_gate_pairs(root, gate),
        },
        "single_hart_compatibility": h1,
        "architecture": {
            "status": comparison["status"],
            "selection_count": len(architecture_runs),
            "sample_counts": architecture_samples,
            "main_matrix": {"selection_count": 96, "raw_sample_count": 576},
            "h1_reference": {"selection_count": 12, "raw_sample_count": 72},
            "comparison_counts": comparison["counts"],
            "interrupted_and_resumed": interrupted,
            "performance": performance_summary(comparison),
        },
        "protected_assets": protected,
        "boundaries": {
            "architecture_verdict_excludes_performance_sign": True,
            "cas_attempt_count_is_diagnostic_only": True,
            "all_harts_cas_not_required": True,
            "prefilled_is_not_forced_cas": True,
            "not_run": ["buffer-full", "Linux/KVM", "FPGA", "other ISA extensions"],
        },
    }

    write_json(inputs_output, inputs)
    write_json(results_output, results)
    print(f"Phase-3 audit collection: PASS inputs={relative(root, inputs_output)} "
          f"results={relative(root, results_output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
