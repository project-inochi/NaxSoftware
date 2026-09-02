import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "rtl_report.py"
SPEC = importlib.util.spec_from_file_location("rtl_report", MODULE_PATH)
rtl_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = rtl_report
SPEC.loader.exec_module(rtl_report)


class RtlReportTest(unittest.TestCase):
    def test_trace_classifies_and_attributes_private_buffers(self):
        text = "\n".join([
            "rv new 0 RV64 0 0 0 0 0 0",
            "rv new 1 RV64 0 0 0 0 0 0",
            "rv mmu store 0 0000000082010000 8 0000000000030000 0",
            "rv mmu store 1 0000000082810000 8 0000000000040000 0",
            "rv mmu store 1 0000000081005010 8 00000000000000c7 0",
            "rv trap 1 0 24",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracer.log"
            path.write_text(text)
            summary = rtl_report.parse_trace(path, "race", 2)
        self.assertEqual(summary.appends, 2)
        self.assertEqual(summary.pte_updates, 1)
        self.assertEqual(summary.dirty_log_faults, 1)
        self.assertEqual(summary.attribution_errors, 0)

    def test_cross_hart_buffer_is_rejected(self):
        text = "\n".join([
            "rv new 0 RV64 0 0 0 0 0 0",
            "rv new 1 RV64 0 0 0 0 0 0",
            "rv mmu store 0 0000000082810000 8 0000000000030000 0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracer.log"
            path.write_text(text)
            summary = rtl_report.parse_trace(path, "race", 2)
        self.assertEqual(summary.attribution_errors, 1)

    def test_dirtygen_replacement_slots_are_appends(self):
        text = "\n".join([
            "rv new 0 RV64 0 0 0 0 0 0",
            "rv mmu store 0 000000008000c000 8 0000000000010000 0",
            "rv mmu store 0 0000000080018000 8 0000000000020000 0",
            "rv mmu store 0 0000000080206000 8 00000000200040c7 0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracer.log"
            path.write_text(text)
            summary = rtl_report.parse_trace(path, "dirtygen", 1)
        self.assertEqual(summary.appends, 2)
        self.assertEqual(summary.pte_updates, 1)
        self.assertEqual(summary.attribution_errors, 0)

    def test_missing_trace_hart_is_rejected(self):
        text = "rv new 0 RV64 0 0 0 0 0 0\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracer.log"
            path.write_text(text)
            with self.assertRaises(ValueError):
                rtl_report.parse_trace(path, "race", 2)

    def test_optional_missing_trace_is_explicitly_unavailable(self):
        summary = rtl_report.parse_trace(None, "race", 2, require_trace=False)
        self.assertFalse(summary.available)
        self.assertEqual(summary.cpus, 2)
        self.assertEqual(summary.mmu_stores, 0)
        with self.assertRaises(ValueError):
            rtl_report.parse_trace(None, "race", 2)

    def test_optional_mode_never_downgrades_malformed_present_trace(self):
        text = "rv new 0 RV64 0 0 0 0 0 0\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracer.log"
            path.write_text(text)
            with self.assertRaises(ValueError):
                rtl_report.parse_trace(path, "race", 2, require_trace=False)

    def test_bad_implicit_store_shape_is_counted(self):
        text = "\n".join([
            "rv new 0 RV64 0 0 0 0 0 0",
            "rv mmu store 3 0000000082010000 4 0000000000030001 1",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracer.log"
            path.write_text(text)
            summary = rtl_report.parse_trace(path, "race", 1)
        self.assertGreater(summary.attribution_errors, 0)

    def test_csr_contract(self):
        records = []
        for case in range(5):
            trap_count = 4 if case in (1, 4) else 0
            cause = 2 if case == 1 else (22 if case == 4 else 0)
            target = 3 if case == 1 else (1 if case == 4 else 0)
            records.append(
                f"SHDLT_RTL_HART abi=0x1 case=0x{case:x} status=0x0 "
                f"trap_count=0x{trap_count:x} cause=0x{cause:x} trap_target=0x{target:x}"
            )
        records.append("SHDLT_RTL_END abi=0x1 cases=0x5 failures=0x0 status=0x0")
        trace = rtl_report.TraceSummary(1, 0, 0, 0, 10, 0, 0)
        details = rtl_report.validate_csr("\n".join(records), trace)
        self.assertEqual(details["cases"], 5)

    def test_smoke_accepts_interleaved_uart_after_all_hart_pass(self):
        text = "\n".join([
            "SHDSLHTD_LMTC__MSCA_MSPALMEP interleaved",
            "[Done] Simulation done in 123.000 ms",
            "[395/395, SUCCESS] mill Test.runMain",
        ])
        details = rtl_report.validate_smoke(text, 2, "load_only")
        self.assertEqual(details["harts"], 2)
        self.assertEqual(details["decoded_uart_records"], 0)
        self.assertIn("pass-policy-all", details["result_contract"])

    def test_smoke_checks_intact_records(self):
        text = "\n".join([
            "SHDLT_MC_SAMPLE case=0x1 hart=0x0 entries=0x0 status=0x600d",
            "SHDLT_MC_SAMPLE case=0x1 hart=0x1 entries=0x0 status=0x600d",
            "[Done] Simulation done in 123.000 ms",
            "[395/395, SUCCESS] mill Test.runMain",
        ])
        details = rtl_report.validate_smoke(text, 2, "load_only")
        self.assertEqual(details["decoded_uart_records"], 2)
        self.assertEqual(details["entries_decoded"], 0)

    def test_smoke_rejects_failed_decoded_record(self):
        text = "\n".join([
            "SHDLT_MC_SAMPLE case=0x1 hart=0x0 status=0xbad",
            "[Done] Simulation done in 123.000 ms",
            "[395/395, SUCCESS] mill Test.runMain",
        ])
        with self.assertRaises(ValueError):
            rtl_report.validate_smoke(text, 2, "load_only")

    def test_cli_accepts_architecture_only_without_trace(self):
        text = "SHDLT_RACE_END case=0x0 cpus=0x2 status=0x0\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "run.log"
            output = root / "result.json"
            log.write_text(text)
            completed = __import__("subprocess").run(
                [sys.executable, str(MODULE_PATH),
                 "--family", "race", "--case", "different_pages", "--cpus", "2",
                 "--log", str(log), "--json", str(output)],
                text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = __import__("json").loads(output.read_text())
            self.assertFalse(result["trace_available"])
            self.assertFalse(result["trace"]["available"])


if __name__ == "__main__":
    unittest.main()
