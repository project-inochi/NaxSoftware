import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import run_dirtygen_epoch as runner
import run_dirtygen_epoch_phase3 as phase3


class EpochCampaignTest(unittest.TestCase):
    def test_schedule_counts_and_backend_order(self):
        expected = {"architecture-smoke": 6, "rvls-smoke": 12,
                    "stage3": 18, "full-architecture": 68}
        for phase, count in expected.items():
            schedule = phase3.selected_schedule(phase)
            self.assertEqual(len(schedule), count)
            self.assertEqual(len(schedule) * 6, count * 6)
            for index in range(0, len(schedule), 2):
                pair = schedule[index:index + 2]
                self.assertEqual(tuple(row.backend for row in pair),
                                 phase3.BLOCKS[pair[0].block])

    def test_runner_selection_paths_and_trace_modes(self):
        root = Path("/repo")
        self.assertIn("unique-p128-shdlt-log",
            str(runner.elf_path(root, "single", "unique", 128, 1, "shdlt-log")))
        self.assertIn("h4-same-pte-pte-scan-serial",
            str(runner.elf_path(root, "mc", "same-pte", None, 4,
                                "pte-scan-serial")))
        with mock.patch("run_dirtygen_epoch.shutil.which", return_value="/usr/bin/mill"):
            architecture = runner.mill_command(root, "single", "unique", 1, 1,
                "pte-scan-serial", "E0", "unit", "architecture", 2, "a")
            rvls = runner.mill_command(root, "mc", "same-pte", None, 4,
                "shdlt-log", "E0", "unit", "rvls", 2, "b")
            no_trace = runner.mill_command(root, "single", "unique", 1, 1,
                "pte-scan-serial", "E0", "unit", "architecture", 2, "c",
                "disabled")
        self.assertIn("--with-rvls-log", architecture)
        self.assertIn("--no-rvls-check", architecture)
        self.assertIn("--with-rvls-log", rvls)
        self.assertNotIn("--no-rvls-check", rvls)
        self.assertNotIn("--with-rvls-log", no_trace)
        self.assertIn("--no-rvls-check", no_trace)
        self.assertNotEqual(architecture[architecture.index("--name") + 1],
                            rvls[rvls.index("--name") + 1])

    def test_argument_rejects_illegal_profile_combinations(self):
        bad = [
            ["--profile", "single", "--workload", "unique", "--value", "7",
             "--hart-count", "1"],
            ["--profile", "single", "--workload", "unique", "--value", "1",
             "--hart-count", "2"],
            ["--profile", "mc", "--workload", "private-weak", "--value", "1",
             "--hart-count", "2"],
        ]
        common = ["--backend", "pte-scan-serial", "--epoch-block-id", "E0",
                  "--experiment-id", "unit", "--mode", "architecture"]
        for arguments in bad:
            with self.assertRaises(SystemExit):
                runner.parse_args(arguments + common)
        with self.assertRaises(SystemExit):
            runner.parse_args(["--profile", "single", "--workload", "unique",
                "--value", "1", "--hart-count", "1",
                "--host-timeout-seconds", "0"] + common)
        with self.assertRaises(SystemExit):
            runner.parse_args(["--profile", "single", "--workload", "unique",
                "--value", "1", "--hart-count", "1", "--trace-mode", "disabled",
                "--backend", "pte-scan-serial", "--epoch-block-id", "E0",
                "--experiment-id", "unit", "--mode", "rvls"])
        with self.assertRaises(SystemExit):
            runner.parse_args(["--profile", "single", "--workload", "unique",
                "--value", "1", "--hart-count", "1",
                "--prebuilt-elf-sha256", "bad"] + common)

    def test_extended_timeout_is_explicit_and_fingerprinted(self):
        selection = phase3.rvls_smoke_schedule()[6]
        command = phase3.command_for(Path("/repo"), selection, "unit", 2,
                                     Path("/out"), 5400)
        self.assertEqual(command[command.index("--host-timeout-seconds") + 1],
                         "5400")
        first = phase3.command_fingerprint(command, {"digest": "fixed"})
        command[command.index("--host-timeout-seconds") + 1] = "1800"
        self.assertNotEqual(first, phase3.command_fingerprint(
            command, {"digest": "fixed"}))

    def test_fingerprint_binds_command_and_source(self):
        source = {"digest": "one"}
        first = phase3.command_fingerprint(["run", "a"], source)
        self.assertNotEqual(first, phase3.command_fingerprint(["run", "b"], source))
        self.assertNotEqual(first, phase3.command_fingerprint(["run", "a"], {"digest": "two"}))

    def test_source_enumeration_prunes_generated_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src/build/deep").mkdir(parents=True)
            (root / "src/__pycache__").mkdir()
            (root / "src/keep.py").write_text("keep")
            (root / "src/build/deep/drop.py").write_text("drop")
            (root / "src/__pycache__/drop.pyc").write_text("drop")
            self.assertEqual(runner.scoped_files(root, "src"),
                             [root / "src/keep.py"])

    def test_orchestrator_is_fail_fast(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            completed = mock.Mock(returncode=7)
            with mock.patch("run_dirtygen_epoch_phase3.find_repo_root", return_value=Path("/repo")), \
                 mock.patch("run_dirtygen_epoch_phase3.source_fingerprint",
                            return_value={"digest": "fixed"}), \
                 mock.patch("run_dirtygen_epoch_phase3.subprocess.run",
                            return_value=completed) as invoked:
                with self.assertRaises(RuntimeError):
                    phase3.main(["--phase", "stage3", "--experiment-id", "unit",
                                 "--output-root", str(output)])
            self.assertEqual(invoked.call_count, 1)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["runs"][0]["status"], "failed")
            self.assertTrue(all(row["status"] == "pending"
                                for row in manifest["runs"][1:]))

    def test_dry_run_reports_exact_stage3_count(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(phase3.main(["--phase", "stage3", "--dry-run"]), 0)
        document = json.loads(stream.getvalue())
        self.assertEqual(document["selection_count"], 18)
        self.assertEqual(document["raw_sample_count"], 108)
        self.assertEqual(document["measured_sample_count"], 90)

    def test_dry_run_can_start_at_backend_pair_boundary(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(phase3.main(["--phase", "rvls-smoke", "--dry-run",
                "--start-index", "6", "--host-timeout-seconds", "5400"]), 0)
        document = json.loads(stream.getvalue())
        self.assertEqual(document["selection_count"], 6)
        self.assertEqual(document["raw_sample_count"], 36)
        self.assertEqual(document["measured_sample_count"], 30)
        self.assertEqual(document["start_index"], 6)
        self.assertEqual(document["host_timeout_seconds"], 5400)
        self.assertEqual(document["selections"][0]["harts"], 4)
        self.assertEqual(document["selections"][0]["workload"], "private-weak")


if __name__ == "__main__":
    unittest.main()
