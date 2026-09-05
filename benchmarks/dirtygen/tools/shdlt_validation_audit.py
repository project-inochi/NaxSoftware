#!/usr/bin/env python3
"""Reproduce the frozen SHDLT correctness and performance evidence audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import dirtygen_perf_compare
import dirtygen_perf_report


INPUT_SCHEMA = "shdlt-validation-audit-input-v1"
OUTPUT_SCHEMA = "shdlt-validation-audit-v1"
EXPECTED_MATRIX_TOTALS = {
    "runs": 52,
    "trace_available_runs": 52,
    "trace_unavailable_runs": 0,
    "invariant_failures": 0,
    "attribution_errors": 0,
}
FORBIDDEN_CONSOLE_TEXT = (
    "rvls mismatch",
    "attribution error",
    "failure context",
    "residual mmustorequeue",
    "timeout reached",
    "simulation timeout",
)
AUDIT_SNAPSHOT = "ext/NaxSoftware/benchmarks/dirtygen/SHDLT_VALIDATION_AUDIT.md"


class AuditError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def resolve_relative(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AuditError("evidence path must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise AuditError(f"evidence path escapes repository root: {value!r}")
    root = root.resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AuditError(f"evidence path escapes repository root: {value!r}") from error
    return resolved


def require_unique(values: Iterable[str], kind: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise AuditError(f"duplicate {kind}: {value}")
        seen.add(value)


class Evidence:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.files: dict[str, dict[str, Any]] = {}

    def path(self, relative: str) -> Path:
        return resolve_relative(self.root, relative)

    def add(self, relative: str) -> Path:
        path = self.path(relative)
        if not path.is_file():
            raise AuditError(f"missing evidence file: {relative}")
        if relative not in self.files:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            self.files[relative] = {
                "path": relative,
                "size": size,
                "sha256": digest.hexdigest(),
            }
        return path

    def json(self, relative: str) -> dict[str, Any]:
        path = self.add(relative)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AuditError(f"invalid JSON evidence {relative}: {error}") from error
        if not isinstance(value, dict):
            raise AuditError(f"JSON evidence must be an object: {relative}")
        return value

    def digest(self) -> str:
        digest = hashlib.sha256()
        for item in sorted(self.files.values(), key=lambda entry: entry["path"]):
            digest.update(
                f"{item['path']}\0{item['size']}\0{item['sha256']}\n".encode()
            )
        return digest.hexdigest()


@dataclass
class Check:
    category: str
    check: str
    status: str
    observed: Any
    expected: Any
    evidence: str

    def document(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "check": self.check,
            "status": self.status,
            "observed": self.observed,
            "expected": self.expected,
            "evidence": self.evidence,
        }


class Checks:
    def __init__(self) -> None:
        self.items: list[Check] = []

    def equal(
        self, category: str, name: str, observed: Any, expected: Any, evidence: str
    ) -> None:
        status = "PASS" if observed == expected else "FAIL"
        self.items.append(Check(category, name, status, observed, expected, evidence))
        if status == "FAIL":
            raise AuditError(
                f"{category}/{name}: observed {observed!r}, expected {expected!r}"
            )

    def true(self, category: str, name: str, value: bool, evidence: str) -> None:
        self.equal(category, name, bool(value), True, evidence)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AuditError(
            f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}"
        )
    return result.stdout.rstrip("\n")


def git_status_paths(repo: Path) -> tuple[list[str], list[str]]:
    output = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    tracked: list[str] = []
    untracked: list[str] = []
    for line in output.splitlines():
        if line.startswith("?? "):
            untracked.append(line[3:])
        elif line:
            tracked.append(line[3:] if len(line) > 3 else line)
    return tracked, untracked


def validate_repo_state(
    root: Path, manifest: dict[str, Any], checks: Checks
) -> dict[str, Any]:
    repos = {
        "VexiiRiscv": root,
        "NaxSoftware": root / "ext/NaxSoftware",
        "Spike": root / "ext/riscv-isa-sim",
        "RVLS": root / "ext/rvls",
    }
    observed: dict[str, Any] = {}
    tested = manifest["tested_heads"]
    for name, repo in repos.items():
        head = run_git(repo, "rev-parse", "HEAD")
        branch = run_git(repo, "branch", "--show-current") or "DETACHED"
        tracked, untracked = git_status_paths(repo)
        observed[name] = {
            "head": head,
            "branch": branch,
            "tracked_paths": tracked,
            "untracked_paths": untracked,
        }
        if name in ("VexiiRiscv", "Spike", "RVLS"):
            checks.equal("repository", f"{name} tested HEAD", head, tested[name], name)

    nax = repos["NaxSoftware"]
    nax_head = observed["NaxSoftware"]["head"]
    tested_nax = tested["NaxSoftware"]
    descendant = subprocess.run(
        ["git", "-C", str(nax), "merge-base", "--is-ancestor", tested_nax, nax_head],
        check=False,
    ).returncode == 0
    checks.true("repository", "NaxSoftware tested or audit-only descendant", descendant, "NaxSoftware")
    committed_paths = set(
        filter(None, run_git(nax, "diff", "--name-only", f"{tested_nax}..{nax_head}").splitlines())
    )
    audit_paths = set(manifest["audit_only_paths"])
    checks.true(
        "repository",
        "NaxSoftware descendant contains audit-only paths",
        committed_paths <= audit_paths,
        "NaxSoftware",
    )
    tracked_paths = set(observed["NaxSoftware"]["tracked_paths"])
    checks.true(
        "repository",
        "NaxSoftware tracked changes are audit-only",
        tracked_paths <= audit_paths,
        "NaxSoftware",
    )
    untracked_paths = set(observed["NaxSoftware"]["untracked_paths"])
    allowed_untracked = set(manifest["allowed_nax_untracked"])
    allowed_untracked.update(
        path for path in audit_paths if not (nax / path).is_file() or path in untracked_paths
    )
    checks.true(
        "repository",
        "NaxSoftware untracked files allowed",
        untracked_paths <= allowed_untracked,
        "NaxSoftware",
    )
    for name in ("Spike", "RVLS"):
        checks.equal(
            "repository",
            f"{name} tracked status",
            observed[name]["tracked_paths"],
            [],
            name,
        )
        checks.equal(
            "repository",
            f"{name} untracked status",
            observed[name]["untracked_paths"],
            [],
            name,
        )

    cached = run_git(root, "diff", "--cached", "--name-only").splitlines()
    gitlink_paths = {value["path"] for value in manifest["top_level_gitlinks"].values()}
    checks.true(
        "repository",
        "top-level gitlinks are not staged",
        not (set(cached) & gitlink_paths),
        "top-level index",
    )
    for name, value in manifest["top_level_gitlinks"].items():
        listing = run_git(root, "ls-tree", "HEAD", value["path"]).split()
        if len(listing) < 3:
            raise AuditError(f"could not read top-level gitlink {value['path']}")
        checks.equal(
            "repository", f"{name} top-level gitlink", listing[2], value["head"], value["path"]
        )
        actual = observed[name]["head"]
        mismatch = actual != value["head"]
        checks.equal(
            "repository",
            f"{name} allowed gitlink mismatch",
            mismatch,
            bool(value["allow_mismatch"]),
            value["path"],
        )

    for name, commits in manifest["commit_chain"].items():
        repo = repos[name]
        for commit in commits:
            run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
        linear = all(
            subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer],
                check=False,
            ).returncode == 0
            for older, newer in zip(commits, commits[1:])
        )
        checks.true("repository", f"{name} validation commit chain", linear, name)
    return observed


def validate_artifacts(
    root: Path, manifest: dict[str, Any], evidence: Evidence, checks: Checks
) -> None:
    config = manifest["hashes"]
    binary_manifest = config["binary_manifest"]
    path = binary_manifest["path"]
    actual_manifest_hash = evidence.files[path]["sha256"] if path in evidence.files else None
    if actual_manifest_hash is None:
        evidence.add(path)
        actual_manifest_hash = evidence.files[path]["sha256"]
    checks.equal(
        "artifact", "matrix manifest SHA256", actual_manifest_hash, binary_manifest["sha256"], path
    )
    lines = [
        line.split()
        for line in evidence.path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    checks.equal("artifact", "matrix manifest entries", len(lines), binary_manifest["entries"], path)
    require_unique([fields[1] for fields in lines if len(fields) == 2], "matrix binary path")
    if any(len(fields) != 2 for fields in lines):
        raise AuditError("malformed matrix binary manifest")
    bad: list[str] = []
    for expected_hash, elf_path in lines:
        evidence.add(elf_path)
        if evidence.files[elf_path]["sha256"] != expected_hash:
            bad.append(elf_path)
    checks.equal("artifact", "matrix ELF checksums", bad, [], path)

    names: list[str] = []
    artifact_paths: list[str] = []
    for name, artifact_path, expected_hash in config["artifacts"]:
        names.append(name)
        artifact_paths.append(artifact_path)
        evidence.add(artifact_path)
        checks.equal(
            "artifact",
            f"{name} SHA256",
            evidence.files[artifact_path]["sha256"],
            expected_hash,
            artifact_path,
        )
    require_unique(names, "artifact name")
    require_unique(artifact_paths, "artifact path")


def scan_forbidden(path: Path) -> list[str]:
    hits: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            lowered = line.lower()
            for needle in FORBIDDEN_CONSOLE_TEXT:
                if needle in lowered:
                    hits.append(f"{number}:{needle}")
    return hits


def validate_matrix_document(document: dict[str, Any], expected_runs: int) -> list[str]:
    if document.get("status") != "PASS":
        raise AuditError("correctness matrix summary is not PASS")
    totals = document.get("totals")
    if not isinstance(totals, dict):
        raise AuditError("correctness matrix summary has no totals")
    expected_totals = dict(EXPECTED_MATRIX_TOTALS)
    expected_totals["runs"] = expected_runs
    expected_totals["trace_available_runs"] = expected_runs
    for field, expected in expected_totals.items():
        if totals.get(field) != expected:
            raise AuditError(
                f"correctness matrix {field}={totals.get(field)!r}, expected {expected}"
            )
    expected = document.get("expected")
    records = document.get("records")
    if not isinstance(expected, list) or not isinstance(records, list):
        raise AuditError("correctness matrix expected/records must be lists")
    if len(expected) != expected_runs or len(records) != expected_runs:
        raise AuditError("correctness matrix run count differs from expected")
    require_unique(expected, "matrix run ID")
    by_id = {record.get("run_id"): record for record in records}
    if set(by_id) != set(expected) or len(by_id) != expected_runs:
        raise AuditError("correctness matrix run ID set differs from expected")
    for run_id, record in by_id.items():
        if record.get("status") != "PASS" or record.get("trace_available") is not True:
            raise AuditError(f"matrix record {run_id} is not a traced PASS")
        invariants = record.get("invariants")
        if not isinstance(invariants, dict) or invariants.get("status") != "PASS":
            raise AuditError(f"matrix record {run_id} invariant is not PASS")
        trace = invariants.get("trace", {})
        if trace.get("attribution_errors") != 0:
            raise AuditError(f"matrix record {run_id} has attribution errors")
        if invariants.get("violations") != []:
            raise AuditError(f"matrix record {run_id} has invariant violations")
    return expected


def validate_correctness(
    manifest: dict[str, Any], evidence: Evidence, checks: Checks
) -> None:
    config = manifest["correctness"]
    summary_path = config["summary"]
    summary = evidence.json(summary_path)
    run_ids = validate_matrix_document(summary, config["expected_runs"])
    checks.equal("correctness", "fresh matrix status", summary["status"], "PASS", summary_path)
    for field, expected in EXPECTED_MATRIX_TOTALS.items():
        checks.equal(
            "correctness",
            f"fresh matrix {field}",
            summary["totals"].get(field),
            expected,
            summary_path,
        )

    root = config["matrix_root"]
    bad_runs: list[str] = []
    for run_id in run_ids:
        result_rel = f"{root}/results/{run_id}.json"
        invariant_rel = f"{root}/results/{run_id}.invariants.json"
        done_rel = f"{root}/results/{run_id}.done"
        console_rel = f"{root}/logs/{run_id}.log"
        trace_rel = f"{root}/traces/{run_id}.tracer.log"
        result = evidence.json(result_rel)
        invariant = evidence.json(invariant_rel)
        evidence.add(done_rel)
        console = evidence.add(console_rel)
        evidence.add(trace_rel)
        if (
            result.get("status") != "PASS"
            or result.get("trace_available") is not True
            or result.get("trace", {}).get("attribution_errors") != 0
            or invariant.get("status") != "PASS"
            or invariant.get("violations") != []
            or invariant.get("trace", {}).get("attribution_errors") != 0
            or scan_forbidden(console)
        ):
            bad_runs.append(run_id)
    checks.equal("correctness", "52 result/invariant/log/trace groups", bad_runs, [], root)

    report_paths = [item[0] for item in config["attribution_reports"]]
    require_unique(report_paths, "attribution report")
    for report_path, expected in config["attribution_reports"]:
        observed = evidence.json(report_path)
        validate_attribution(observed, expected)
        checks.equal(
            "attribution", Path(report_path).stem, observed, expected, report_path
        )


def validate_attribution(observed: dict[str, Any], expected: dict[str, Any]) -> None:
    if observed != expected:
        raise AuditError("attribution report differs from its frozen expectation")
    states = observed.get("states", {})
    if observed.get("open_pending") != 0 or observed.get("duplicate_attempt_states") != 0:
        raise AuditError("attribution report has an open or duplicate lifecycle")
    mode = observed.get("mode")
    if mode == "fault" and states.get("error") != observed.get("attempts"):
        raise AuditError("log-fault attribution was not retained as error")
    if mode == "ctc" and (states.get("committed", 0) < 1 or states.get("superseded", 0) < 1):
        raise AuditError("CTC attribution lacks a winner or loser")


def campaign_files(root: str, run: str, rvls: bool) -> list[str]:
    prefix = f"{root}/{run}"
    files = [
        f"{prefix}/metadata.json",
        f"{prefix}/build.log",
        f"{prefix}/console.log",
        f"{prefix}/report.log",
        f"{prefix}/report/samples.json",
        f"{prefix}/report/samples.csv",
        f"{prefix}/report/summary.json",
        f"{prefix}/report/summary.csv",
    ]
    if rvls:
        files.extend((f"{prefix}/tracer.log", f"{prefix}/trace-audit.json"))
    return files


def load_campaign(
    evidence: Evidence, perf_root: str, run: str, *, rvls: bool
) -> dirtygen_perf_compare.Campaign:
    for path in campaign_files(perf_root, run, rvls):
        evidence.add(path)
    samples_path = evidence.path(f"{perf_root}/{run}/report/samples.json")
    metadata_path = evidence.path(f"{perf_root}/{run}/metadata.json")
    try:
        campaign = dirtygen_perf_compare.load_campaign(samples_path, metadata_path)
    except (dirtygen_perf_compare.ComparisonError, dirtygen_perf_report.ReportError) as error:
        raise AuditError(f"invalid performance campaign {run}: {error}") from error
    report = dirtygen_perf_report.DirtygenPerfReport(
        begin=campaign.document["begin"],
        samples=campaign.samples,
        end=campaign.document["end"],
        suite=campaign.metadata["suite"],
        schedule_id=campaign.metadata["schedule_id"],
    )
    expected_summary = dirtygen_perf_report.summary_document(report)
    actual_summary = evidence.json(f"{perf_root}/{run}/report/summary.json")
    if actual_summary != expected_summary:
        raise AuditError(f"performance summary drift in {run}")
    return campaign


def assert_campaign_head(
    campaign: dirtygen_perf_compare.Campaign, tested_heads: dict[str, str], run: str
) -> None:
    for name, expected in tested_heads.items():
        state = campaign.metadata["repositories"].get(name, {})
        if state.get("head") != expected:
            raise AuditError(f"{run} {name} HEAD differs from tested HEAD")
    if campaign.metadata["repositories"]["NaxSoftware"].get("tracked_dirty") is not False:
        raise AuditError(f"{run} was not measured at tracked-clean NaxSoftware HEAD")


def assert_reference_head(
    campaign: dirtygen_perf_compare.Campaign,
    tested_heads: dict[str, str],
    reference_nax_head: str,
    run: str,
) -> None:
    for name in ("VexiiRiscv", "Spike", "RVLS"):
        if campaign.metadata["repositories"].get(name, {}).get("head") != tested_heads[name]:
            raise AuditError(f"{run} {name} HEAD differs from tested HEAD")
    if campaign.metadata["repositories"].get("NaxSoftware", {}).get("head") != reference_nax_head:
        raise AuditError(f"{run} NaxSoftware HEAD differs from frozen reference HEAD")


def parse_trace_lifecycle(path: Path) -> dict[str, Any]:
    lifecycles: dict[tuple[int, int, int], list[str]] = {}
    architectural = 0
    malformed = 0
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("rv mmu store "):
                architectural += 1
            elif line.startswith("rv mmu physical-store "):
                fields = line.split()
                if len(fields) != 12:
                    malformed += 1
                    continue
                try:
                    key = (int(fields[3]), int(fields[4]), int(fields[5]))
                    int(fields[10])
                except ValueError:
                    malformed += 1
                    continue
                state = fields[11]
                if state not in ("pending", "committed", "superseded", "error"):
                    malformed += 1
                    continue
                lifecycles.setdefault(key, []).append(state)
    committed = sum(states == ["pending", "committed"] for states in lifecycles.values())
    superseded = sum(states == ["pending", "superseded"] for states in lifecycles.values())
    errors = sum(states == ["error"] for states in lifecycles.values())
    bad = [list(key) + states for key, states in lifecycles.items() if states not in (["pending", "committed"], ["pending", "superseded"], ["error"])]
    return {
        "attempts": len(lifecycles),
        "committed": committed,
        "superseded": superseded,
        "error": errors,
        "bad_lifecycles": bad,
        "malformed": malformed,
        "architectural_mmu_stores": architectural,
    }


def validate_smoke_trace(
    trace: dict[str, Any], audit: dict[str, Any]
) -> None:
    expected_trace = {
        "attempts": 54,
        "committed": 54,
        "superseded": 0,
        "error": 0,
        "bad_lifecycles": [],
        "malformed": 0,
        "architectural_mmu_stores": 162,
    }
    if trace != expected_trace:
        raise AuditError(f"RVLS smoke lifecycle differs: {trace!r}")
    if (
        audit.get("status") != "PASS"
        or audit.get("attempts") != 54
        or audit.get("committed_logger_stores") != 54
        or audit.get("architectural_mmu_stores") != 162
        or audit.get("bad_lifecycles") != []
        or audit.get("errors") != []
        or audit.get("malformed_records") != []
        or audit.get("unmatched_committed_logger_stores") != 0
        or any(audit.get("forbidden_console_hits", {}).values())
    ):
        raise AuditError("stored RVLS smoke trace audit is not clean")


def comparison_core(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: document[key]
        for key in (
            "schema", "status", "suite", "mode", "pair_key_fields",
            "warmup_samples_excluded", "cycle_deltas_are_descriptive_only",
            "pairings", "summaries", "schedule_distributions",
        )
    }


def validate_comparison(
    campaigns: list[dirtygen_perf_compare.Campaign], stored: dict[str, Any]
) -> dict[str, Any]:
    try:
        recomputed = dirtygen_perf_compare.comparison_document(campaigns)
    except (dirtygen_perf_compare.ComparisonError, dirtygen_perf_report.ReportError) as error:
        raise AuditError(f"could not recompute performance comparison: {error}") from error
    if comparison_core(recomputed) != comparison_core(stored):
        raise AuditError("stored performance comparison differs from recomputed data")
    return recomputed


def classify_stability(values: list[int | float]) -> str:
    if not values:
        raise AuditError("cannot classify an empty stability sample")
    if all(value == values[0] for value in values):
        return "exact"
    if all(value > 0 for value in values) or all(value < 0 for value in values):
        return "directional/value-sensitive"
    return "unstable"


def stability_from_comparison(document: dict[str, Any]) -> dict[str, Any]:
    metrics = dirtygen_perf_compare.DELTA_METRICS
    grouped: dict[tuple[str, int, int, int], dict[str, dict[str, int | float]]] = {}
    for summary in document["summaries"]:
        key = (
            str(summary["pattern"]), int(summary["pages"]),
            int(summary["operations"]), int(summary["simulation_seed"]),
        )
        grouped.setdefault(key, {})[str(summary["schedule_id"])] = {
            metric: summary["metrics"][metric]["median"] for metric in metrics
        }
    result: dict[str, Any] = {}
    for (pattern, pages, operations, seed), schedules in sorted(grouped.items()):
        if set(schedules) != {"S0", "S1", "S2", "S3"}:
            raise AuditError("sensitivity distribution does not contain S0--S3")
        workload = f"{pattern}/{pages}/{operations}"
        values = {
            metric: [schedules[schedule][metric] for schedule in ("S0", "S1", "S2", "S3")]
            for metric in metrics
        }
        result.setdefault(workload, {})[str(seed)] = {
            metric: {"medians": metric_values, "classification": classify_stability(metric_values)}
            for metric, metric_values in values.items()
        }
    return result


def validate_stability(
    stability: dict[str, Any], expectations: dict[str, Any]
) -> None:
    if set(stability) != set(expectations):
        raise AuditError("stability workload set differs from expectations")
    for workload, seeds in stability.items():
        if set(seeds) != {"2", "17", "101"}:
            raise AuditError(f"{workload} does not contain all frozen seeds")
        for seed, metrics in seeds.items():
            for metric, expected in expectations[workload].items():
                if metrics[metric]["classification"] != expected:
                    raise AuditError(
                        f"{workload} seed {seed} {metric} stability differs"
                    )


def validate_seed_equivalence(
    campaigns: list[dirtygen_perf_compare.Campaign]
) -> None:
    by_schedule: dict[str, dict[int, dict[str, Any]]] = {}
    for campaign in campaigns:
        by_schedule.setdefault(campaign.schedule_id, {})[campaign.seed] = campaign.document
    for schedule, seeds in by_schedule.items():
        if set(seeds) != {2, 17, 101}:
            raise AuditError(f"schedule {schedule} does not have the three frozen seeds")
        values = list(seeds.values())
        if any(value != values[0] for value in values[1:]):
            raise AuditError(f"schedule {schedule} has observable sample differences across seeds")


def validate_reference_samples(
    clean: list[dirtygen_perf_compare.Campaign],
    reference: list[dirtygen_perf_compare.Campaign],
) -> None:
    def keyed(campaigns: list[dirtygen_perf_compare.Campaign]) -> dict[tuple[str, int], dict[str, Any]]:
        result = {(campaign.schedule_id, campaign.seed): campaign.document for campaign in campaigns}
        if len(result) != len(campaigns):
            raise AuditError("duplicate sensitivity schedule/seed input")
        return result
    if keyed(clean) != keyed(reference):
        raise AuditError("clean sensitivity samples differ from Phase-4 references")


def validate_performance(
    manifest: dict[str, Any], evidence: Evidence, checks: Checks
) -> tuple[dict[str, Any], dict[str, int]]:
    config = manifest["performance"]
    root = config["root"]
    tested = manifest["tested_heads"]

    require_unique(config["rvls_smoke_runs"], "RVLS smoke run")
    smoke: list[dirtygen_perf_compare.Campaign] = []
    for run in config["rvls_smoke_runs"]:
        campaign = load_campaign(evidence, root, run, rvls=True)
        assert_campaign_head(campaign, tested, run)
        if len(campaign.samples) != 48 or len([s for s in campaign.samples if s["warmup"] == 0]) != 40:
            raise AuditError(f"{run} does not contain 48/40 samples")
        trace = parse_trace_lifecycle(evidence.path(f"{root}/{run}/tracer.log"))
        trace_audit = evidence.json(f"{root}/{run}/trace-audit.json")
        validate_smoke_trace(trace, trace_audit)
        if scan_forbidden(evidence.path(f"{root}/{run}/console.log")):
            raise AuditError(f"{run} console contains a forbidden failure marker")
        smoke.append(campaign)
    checks.equal("performance", "RVLS smoke campaigns", len(smoke), 4, root)

    sensitivity: list[dirtygen_perf_compare.Campaign] = []
    reference: list[dirtygen_perf_compare.Campaign] = []
    require_unique(config["sensitivity_runs"], "sensitivity run")
    require_unique(config["sensitivity_reference_runs"], "reference sensitivity run")
    for run in config["sensitivity_runs"]:
        campaign = load_campaign(evidence, root, run, rvls=False)
        assert_campaign_head(campaign, tested, run)
        sensitivity.append(campaign)
    for run in config["sensitivity_reference_runs"]:
        campaign = load_campaign(evidence, root, run, rvls=False)
        assert_reference_head(campaign, tested, config["reference_nax_head"], run)
        reference.append(campaign)
    validate_reference_samples(sensitivity, reference)
    validate_seed_equivalence(sensitivity)
    sensitivity_comparison_path = f"{root}/{config['sensitivity_comparison']}"
    stored_sensitivity = evidence.json(sensitivity_comparison_path)
    recomputed_sensitivity = validate_comparison(sensitivity, stored_sensitivity)
    sensitivity_counts = (
        len(sensitivity), sum(len(run.samples) for run in sensitivity),
        sum(len([sample for sample in run.samples if sample["warmup"] == 0]) for run in sensitivity),
        len(recomputed_sensitivity["pairings"]), len(recomputed_sensitivity["summaries"]),
        len(recomputed_sensitivity["schedule_distributions"]),
    )
    checks.equal(
        "performance", "sensitivity campaigns/raw/measured/pairs/summaries/distributions",
        sensitivity_counts, (12, 576, 480, 120, 24, 6), sensitivity_comparison_path,
    )
    stability = stability_from_comparison(recomputed_sensitivity)
    validate_stability(stability, manifest["stability_expectations"])
    checks.true("performance", "sensitivity schedule stability", True, sensitivity_comparison_path)

    full: list[dirtygen_perf_compare.Campaign] = []
    require_unique(config["full_runs"], "full performance run")
    for run in config["full_runs"]:
        campaign = load_campaign(evidence, root, run, rvls=False)
        assert_campaign_head(campaign, tested, run)
        full.append(campaign)
    full_comparison_path = f"{root}/{config['full_comparison']}"
    stored_full = evidence.json(full_comparison_path)
    recomputed_full = validate_comparison(full, stored_full)
    full_counts = (
        len(full), sum(len(run.samples) for run in full),
        sum(len([sample for sample in run.samples if sample["warmup"] == 0]) for run in full),
        len(recomputed_full["pairings"]), len(recomputed_full["summaries"]),
        len(recomputed_full["schedule_distributions"]),
    )
    checks.equal(
        "performance", "full campaigns/raw/measured/pairs/summaries/distributions",
        full_counts, (4, 768, 640, 160, 32, 8), full_comparison_path,
    )
    return stability, {
        "rvls_smoke_runs": len(smoke),
        "sensitivity_runs": len(sensitivity),
        "sensitivity_raw_samples": sensitivity_counts[1],
        "sensitivity_measured_samples": sensitivity_counts[2],
        "full_runs": len(full),
        "full_raw_samples": full_counts[1],
        "full_measured_samples": full_counts[2],
    }


def validate_manifest_paths(manifest: dict[str, Any], root: Path) -> None:
    if manifest.get("schema") != INPUT_SCHEMA:
        raise AuditError(f"manifest schema must be {INPUT_SCHEMA}")
    paths: list[str] = []
    binary = manifest["hashes"]["binary_manifest"]["path"]
    paths.append(binary)
    paths.extend(item[1] for item in manifest["hashes"]["artifacts"])
    paths.append(manifest["correctness"]["summary"])
    paths.extend(item[0] for item in manifest["correctness"]["attribution_reports"])
    paths.extend(value["path"] for value in manifest["top_level_gitlinks"].values())
    for path in paths:
        resolve_relative(root, path)
    require_unique(paths, "manifest input path")


def json_cell(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def checks_csv(checks: list[Check]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=("category", "check", "status", "observed", "expected", "evidence")
    )
    writer.writeheader()
    for item in checks:
        writer.writerow(
            {
                "category": item.category,
                "check": item.check,
                "status": item.status,
                "observed": json_cell(item.observed),
                "expected": json_cell(item.expected),
                "evidence": item.evidence,
            }
        )
    return output.getvalue()


def audit_markdown(document: dict[str, Any]) -> str:
    heads = document["tested_heads"]
    stability = document["stability"]
    repeat = stability["REPEAT/1/4096"]["2"]
    unique = stability["UNIQUE/128/128"]["2"]
    return f"""# SHDLT validation audit

