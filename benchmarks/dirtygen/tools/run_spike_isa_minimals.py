#!/usr/bin/env python3
"""Rebuild and execute the 12 bounded Spike PTE/Svadu acceptance regressions."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from shdlt_isa_audit import DIRTYGEN, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spike", default="spike")
    parser.add_argument("--cc", default="riscv64-linux-gnu-gcc")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    spike = shutil.which(args.spike)
    if spike is None:
        parser.error("provide an existing Spike executable with --spike")
    output = args.output_root.resolve()
    if not output.is_relative_to(DIRTYGEN / "build"):
        parser.error("output must be inside dirtygen/build")
    output.mkdir(parents=True, exist_ok=False)
    source = DIRTYGEN / "tests/isa/spike"
    fixtures = json.loads((source / "fixtures.json").read_text())
    cases = [dict(name=f"rv{xlen}-{stage}-fenced", isa=f"rv{xlen}iah_zicsr_svadu",
                  harts=1, xlen=xlen, stage=index) for xlen in (32, 64)
             for index, stage in enumerate(("s", "vs", "g"))] + fixtures
    results = {"schema": "spike-isa-minimals-v1", "spike": str(Path(spike).resolve()),
               "spike_sha256": sha256(Path(spike)), "compiler": subprocess.check_output(
                   [args.cc, "--version"], text=True).splitlines()[0], "results": []}
    for case in cases:
        name = case["name"]
        elf = output / (name + ".elf")
        xlen = case.get("xlen", 64)
        recovered = "historical_elf_sha256" in case
        assembly = source / (name + ".S" if recovered else "pte_rsw.S")
        linker = source / (name + ".ld" if recovered else "link.ld")
        build = [args.cc, f"-march=rv{xlen}iah_zicsr", "-mabi=" + ("lp64" if xlen == 64 else "ilp32"),
                 "-nostdlib", "-nostartfiles", "-static", "-fno-pie", "-no-pie",
                 "-Wl,--no-relax", "-Wl,--build-id=none", "-Wl,-T," + str(linker)]
        if not recovered:
            build += [f"-DSTAGE={case['stage']}", "-DFENCED=1"]
        build += [str(assembly), "-o", str(elf)]
        with (output / (name + "-build.log")).open("w") as stream:
            subprocess.run(build, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if recovered:
            for section, expected in case["loadable_section_sha256"].items():
                payload = subprocess.check_output(["riscv64-linux-gnu-objcopy", "-O", "binary",
                                                   "--only-section=" + section, str(elf), "/dev/stdout"])
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise RuntimeError(f"recovered {name} {section} differs from historical ELF")
        command = [spike, "--isa=" + case["isa"], "-p" + str(case["harts"]), "-m128", str(elf)]
        with (output / (name + ".log")).open("w") as stream:
            try:
                code = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=20).returncode
            except subprocess.TimeoutExpired:
                code = 124
        results["results"].append(dict(name=name, build=build, command=command,
                                       elf_sha256=sha256(elf), source_sha256=sha256(assembly),
                                       exit_code=code, status="PASS" if code == 0 else "UNVERIFIED"))
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"{name}: exit={code}", flush=True)
    return int(any(item["exit_code"] for item in results["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
