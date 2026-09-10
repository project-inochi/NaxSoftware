import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DIRTYGEN = Path(__file__).resolve().parents[1]
NAX = DIRTYGEN.parents[1]
sys.path.insert(0, str(DIRTYGEN / "tools"))
import shdlt_isa_report as isa
import run_shdlt_isa as runner
sys.path.insert(0, str(NAX / "benchmarks/cache_tlb_shdlt/tests"))
sys.path.insert(0, str(NAX / "baremetal/multicore_race_shdlt/tests"))
from test_ctc_report import transcript
from test_race_report import records, text


def corrected_ctc(case=0, harts=2):
    lines = transcript(case, harts).splitlines()
    result = [isa.PROFILE_LINE]
    for line in lines:
        if line.startswith("SHDLT_CTC_HART"):
            line = line.replace("outcome=0x2", "outcome=0x0").replace("fence_errors=0x1", "fence_errors=0x0")
            if case == 5:
                line = line.replace("final_index=0x2", "final_index=0x1").replace("entries=0x2", "entries=0x1").replace("log_bitmap=0x3", "log_bitmap=0x1")
            if case == 6:
                line = line.replace("old_mapping_bitmap=0x2", "old_mapping_bitmap=0x0")
            if case == 9:
                hart = isa.fields(line)["hart"]
                line = line.replace("old_mapping_bitmap=0x0", "old_mapping_bitmap=0x1")
                line = line.replace("new_mapping_bitmap=0x0", "new_mapping_bitmap=0x4" if hart & 1 else "new_mapping_bitmap=0x6")
        if case in (6, 7):
            line = line.replace(f"xfail=0x{harts:x}", "xfail=0x0").replace(" pass=0x0", f" pass=0x{harts:x}")
        if case == 5:
            line = line.replace(f"total_entries=0x{2*harts:x}", f"total_entries=0x{harts:x}")
        result.append(line)
    return "\n".join(result)