Status: **PASS**

Evidence digest: `{document['evidence_digest']}`

Evidence files: {len(document['evidence_files'])}

## Frozen implementation

The architectural result treats `INDEX` as the committed dirty-log boundary.
CAS-loser logger writes remain visible in the physical tracer as `superseded`
events but do not enter the architectural RVLS implicit-store stream.
Successful effective guest stores that transition a G-stage PTE.D bit are
covered for explicit stores and implicit VS page-table-walker PTE.A updates.
Failure atomicity and translation/permission/log-target fault priority are
covered separately; the logger CSRs remain HS-only in the audited design.

Tested repository heads:

- VexiiRiscv: `{heads['VexiiRiscv']}`
- NaxSoftware: `{heads['NaxSoftware']}`
- Spike: `{heads['Spike']}`
- RVLS: `{heads['RVLS']}`

Recorded top-level gitlinks (intentionally different from tested submodule
heads):

- NaxSoftware: `{document['top_level_gitlinks']['NaxSoftware']['head']}`
- Spike: `{document['top_level_gitlinks']['Spike']['head']}`
- RVLS: `{document['top_level_gitlinks']['RVLS']['head']}`

Validated commit chains (oldest to newest):

- VexiiRiscv: `{' -> '.join(document['commit_chain']['VexiiRiscv'])}`
- NaxSoftware: `{' -> '.join(document['commit_chain']['NaxSoftware'])}`
- Spike: `{' -> '.join(document['commit_chain']['Spike'])}`
- RVLS: `{' -> '.join(document['commit_chain']['RVLS'])}`

