#!/usr/bin/env python3
"""Capture/verify the frozen inputs without rebuilding or repinning them."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
NAX = Path(__file__).resolve().parents[3]
DIRTYGEN = NAX / "benchmarks/dirtygen"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(path: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(path), *args])


def protected_state() -> dict:
    manifest = NAX / "baremetal/rtl_directed_shdlt/binaries.sha256"
    paths = {manifest, DIRTYGEN / "SHDLT_VALIDATION_AUDIT.md",
             DIRTYGEN / "audit/shdlt_validation_inputs.json",
             NAX / "baremetal/rtl_directed_shdlt/tools/run_matrix.sh"}
    for line in manifest.read_text().splitlines():
        if line.strip():
            paths.add(ROOT / line.split(maxsplit=1)[1])
    frozen = json.loads((DIRTYGEN / "audit/shdlt_validation_inputs.json").read_text())
    for _, path, _ in frozen["hashes"]["artifacts"]:
        paths.add(ROOT / path)
    files = {str(path.relative_to(ROOT)): sha256(path) for path in sorted(paths)}
    repos = {}
    for name, path in (("VexiiRiscv", ROOT), ("Spike", ROOT / "ext/riscv-isa-sim"),
                       ("RVLS", ROOT / "ext/rvls")):
        repos[name] = {"head": git(path, "rev-parse", "HEAD").decode().strip(),
                       "diff_sha256": hashlib.sha256(git(path, "diff", "HEAD", "--binary")).hexdigest()}
    return {"schema": "shdlt-isa-protected-inputs-v1", "files": files,
            "external_repositories": repos,
            "gitlinks": git(ROOT, "ls-tree", "HEAD", "ext/NaxSoftware",
                            "ext/riscv-isa-sim", "ext/rvls").decode()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    actual = protected_state()
    if args.action == "capture":
        args.path.parent.mkdir(parents=True, exist_ok=True)
        with args.path.open("x") as stream:
            json.dump(actual, stream, indent=2, sort_keys=True)
            stream.write("\n")
    elif actual != json.loads(args.path.read_text()):
        raise SystemExit("protected input changed; do not refresh the legacy manifest")
    print(f"protected inputs: {args.action} PASS ({len(actual['files'])} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