class IsaProfileTests(unittest.TestCase):
    def test_smoke_rejects_duplicate_fields_and_missing_begin(self):
        values = dict(case=1, a=0xffff, d=0, expected=0, actual=0, initial=0,
                      final=0, entries=0, unique=0, dup=0, missing=0, extra=0,
                      data_errors=0, faults=0, status=0x600d)
        good = "SHDLT_MC_BEGIN\n" + "\n".join(
            "SHDLT_MC_SAMPLE " + " ".join(f"{k}=0x{v:x}" for k, v in dict(values, hart=h).items())
            for h in (0, 1)) + "\nSHDLT_MC_END\n"
        isa.validate_smoke(good, 2, "load_only")
        for bad in (good.replace("status=0x600d", "status=0xbad status=0x600d"),
                    good.replace("SHDLT_MC_BEGIN\n", ""),
                    good.replace("hart=0x0", "hart=0x0 broken")):
            with self.assertRaises(ValueError): isa.validate_smoke(bad, 2, "load_only")

    def test_selection_coverage_and_legacy_boundary(self):
        self.assertEqual(len(runner.selections()), 42)
        self.assertEqual(len(runner.selections(True)), 50)
        with self.assertRaises(ValueError): isa.require_profile(transcript())
        with self.assertRaises(ValueError): isa.require_profile(isa.PROFILE_LINE + "\n" + isa.PROFILE_LINE)

    def test_ctc_completion_required(self):
        good = corrected_ctc()
        isa.ctc_report.parse_text(good, profile="isa")
        for bad in (good.replace("done=0x1", "done=0x0"),
                    "\n".join(l for l in good.splitlines() if not l.startswith("SHDLT_CTC_END"))):
            with self.assertRaises(ValueError): isa.ctc_report.parse_text(bad, profile="isa")

    def test_ctc_legal_overfence_and_real_vmid(self):
        for harts in (2, 4):
            for case in (6, 7):
                good = corrected_ctc(case, harts)
                for vmid in (0, 1, 0x3fff):
                    isa.ctc_report.parse_text(good.replace("readback_vmid=0x0", f"readback_vmid=0x{vmid:x}"), profile="isa")
                if case == 6:
                    retained = good.replace("new_mapping_bitmap=0x3", "new_mapping_bitmap=0x1").replace("old_mapping_bitmap=0x0", "old_mapping_bitmap=0x2")
                    isa.ctc_report.parse_text(retained, profile="isa")
                else:
                    with self.assertRaises(ValueError):
                        isa.ctc_report.parse_text(good.replace("new_mapping_bitmap=0x3", "new_mapping_bitmap=0x1"), profile="isa")

    def test_independent_repeated_epoch(self):
        isa.ctc_report.parse_text(corrected_ctc(5), profile="isa")
        with self.assertRaises(ValueError):
            isa.ctc_report.parse_text(isa.PROFILE_LINE + "\n" + transcript(5), profile="isa")

    def test_isolation_idle_interval_is_not_an_observation(self):
        good = corrected_ctc(9)
        isa.ctc_report.parse_text(good, profile="isa")
        with self.assertRaisesRegex(ValueError, "actual target"):
            isa.ctc_report.parse_text(good.replace("old_mapping_bitmap=0x1", "old_mapping_bitmap=0x2"), profile="isa")

    def test_duplicate_global_commit_repro(self):
        rows = records(6, 2)
        rows[1][1].update(entries=1, final=1, log_bitmap=1)
        rows[2].update(total_entries=2, recorded_harts=3)
        # Preserve the historical parser behavior, reject it in the new profile.
        isa.race_report.parse_text(text(rows))
        with self.assertRaises(ValueError):
            isa.race_report.parse_text(isa.PROFILE_LINE + "\n" + text(rows), profile="isa")
        ctc = corrected_ctc(4).replace("final_index=0x0", "final_index=0x1").replace("entries=0x0", "entries=0x1").replace("log_bitmap=0x0", "log_bitmap=0x1").replace("total_entries=0x1", "total_entries=0x2")
        with self.assertRaises(ValueError): isa.ctc_report.parse_text(ctc, profile="isa")

    def test_legal_superseded_and_invalid_physical_evidence(self):
        lines = ["rv mmu physical-store 0 1 1 1 83010000 8 00040000 0 pending",
                 "rv mmu physical-store 0 1 1 2 83010000 8 00040000 0 committed",
                 "rv mmu store 0 83010000 8 00040000 0",
                 "rv mmu store 0 81008200 8 204800d7 0"]
        self.assertEqual(isa.check_lifecycle(iter(lines), "ctc", 4)["physical_attempts"], 1)
        loser = ["rv mmu physical-store 1 2 2 1 83810000 8 00040000 0 pending",
                 "rv mmu physical-store 1 2 2 2 83810000 8 00040000 0 superseded"]
        self.assertEqual(isa.check_lifecycle(iter(lines + loser), "ctc", 4)["superseded"], 1)
        bads = [lines + [lines[1]], lines[:1] + lines[2:], lines[:2] + lines[3:],
                [l.replace("store 0 81008200", "store 1 81008200") for l in lines],
                [l.replace("physical-store 0", "physical-store 4") for l in lines],
                [l.replace("00040000", "00040001") for l in lines],
                lines + ["rv mmu physical-store broken"]]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                isa.check_lifecycle(iter(bad), "ctc", 4)

    def test_firmware_raw_log_reserved_bits(self):
        with tempfile.TemporaryDirectory() as temporary:
            exe = Path(temporary) / "log-word"
            subprocess.run(["cc", "-O2", "-I" + str(NAX / "baremetal/rtl_directed_shdlt/include"),
                            str(DIRTYGEN / "tests/isa/log_word.c"), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_actual_poll_disassembly_rejects_broken_synchronization(self):
        with tempfile.TemporaryDirectory() as temporary:
            for broken in (None, "BAD_POLL", "BAD_ACQUIRE"):
                obj = Path(temporary) / ((broken or "good") + ".elf")
                command = ["riscv64-elf-gcc", "-Os", "-march=rv64ia_zicsr", "-mabi=lp64",
                           "-I" + str(NAX / "baremetal/rtl_directed_shdlt/include"),
                           "-nostdlib", "-Wl,--no-relax", "-Wl,-e,consume",
                           str(DIRTYGEN / "tests/isa/sync.c"), "-o", str(obj)]
                if broken: command.append("-D" + broken)
                subprocess.run(command, check=True)
                if broken:
                    with self.assertRaisesRegex(ValueError, "reload.*acquire"):
                        isa.inspect_elf(obj, "ctc")
                else:
                    self.assertTrue(isa.inspect_elf(obj, "ctc")["poll_reloads"])


if __name__ == "__main__":
    unittest.main()