The three top-level submodule gitlinks intentionally remain at their recorded
older commits. This audit-only snapshot does not update, stage, or reinterpret
those gitlinks. The NaxSoftware audit commit is permitted to be a descendant of
the tested NaxSoftware head; no measured executable or checker is changed.

## Correctness evidence

- Fresh directed matrix: 52/52 result PASS, 52/52 invariant PASS, 52 traces.
- Matrix attribution errors, invariant failures, timeouts, RVLS mismatches,
  failure contexts, and residual MMU stores: zero.
- Six focused attribution cases cover normal append, logger-target failure,
  2/4-hart CAS winner/loser, and 2/4-hart same-PTE races; every pending attempt
  reaches exactly one terminal state.
- The 43-entry ELF manifest, main dirtygen ELF, and all frozen performance ELF
  hashes match the input manifest.

No SHDLT correctness blocker remains in the audited scope.

## Performance evidence

- RVLS smoke: 4/4 PASS, 48 raw and 40 measured samples per schedule; each run
  has 54 `pending -> committed` logger attempts and 162 architectural implicit
  stores, with no error, superseded, open, mismatch, or residual event.
- Sensitivity: 12/12 PASS, 576 raw, 480 measured, 120 paired repetitions,
  24 summaries, and 6 schedule distributions. Clean-HEAD samples exactly match
  their Phase-4 references.
