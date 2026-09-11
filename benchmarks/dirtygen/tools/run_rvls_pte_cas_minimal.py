#!/usr/bin/env python3
"""Build and run the RVLS PTE-CAS callback minimum reproducer."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def repo_root(path: Path) -> Path:
    for parent in path.resolve().parents:
        if (parent / "ext" / "rvls" / "Makefile").is_file():
            return parent
    raise RuntimeError("VexiiRiscv repository root was not found")


def commands(root: Path, output: Path) -> tuple[list[str], list[str]]:
    rvls = root / "ext" / "rvls"
    spike = root / "ext" / "riscv-isa-sim"
    source = (root / "ext" / "NaxSoftware" / "benchmarks" / "dirtygen" /
              "tests" / "rvls" / "pte_cas_callbacks.cpp")
    library = rvls / "build" / "apps" / "rvls.so"
    compile_command = [
        "c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-Wno-unused-variable",
        "-Wno-unused-function",
        f"-I{rvls / 'src'}", f"-I{spike / 'riscv'}",
        f"-I{spike / 'fesvr'}", f"-I{spike / 'softfloat'}",
        f"-I{spike / 'build'}", str(source), str(library),
        f"-Wl,-rpath,{library.parent}", "-lpthread", "-ldl",
        "-lboost_regex", "-o", str(output),
    ]
    return compile_command, [str(output)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = repo_root(Path(__file__))
    output_dir = (root / "ext" / "NaxSoftware" / "benchmarks" /
                  "dirtygen" / "build" / "audit" / "rvls-pte-cas-minimal")
    output = output_dir / "pte_cas_callbacks"
    compile_command, run_command = commands(root, output)
    if args.dry_run:
        print(json.dumps({"compile": compile_command, "run": run_command}, indent=2))
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(compile_command, cwd=root, check=True)
    subprocess.run(run_command, cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
