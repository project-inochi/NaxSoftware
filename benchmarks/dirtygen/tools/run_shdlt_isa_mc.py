#!/usr/bin/env python3
"""Phase-2 MC build coverage and bounded, sequential ABI-v2 validation (not a performance campaign)."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import run_dirtygen_perf_mc as mc


def selections():
    return [(h, w, b) for h in (1, 2, 4)
            for w in ("private-strong", "private-weak", "same-pte")
            for b in ("B0", "B1", "B2", "B3")] + [
                (h, "prefilled-same-pte", b) for h in (2, 4) for b in ("B2", "B3")]


def required_runs():
    return [(1, "private-weak", b) for b in ("B0", "B1", "B2", "B3")] + [
        (h, "same-pte", b) for h in (2, 4) for b in ("B0", "B1", "B2", "B3")] + [
        (h, "prefilled-same-pte", b) for h in (2, 4) for b in ("B2", "B3")] + [
        (h, "private-strong", "B3") for h in (2, 4)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    root = mc.find_repo_root(Path(__file__))
    output = args.output_root.resolve()
    if not output.is_relative_to(mc.dirtygen_dir(root) / "build"):
        parser.error("output must be inside dirtygen/build")
    output.mkdir(parents=True, exist_ok=False)
    results = {"schema": "shdlt-isa-mc-validation-v2", "builds": [], "runs": []}
    def save():
        (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    for harts, workload, baseline in selections():
        name = f"h{harts}-{workload}-{baseline.lower()}"
        command = mc.build_command(root, harts, workload, baseline)
        code = mc.run_logged(command, root, output / f"{name}-build.log")
        entry = {"name": name, "command": command, "exit_code": code}
        if code == 0:
            entry["artifact"] = mc.fingerprints(mc.elf_path(root, harts, workload, baseline))
            if entry["artifact"]["selection"]["abi_version"] != 2:
                raise RuntimeError("legacy MC ELF rejected")
        results["builds"].append(entry); save()
        if code:
            return code
    # The ordinary and prefilled instruction timing contract must be identical.
    timed = {entry["artifact"]["timed_window_sha256"] for entry in results["builds"]}
    if len(timed) != 1:
        raise RuntimeError("MC timed instruction windows differ")
    print("MC ABI-v2 build coverage: PASS (40 selections, one timed-window hash)", flush=True)
    if not args.build_only:
        for harts, workload, baseline in required_runs():
            name = f"h{harts}-{workload}-{baseline.lower()}"
            command = [sys.executable, str(Path(mc.__file__)), "--hart-count", str(harts),
                       "--workload", workload, "--baseline", baseline,
                       "--isolation-block-id", "I0", "--experiment-id", "isa-phase2",
                       "--mode", "architecture", "--output-root", str(output / name)]
            code = subprocess.call(command, cwd=root)
            results["runs"].append({"name": name, "command": command, "exit_code": code,
                                    "result": str(output / name / "metadata.json")})
            save(); print(f"MC {name}: exit={code}", flush=True)
            if code:
                return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