- Full architecture: 4/4 PASS, 768 raw, 640 measured, 160 paired repetitions,
  32 summaries, and 8 distributions. Firmware oracles and paired instret checks
  all pass.

Schedule classification for seed 2 (the other two seeds are sample-identical):

| Workload | Delta | S0/S1/S2/S3 medians | Classification |
|---|---|---|---|
| UNIQUE/128 | B1-B0 | {unique['enable_cycles']['medians']} | {unique['enable_cycles']['classification']} |
| UNIQUE/128 | B2-B0 | {unique['svadu_cycles']['medians']} | {unique['svadu_cycles']['classification']} |
| UNIQUE/128 | B3-B2 | {unique['log_cycles']['medians']} | {unique['log_cycles']['classification']} |
| REPEAT/4096 | B1-B0 | {repeat['enable_cycles']['medians']} | {repeat['enable_cycles']['classification']} |
| REPEAT/4096 | B2-B0 | {repeat['svadu_cycles']['medians']} | {repeat['svadu_cycles']['classification']} |
| REPEAT/4096 | B3-B2 | {repeat['log_cycles']['medians']} | {repeat['log_cycles']['classification']} |

UNIQUE/128 `B1-B0` is schedule-unstable, so the earlier 43-cycle observation
must not be interpreted as a stable logger-enable cost. Its Svadu and logging
increments are directionally stable but value-sensitive. REPEAT/4096 is exact
for the audited deltas. Seeds 2, 17, and 101 produce no observable counter
difference in this configuration and are not claimed as statistically
independent samples.

