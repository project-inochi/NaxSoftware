import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "run_dirtygen_perf_mc.py"
SPEC = importlib.util.spec_from_file_location("run_dirtygen_perf_mc", MODULE_PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)
REPO_ROOT = runner.find_repo_root(Path(__file__))


class McCampaignTest(unittest.TestCase):
    def test_trace_path_honors_spinal_workspace(self):
        root = Path("/repo")
        with mock.patch.dict(os.environ, {"SPINALSIM_WORKSPACE": "build/sim-worker"}):
            self.assertEqual(
                runner.trace_path(root, "run"),
                root / "build/sim-worker/TestBenchDut/run/tracer.log",
            )
        with mock.patch.dict(os.environ, {"SPINALSIM_WORKSPACE": "/tmp/sim-worker"}):
            self.assertEqual(
                runner.trace_path(root, "run"),
                Path("/tmp/sim-worker/TestBenchDut/run/tracer.log"),
            )
    def test_build_and_artifact_select_exact_variant(self):
        for harts in (1, 2, 4):
            for workload in ("private-strong", "private-weak", "same-pte"):
                for baseline in ("B0", "B1", "B2", "B3"):
                    command = runner.build_command(REPO_ROOT, harts, workload, baseline)
                    self.assertIn(f"PERF_MC_HARTS={harts}", command)
                    self.assertIn(f"PERF_MC_WORKLOAD={workload}", command)
                    self.assertIn(f"PERF_MC_BASELINE={baseline[1:]}", command)
                    self.assertTrue(str(runner.elf_path(REPO_ROOT, harts, workload, baseline)).endswith(
                        f"build/perf-mc-v2-h{harts}-{workload}-b{baseline[1:]}/dirtygen_perf_mc.elf"))

    def test_prefilled_build_and_artifact_are_independent(self):
        for harts in (2, 4):
            for baseline in ("B2", "B3"):
                command = runner.build_command(REPO_ROOT, harts, "prefilled-same-pte", baseline)
                self.assertIn("perf-mc-prefilled", command)
                self.assertNotIn("PERF_MC_WORKLOAD=prefilled-same-pte", command)
                self.assertTrue(str(runner.elf_path(REPO_ROOT, harts, "prefilled-same-pte", baseline)).endswith(
                    f"build/perf-mc-v2-prefilled-h{harts}-b{baseline[1:]}/dirtygen_perf_mc_prefilled.elf"))

    @mock.patch.object(runner.shutil, "which", return_value="/usr/bin/mill")
    def test_mill_cpu_options_and_modes(self, _which):
        architecture = runner.mill_command(REPO_ROOT, 4, "same-pte", "B3", "I0", "exp", "architecture", 17, "run")
        rvls = runner.mill_command(REPO_ROOT, 4, "same-pte", "B3", "I0", "exp", "rvls", 17, "run")
        for command in (architecture, rvls):
            self.assertEqual(command.count("Test[2.13.12].runMain"), 1)
            self.assertIn("--cpu-count", command); self.assertIn("4", command)
            self.assertIn("--performance-counters", command)
            self.assertIn("--lsu-l1-coherency", command)
            self.assertIn("--with-rvls-log", command)
            self.assertIn("--pass-policy", command); self.assertIn("all", command)
            self.assertIn("--fail-policy", command); self.assertIn("any", command)
        self.assertIn("--no-rvls-check", architecture)
        self.assertNotIn("--no-rvls-check", rvls)
        one = runner.mill_command(REPO_ROOT, 1, "private-weak", "B0", "I1", "exp", "architecture", 2, "run")
        self.assertNotIn("--lsu-l1-coherency", one)

    def test_metadata_records_selection_block_and_actual_repositories(self):
        build = ["make"]; mill = ["/bin/sh", "/usr/bin/mill"]; report = ["python3"]
        repos = {name: {"head": name, "tracked_dirty": False} for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")}
        with mock.patch.object(runner, "repository_states", return_value=repos), \
             mock.patch.object(runner, "top_level_gitlinks", return_value={"NaxSoftware": {"matches_actual": False}}), \
             mock.patch.object(runner, "toolchain_information", return_value={"test": True}):
            metadata = runner.initial_metadata(REPO_ROOT, 2, "private-strong", "B3", "I2", "experiment", "rvls", 101, "run", build, mill, report)
        self.assertEqual(metadata["schema"], "shdlt-dirtygen-perf-mc-campaign-v2")
        self.assertEqual(metadata["launch_order"], ["B2", "B3", "B1", "B0"])
        self.assertEqual(metadata["launch_position"], 1)
        self.assertTrue(metadata["fresh_reset"])
        self.assertEqual(metadata["simulation_seed"], metadata["cpu_config"]["seed"])
        self.assertTrue(metadata["trace_required"] and metadata["trace_requested"])
        self.assertEqual(metadata["repositories"], repos)

    def test_fingerprints_include_code_and_selection(self):
        elf = runner.elf_path(REPO_ROOT, 2, "same-pte", "B3")
        if not elf.is_file():
            self.skipTest("representative perf-mc ELF has not been built")
        data = runner.fingerprints(elf)
        for name in ("elf_sha256", "text_sha256", "text_init_sha256", "workload_code_sha256",
                     "timed_window_sha256", "selection_sha256"):
            self.assertEqual(len(data[name]), 64)
        self.assertEqual(data["selection"]["hart_count"], 2)
        self.assertEqual(data["selection"]["workload"], 2)
        self.assertEqual(data["selection"]["baseline"], 3)
        self.assertEqual(data["selection"]["runs"], 6)

    @mock.patch.object(runner.shutil, "which", return_value="/usr/bin/mill")
    @mock.patch.object(runner, "find_repo_root", return_value=REPO_ROOT)
    def test_dry_run_is_side_effect_free_and_one_process(self, _root, _which):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "absent"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = runner.main(["--hart-count", "2", "--workload", "private-weak",
                                      "--baseline", "B1", "--isolation-block-id", "I1",
                                      "--experiment-id", "dry", "--mode", "architecture",
                                      "--seed", "17", "--output-root", str(output), "--dry-run"])
            self.assertEqual(status, 0); self.assertFalse(output.exists())
            document = json.loads(stdout.getvalue())
            self.assertEqual(document["simulation"].count("Test[2.13.12].runMain"), 1)
            self.assertIn("--no-rvls-check", document["simulation"])
            self.assertEqual(document["cpu_config"]["seed"], 17)

    @mock.patch.object(runner.shutil, "which", return_value="/usr/bin/mill")
    @mock.patch.object(runner, "find_repo_root", return_value=REPO_ROOT)
    def test_prefilled_dry_run_and_selection_restrictions(self, _root, _which):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = runner.main(["--hart-count", "4", "--workload", "prefilled-same-pte",
                                  "--baseline", "B3", "--isolation-block-id", "I0",
                                  "--experiment-id", "prefilled", "--mode", "rvls", "--dry-run"])
        self.assertEqual(status, 0)
        document = json.loads(stdout.getvalue())
        self.assertIn("perf-mc-prefilled", document["build"])
        self.assertNotIn("--no-rvls-check", document["simulation"])
        for invalid in (("1", "B3"), ("2", "B0")):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                runner.parse_args(["--hart-count", invalid[0], "--workload", "prefilled-same-pte",
                                   "--baseline", invalid[1], "--isolation-block-id", "I0",
                                   "--experiment-id", "prefilled", "--mode", "architecture"])


if __name__ == "__main__":
    unittest.main()
