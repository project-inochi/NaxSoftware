#!/usr/bin/env python3
"""Produce reviewable Phase-2 input/result JSON in build; never rewrite historical audits."""
import argparse
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

from shdlt_isa_audit import DIRTYGEN, NAX, ROOT, git, protected_state, sha256
from run_shdlt_isa import FAMILIES, Selection, make_command, run as run_command
from shdlt_isa_report import build_report
import run_dirtygen_perf_mc as mc_runner


def reference(path):
    path = path.resolve()
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": sha256(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family-root", type=Path, action="append", required=True)
    parser.add_argument("--mc-root", type=Path, required=True)
    parser.add_argument("--spike-root", type=Path, required=True)
    parser.add_argument("--protected-before", type=Path, required=True)
    parser.add_argument("--legacy-rebuild", type=Path, required=True)
    parser.add_argument("--unit-log", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if not output.is_relative_to(DIRTYGEN / "build"):
        parser.error("output must be inside dirtygen/build")
    output.mkdir(parents=True, exist_ok=False)
    before = json.loads(args.protected_before.read_text())
    if protected_state() != before:
        raise RuntimeError("frozen baseline or external implementation changed")
    selected, attempts, inputs = {}, [], []
    for campaign_index, directory in enumerate(args.family_root):
        summary = json.loads((directory / "summary.json").read_text())
        for run in summary["results"]:
            s = run["selection"]
            name = f"{s['family']}-h{s['harts']}-{s['case']}-p{s['producer_delay']}-c{s['consumer_delay']}"
            folder = directory / "runs" / name
            entry = {"name": name, "selection": s, "status": run["status"],
                     "record": reference(folder / "run.json")}
            if "error" in run: entry["error"] = run["error"]
            if run["status"] != "PASS" and (folder / "console.log").exists():
                if "Reached Timeout" in (folder / "console.log").read_text(errors="replace"):
                    entry["classification"] = "budget exhausted; not an ISA verdict"
            attempts.append(entry)
            elf = folder / "build" / (FAMILIES[s["family"]][1] + ".elf")
            if run["status"] == "PASS":
                focused = (s["family"], s["case"]) in (("ctc", "cas_retry"), ("race", "same_pte"))
                try:
                    if s["family"] in ("ctc", "race") and not (folder / "tracer.log").is_file():
                        raise ValueError("required CTC/race physical trace was not archived")
                    report = build_report(folder / "console.log", s["family"], s["harts"], s["case"],
                                          elf, folder / "tracer.log" if focused else None)
                    if report["diagnostics"]["status"] == "INCOMPLETE":
                        raise ValueError(report["diagnostics"]["error"])
                    report_path = output / f"rechecked-{campaign_index}-{name}.json"
                    report_path.write_text(json.dumps(report, indent=2) + "\n")
                    entry["rechecked_report"] = reference(report_path)
                    entry["architecture_status"] = report["architecture_status"]
                    entry["diagnostics"] = {key: value for key, value in report["diagnostics"].items()
                                            if key in ("status", "profile", "physical_attempts", "committed",
                                                       "superseded", "attempts_by_hart")}
                    if "translation_observations" in report:
                        entry["translation_observations"] = report["translation_observations"]
                    selected[name] = entry
                except ValueError as error:
                    entry["status"] = "SUPERSEDED_OR_REJECTED"
                    entry["recheck_error"] = str(error)
            if elf.exists():
                inputs.append({"selection": s, "profile": "isa", "elf": reference(elf),
                               "console": reference(folder / "console.log") if (folder / "console.log").exists() else None,
                               "build": run["build"]["command"],
                               "simulation": run.get("simulation", {}).get("command"),
                               "report": reference(folder / "report.json") if (folder / "report.json").exists() else None,
                               "trace": reference(folder / "tracer.log") if (folder / "tracer.log").exists() else None})
    # Bind accepted ELF evidence to the exact final source snapshot, even when
    # unrelated case-specialized code changed during this implementation.
    for name, entry in selected.items():
        folder = output / "source-rebuild" / name
        folder.mkdir(parents=True)
        record = run_command(make_command(Selection(**entry["selection"]), folder / "build", "isa"),
                             folder / "build.log", 180)
        image = FAMILIES[entry["selection"]["family"]][1] + ".elf"
        original_record = ROOT / entry["record"]["path"]
        original_elf = original_record.parent / "build" / image
        if record["exit_code"] or sha256(folder / "build" / image) != sha256(original_elf):
            raise RuntimeError(f"accepted ELF no longer matches final source: {name}")
        entry["final_source_rebuild"] = "IDENTICAL"
    mc = json.loads((args.mc_root / "summary.json").read_text())
    for entry in mc["builds"]:
        if entry["exit_code"]:
            continue
        selection = entry["artifact"]["selection"]
        prefilled = "prefilled" in entry["name"]
        folder = output / "source-rebuild" / ("mc-" + entry["name"])
        folder.mkdir(parents=True)
        command = ["make", "-C", str(DIRTYGEN), "all",
                   "SUITE=" + ("perf-mc-prefilled" if prefilled else "perf-mc"),
                   f"BUILD_DIR={folder / 'build'}", f"PERF_MC_HARTS={selection['hart_count']}",
                   f"PERF_MC_WORKLOAD_ID={selection['workload']}",
                   f"PERF_MC_BASELINE={selection['baseline']}"]
        record = run_command(command, folder / "build.log", 180)
        image = "dirtygen_perf_mc_prefilled.elf" if prefilled else "dirtygen_perf_mc.elf"
        if record["exit_code"] or sha256(folder / "build" / image) != entry["artifact"]["elf_sha256"]:
            raise RuntimeError(f"MC ELF no longer matches final source: {entry['name']}")
        entry["final_source_rebuild"] = "IDENTICAL"
    mc_runs = []
    for run in mc["runs"]:
        folder = args.mc_root / run["name"]
        metadata = json.loads((folder / "metadata.json").read_text())
        elf = mc_runner.elf_path(ROOT, metadata["hart_count"], metadata["workload"], metadata["baseline"])
        if sha256(elf) != metadata["artifact"]["elf_sha256"]:
            raise RuntimeError(f"MC run ELF changed: {run['name']}")
        rechecked = output / ("rechecked-mc-" + run["name"])
        command = [sys.executable, str(DIRTYGEN / "tools/dirtygen_perf_mc_report.py"),
                   str(folder / "console.log"), "--hart-count", str(metadata["hart_count"]),
                   "--workload", metadata["workload"], "--baseline", metadata["baseline"],
                   "--tracer", str(folder / "tracer.log"), "--elf", str(elf),
                   "--output-dir", str(rechecked)]
        record = run_command(command, output / ("rechecked-mc-" + run["name"] + ".log"), 180)
        if record["exit_code"]:
            raise RuntimeError(f"MC diagnostic no longer passes: {run['name']}")
        diagnostic = json.loads((rechecked / "trace-report.json").read_text())
        mc_runs.append({"name": run["name"], "status": metadata["status"],
                        "diagnostic_totals": diagnostic["totals"],
                        "outside_timed_events": diagnostic["outside_timed_events"],
                        "metadata": reference(folder / "metadata.json"),
                        "console": reference(folder / "console.log"),
                        "raw_trace": reference(folder / "tracer.log") if (folder / "tracer.log").exists() else None,
                        "trace_report": reference(folder / "report/trace-report.json") if (folder / "report/trace-report.json").exists() else None,
                        "rechecked_trace_report": reference(rechecked / "trace-report.json")})
    spike = json.loads((args.spike_root / "results.json").read_text())
    legacy = json.loads(args.legacy_rebuild.read_text())
    if len(legacy["results"]) != 42 or any(r["exit_code"] or r["expected_sha256"] != r["rebuilt_sha256"] for r in legacy["results"]):
        raise RuntimeError("legacy rebuild evidence is not 42 identical ELF files")
    unit_count = 0
    for path in args.unit_log:
        content = path.read_text()
        match = re.search(r"Ran (\d+) tests? in ", content)
        if not match or not int(match[1]) or not content.rstrip().endswith("OK"):
            raise RuntimeError(f"unit test evidence is not PASS: {path}")
        unit_count += int(match[1])
    basic = [r for r in selected.values() if not r["selection"]["producer_delay"] and not r["selection"]["consumer_delay"]]
    stress = [r for r in selected.values() if r not in basic]
    results = {"schema": "shdlt-isa-consistency-results-v1",
               "basic_pass": len(basic), "basic_required": 42,
               "stress_pass": len(stress), "stress_required": 8,
               "mc_build_pass": sum(r["exit_code"] == 0 for r in mc["builds"]), "mc_build_required": 40,
               "mc_run_pass": sum(r["status"] == "passed" for r in mc_runs), "mc_run_required": 18,
               "spike_pass": sum(r["exit_code"] == 0 for r in spike["results"]), "spike_required": 12,
               "protected_files": len(before["files"]), "protected_status": "PASS",
               "legacy_rebuild_pass": 42, "unit_test_pass": unit_count,
               "accepted_family_runs": list(selected.values()), "all_family_attempts": attempts,
               "mc_runs": mc_runs,
               "rvls": "UNVERIFIED: current source interface mismatch; no RVLS comparison performed"}
    results["phase2_status"] = "COMPLETE" if all(results[k + "_pass"] == results[k + "_required"] for k in
                                                ("basic", "stress", "mc_build", "mc_run", "spike")) else "INCOMPLETE"
    sources = []
    directories = [NAX / entry[0] for entry in FAMILIES.values()] + [DIRTYGEN, NAX / "baremetal/rtl_directed_shdlt"]
    for directory in directories:
        for path in sorted(directory.rglob("*")):
            if (path.is_file() and not {"build", "__pycache__", ".git", "audit"}.intersection(path.relative_to(directory).parts)
                    and (path.suffix in (".c", ".h", ".S", ".ld", ".py", ".sh") or path.name == "Makefile")):
                sources.append(path)
    sources.append(DIRTYGEN / "tests/isa/spike/fixtures.json")
    sources = sorted(set(sources))
    snapshot = output / "source-inputs.tar.gz"
    with tarfile.open(snapshot, "w:gz") as archive:
        for path in sources: archive.add(path, arcname=str(path.relative_to(NAX)))
    isa = Path("/mnt/files/inochi/cache/docs/riscv-isa-manual")
    sbi = Path("/mnt/files/inochi/cache/docs/riscv-sbi-doc")
    normative = [isa / p for p in ("src/priv/supervisor.adoc", "src/priv/hypervisor.adoc", "src/priv/machine.adoc",
                                  "src/priv/svadu.adoc", "src/unpriv/zicsr.adoc", "src/unpriv/zifencei.adoc",
                                  "src/unpriv/rvwmo.adoc")]
    normative += [sbi / "src/ext-rfence.adoc", sbi / "src/binary-encoding.adoc",
                  Path("/home/inochi/code/spec/presentation/riscv/shpgat/mail/shdlt.adoc")]
    external_patches = {}
    for name, repository in (("VexiiRiscv", ROOT), ("Spike", ROOT / "ext/riscv-isa-sim"),
                             ("RVLS", ROOT / "ext/rvls")):
        patch = output / (name + "-existing-worktree.patch")
        patch.write_bytes(git(repository, "diff", "HEAD", "--binary"))
        external_patches[name] = reference(patch)
    manifest = {"schema": "shdlt-isa-consistency-inputs-v1", "scope": "phase2-tests-only",
                "nax_head": git(NAX, "rev-parse", "HEAD").decode().strip(),
                "protected_before": before, "protected_after_matches": True,
                "external_existing_worktree_patches": external_patches,
                "source_files": [reference(p) for p in sources], "source_snapshot": reference(snapshot),
                "normative": {"isa_head": git(isa, "rev-parse", "HEAD").decode().strip(),
                              "sbi_head": git(sbi, "rev-parse", "HEAD").decode().strip(),
                              "files": [reference(p) for p in normative]},
                "toolchain": {tool: subprocess.check_output([tool, "--version"], text=True).splitlines()[0]
                              for tool in ("riscv64-elf-gcc", "riscv64-linux-gnu-gcc", "verilator", "python3")},
                "families": inputs, "mc": mc, "mc_run_inputs": mc_runs,
                "legacy_rebuild": reference(args.legacy_rebuild),
                "unit_test_logs": [reference(p) for p in args.unit_log],
                "spike": spike, "spike_results": reference(args.spike_root / "results.json"),
                "rvls_check": False, "mc_counter_contract": "abi-v2:5*N+5;CSR-I-fences"}
    for name, document in (("shdlt_isa_consistency_inputs.json", manifest),
                           ("shdlt_isa_consistency_results.json", results)):
        (output / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in results.items() if not isinstance(v, list)}, indent=2))


if __name__ == "__main__":
    main()