## Decision order

1. Decide whether to integrate the three top-level submodule gitlinks.
2. Isolate UNIQUE/128 further by running each baseline in its own fresh
   simulation process.
3. Consider multi-hart performance only after single-hart numeric stability.
4. Perform FPGA measurement last.
"""


def build_audit(root: Path, manifest_path: Path) -> dict[str, Any]:
    try:
        manifest_relative = manifest_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise AuditError("manifest must be inside the VexiiRiscv repository") from error
    evidence = Evidence(root)
    manifest = evidence.json(manifest_relative)
    validate_manifest_paths(manifest, root)
    checks = Checks()
    repositories = validate_repo_state(root, manifest, checks)
    validate_artifacts(root, manifest, evidence, checks)
    validate_correctness(manifest, evidence, checks)
    stability, counts = validate_performance(manifest, evidence, checks)
    document = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS",
        "snapshot_id": manifest["snapshot_id"],
        "tested_heads": manifest["tested_heads"],
        "commit_chain": manifest["commit_chain"],
        "top_level_gitlinks": manifest["top_level_gitlinks"],
        "current_repositories": repositories,
        "counts": counts,
        "stability": stability,
        "checks": [item.document() for item in checks.items],
        "evidence_files": sorted(evidence.files.values(), key=lambda item: item["path"]),
        "evidence_digest": evidence.digest(),
    }
    return document


def atomic_write_outputs(output_dir: Path, document: dict[str, Any]) -> None:
    if output_dir.exists():
        raise AuditError(f"audit output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    installed = False
    try:
        temporary.mkdir()
        payloads = {
            "audit.json": json.dumps(document, indent=2, sort_keys=True) + "\n",
            "audit.csv": checks_csv([Check(**item) for item in document["checks"]]),
            "audit.md": audit_markdown(document),
        }
        for name, payload in payloads.items():
            with (temporary / name).open("x", encoding="utf-8", newline="") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, output_dir)
        installed = True
        parent_fd = os.open(output_dir.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        if installed and output_dir.exists():
            shutil.rmtree(output_dir)
        raise


def repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit frozen SHDLT validation evidence")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root = repository_root()
        manifest_path = args.manifest if args.manifest.is_absolute() else Path.cwd() / args.manifest
        output_dir = args.output_dir if args.output_dir.is_absolute() else Path.cwd() / args.output_dir
        document = build_audit(root, manifest_path)
        atomic_write_outputs(output_dir, document)
        print(
            f"SHDLT validation audit: PASS checks={len(document['checks'])} "
            f"evidence={len(document['evidence_files'])} "
            f"digest={document['evidence_digest']}"
        )
        return 0
    except (
        AuditError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        dirtygen_perf_compare.ComparisonError,
        dirtygen_perf_report.ReportError,
    ) as error:
        print(f"SHDLT validation audit error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
