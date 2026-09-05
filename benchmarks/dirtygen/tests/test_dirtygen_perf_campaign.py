import contextlib
import importlib.util
import io
import json
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "run_dirtygen_perf.py"
SPEC = importlib.util.spec_from_file_location("run_dirtygen_perf", MODULE_PATH)
run_dirtygen_perf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_dirtygen_perf)
REPO_ROOT = run_dirtygen_perf.find_repo_root(Path(__file__))


def normalize_mode(command):
    result = []
    skip = False
    for token in command:
        if skip:
            skip = False
            continue
        if token == "--name":
            skip = True
            continue
        if token in ("--with-rvls-log", "--no-rvls-check"):
            continue
        result.append(token)
    return result


class DirtygenPerfCampaignTest(unittest.TestCase):
    def test_modes_share_elf_and_cpu_configuration(self):
        architecture = run_dirtygen_perf.mill_command(
            REPO_ROOT, "smoke", "architecture"
        )
        rvls = run_dirtygen_perf.mill_command(REPO_ROOT, "smoke", "rvls")
        self.assertEqual(normalize_mode(architecture), normalize_mode(rvls))
        self.assertIn("--no-rvls-check", architecture)
        self.assertNotIn("--with-rvls-log", architecture)
        self.assertIn("--with-rvls-log", rvls)
        self.assertNotIn("--no-rvls-check", rvls)

    def test_suites_select_separate_targets_and_elfs(self):
        full_build = run_dirtygen_perf.build_command(REPO_ROOT, "full")
        smoke_build = run_dirtygen_perf.build_command(REPO_ROOT, "smoke")
        self.assertEqual(full_build[-1], "perf")
        self.assertEqual(smoke_build[-1], "perf-rvls-smoke")
        self.assertIn("build/perf/dirtygen_perf.elf", str(
            run_dirtygen_perf.elf_path(REPO_ROOT, "full")
        ))
        self.assertIn("build/perf-rvls-smoke/dirtygen_perf.elf", str(
            run_dirtygen_perf.elf_path(REPO_ROOT, "smoke")
        ))

    def test_scheduled_profiles_select_masks_directories_and_macros(self):
        expected_masks = {
            "full": "0xffffffff",
            "smoke": "0x0f0000f0",
            "sensitivity": "0xf000f000",
        }
        for suite, mask in expected_masks.items():
            for index, schedule_id in enumerate(("S0", "S1", "S2", "S3")):
                with self.subTest(suite=suite, schedule_id=schedule_id):
                    build = run_dirtygen_perf.build_command(
                        REPO_ROOT, suite, schedule_id
                    )
                    directory = f"perf-{suite}-s{index}"
                    self.assertIn(f"BUILD_DIR=build/{directory}", build)
                    self.assertIn(f"PERF_CONFIG_MASK={mask}", build)
                    self.assertIn(f"PERF_SCHEDULE_ID={index}", build)
                    self.assertEqual(build[-1], "all")
                    self.assertIn(
                        f"build/{directory}/dirtygen_perf.elf",
                        str(run_dirtygen_perf.elf_path(
                            REPO_ROOT, suite, schedule_id
                        )),
                    )

    def test_schedule_and_seed_propagate_to_single_simulation(self):
        command = run_dirtygen_perf.mill_command(
            REPO_ROOT, "sensitivity", "architecture", "S2", 17
        )
        self.assertEqual(command.count("Test[2.13.12].runMain"), 1)
        self.assertEqual(
            command[command.index("--seed") + 1], "17"
        )
        self.assertEqual(
            command[command.index("--name") + 1],
            "shdlt_dirtygen_perf_sensitivity_architecture_s2_seed17",
        )
        self.assertTrue(any(
            item.endswith("build/perf-sensitivity-s2/dirtygen_perf.elf")
            for item in command
        ))
        report = run_dirtygen_perf.report_command(
            REPO_ROOT, "sensitivity", Path("console"), Path("report"), "S2"
        )
        self.assertEqual(report[report.index("--schedule-id") + 1], "S2")
        output = run_dirtygen_perf.default_output_root(
            REPO_ROOT, "sensitivity", "architecture", "S2", 17
        )
        self.assertTrue(str(output).endswith(
            "sensitivity-architecture-s2-seed17"
        ))

    def test_metadata_contains_heads_status_commands_and_cpu_config(self):
        build = run_dirtygen_perf.build_command(REPO_ROOT, "smoke")
        mill = run_dirtygen_perf.mill_command(REPO_ROOT, "smoke", "rvls")
        report = run_dirtygen_perf.report_command(
            REPO_ROOT, "smoke", Path("console.log"), Path("report")
        )
        metadata = run_dirtygen_perf.initial_metadata(
            REPO_ROOT, "smoke", "rvls", build, mill, report
        )
        self.assertEqual(
            metadata["schema"], "shdlt-dirtygen-perf-campaign-v2"
        )
        self.assertEqual(metadata["status"], "initialized")
        self.assertEqual(metadata["schedule_id"], "legacy")
        self.assertIsNone(metadata["exit_code"])
        self.assertIsNone(metadata["end_time"])
        self.assertEqual(len(metadata["run_id"]), 32)
        self.assertTrue(metadata["trace_required"])
        self.assertTrue(metadata["trace_requested"])
        self.assertFalse(metadata["trace_generated"])
        self.assertIsNone(metadata["trace_path"])
        self.assertEqual(
            set(metadata["repositories"]),
            {"VexiiRiscv", "NaxSoftware", "Spike", "RVLS"},
        )
        for state in metadata["repositories"].values():
            self.assertEqual(len(state["head"]), 40)
            self.assertIn("branch", state)
            self.assertIn("dirty", state)
            self.assertIsInstance(state["status"], list)
            self.assertIn("tracked_dirty", state)
            self.assertIn("untracked_dirty", state)
            self.assertIsInstance(state["tracked_status"], list)
            self.assertIsInstance(state["untracked_paths"], list)
        self.assertEqual(
            set(metadata["top_level_gitlinks"]),
            {"NaxSoftware", "Spike", "RVLS"},
        )
        for name, state in metadata["top_level_gitlinks"].items():
            self.assertEqual(len(state["gitlink_head"]), 40)
            self.assertEqual(
                state["actual_head"], metadata["repositories"][name]["head"]
            )
            self.assertEqual(
                state["matches_actual"],
                state["gitlink_head"] == state["actual_head"],
            )
        self.assertEqual(metadata["cpu_config"]["seed"], 2)
        self.assertEqual(metadata["simulation_seed"], 2)
        self.assertEqual(metadata["commands"]["simulation"]["argv"], mill)
        self.assertIn("shell", metadata["commands"]["build"])
        self.assertIn("sha256", metadata["artifact"])
        self.assertEqual(
            set(metadata["toolchain"]),
            {"python", "riscv_gcc", "java", "verilator", "mill"},
        )
        self.assertEqual(
            metadata["toolchain"]["mill"]["path"],
            str(Path(mill[1]).resolve()),
        )

    def test_metadata_records_actual_schedule_and_seed(self):
        build = run_dirtygen_perf.build_command(REPO_ROOT, "smoke", "S3")
        mill = run_dirtygen_perf.mill_command(
            REPO_ROOT, "smoke", "rvls", "S3", 9
        )
        report = run_dirtygen_perf.report_command(
            REPO_ROOT, "smoke", Path("console.log"), Path("report"), "S3"
        )
        metadata = run_dirtygen_perf.initial_metadata(
            REPO_ROOT, "smoke", "rvls", build, mill, report, "S3", 9
        )
        self.assertEqual(metadata["schedule_id"], "S3")
        self.assertEqual(metadata["simulation_seed"], 9)
        self.assertEqual(metadata["cpu_config"]["seed"], 9)
        self.assertIn("perf-smoke-s3", metadata["artifact"]["elf"])
        self.assertEqual(
            metadata["commands"]["report"]["argv"][
                metadata["commands"]["report"]["argv"].index("--schedule-id") + 1
            ],
            "S3",
        )

    def test_architecture_metadata_does_not_claim_a_trace(self):
        build = run_dirtygen_perf.build_command(REPO_ROOT, "smoke")
        mill = run_dirtygen_perf.mill_command(
            REPO_ROOT, "smoke", "architecture"
        )
        report = run_dirtygen_perf.report_command(
            REPO_ROOT, "smoke", Path("console.log"), Path("report")
        )
        metadata = run_dirtygen_perf.initial_metadata(
            REPO_ROOT, "smoke", "architecture", build, mill, report
        )
        self.assertFalse(metadata["trace_required"])
        self.assertFalse(metadata["trace_requested"])
        self.assertFalse(metadata["trace_generated"])
        self.assertIsNone(metadata["trace_path"])

    def test_stale_rvls_trace_is_not_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            output = Path(directory) / "output"
            output.mkdir()
            trace = run_dirtygen_perf.rvls_trace_path(repo, "smoke", "rvls")
            trace.parent.mkdir(parents=True)
            trace.write_text("old trace\n", encoding="utf-8")
            previous = run_dirtygen_perf.trace_signature(trace)
            self.assertIsNone(
                run_dirtygen_perf.copy_rvls_trace(
                    repo, "smoke", "rvls", output, previous
                )
            )
            trace.write_text("new trace with changed size\n", encoding="utf-8")
            copied = run_dirtygen_perf.copy_rvls_trace(
                repo, "smoke", "rvls", output, previous
            )
            self.assertEqual(copied, output / "tracer.log")
            self.assertEqual(
                (output / "tracer.log").read_text(encoding="utf-8"),
                "new trace with changed size\n",
            )
            self.assertIsNone(
                run_dirtygen_perf.copy_rvls_trace(
                    repo, "smoke", "architecture", output, None
                )
            )

    def test_trace_sources_are_distinct_by_schedule_and_seed(self):
        first = run_dirtygen_perf.rvls_trace_path(
            Path("/repo"), "smoke", "rvls", "S0", 2
        )
        second = run_dirtygen_perf.rvls_trace_path(
            Path("/repo"), "smoke", "rvls", "S1", 2
        )
        third = run_dirtygen_perf.rvls_trace_path(
            Path("/repo"), "smoke", "rvls", "S0", 3
        )
        self.assertEqual(len({first, second, third}), 3)

    def test_atomic_metadata_write_preserves_previous_document_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            run_dirtygen_perf.write_metadata(path, {"generation": 1})
            self.assertEqual(json.loads(path.read_text()), {"generation": 1})
            with mock.patch.object(
                run_dirtygen_perf.os, "replace", side_effect=OSError("replace failed")
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    run_dirtygen_perf.write_metadata(path, {"generation": 2})
            self.assertEqual(json.loads(path.read_text()), {"generation": 1})
            self.assertEqual(
                [item.name for item in Path(directory).iterdir()],
                ["metadata.json"],
            )

    @staticmethod
    def minimal_metadata(mode):
        return {
            "schema": "shdlt-dirtygen-perf-campaign-v2",
            "run_id": "test-run",
            "schedule_id": "legacy",
            "suite": "smoke",
            "mode": mode,
            "status": "initialized",
            "exit_code": None,
            "failure_stage": None,
            "failure_message": None,
            "start_time": "start",
            "end_time": None,
            "trace_required": mode == "rvls",
            "trace_requested": mode == "rvls",
            "trace_generated": False,
            "trace_path": None,
            "artifact": {"elf": "unused", "sha256": None},
            "build_exit_code": None,
            "simulation_exit_code": None,
            "report_exit_code": None,
        }

    def run_mocked_campaign(
        self, directory, mode="architecture", exits=(0, 0, 0),
        elf_present=True, trace_present=None, exception=None,
    ):
        root = Path(directory) / "repo"
        root.mkdir()
        elf = root / "dirtygen_perf.elf"
        if elf_present:
            elf.write_bytes(b"perf elf")
        output = Path(directory) / "campaign"
        mill = [
            "/bin/sh", "/mock/mill", "--with-rvls-log"
            if mode == "rvls" else "--no-rvls-check"
        ]
        effects = list(exits)
        if exception is not None:
            effects[0] = exception
        if trace_present is None:
            trace_present = mode == "rvls"

        def fake_run_logged(_command, _cwd, _log):
            result = effects.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        trace = output / "tracer.log" if trace_present else None
        patches = (
            mock.patch.object(run_dirtygen_perf, "find_repo_root", return_value=root),
            mock.patch.object(run_dirtygen_perf, "mill_command", return_value=mill),
            mock.patch.object(run_dirtygen_perf, "elf_path", return_value=elf),
            mock.patch.object(
                run_dirtygen_perf,
                "initial_metadata",
                return_value=self.minimal_metadata(mode),
            ),
            mock.patch.object(
                run_dirtygen_perf, "run_logged", side_effect=fake_run_logged
            ),
            mock.patch.object(
                run_dirtygen_perf, "copy_rvls_trace", return_value=trace
            ),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with contextlib.redirect_stderr(io.StringIO()):
                status = run_dirtygen_perf.main(
                    [
                        "--suite", "smoke", "--mode", mode,
                        "--output-root", str(output),
                    ]
                )
        metadata = json.loads((output / "metadata.json").read_text())
        return status, metadata

    def test_successful_campaign_has_a_complete_terminal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            status, metadata = self.run_mocked_campaign(directory)
        self.assertEqual(status, 0)
        self.assertEqual(metadata["status"], "passed")
        self.assertEqual(metadata["exit_code"], 0)
        self.assertIsNone(metadata["failure_stage"])
        self.assertIsNone(metadata["failure_message"])
        self.assertIsNotNone(metadata["end_time"])
        self.assertFalse(metadata["trace_generated"])
        self.assertIsNone(metadata["trace_path"])

    def test_rvls_success_records_the_copied_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            status, metadata = self.run_mocked_campaign(directory, mode="rvls")
        self.assertEqual(status, 0)
        self.assertEqual(metadata["status"], "passed")
        self.assertTrue(metadata["trace_required"])
        self.assertTrue(metadata["trace_requested"])
        self.assertTrue(metadata["trace_generated"])
        self.assertEqual(metadata["trace_path"], "tracer.log")

    def test_each_command_failure_records_its_stage_and_exit_code(self):
        cases = (
            ("build", (7,), 7),
            ("simulation", (0, 9), 9),
            ("report", (0, 0, 5), 5),
        )
        for expected_stage, exits, expected_exit in cases:
            with self.subTest(stage=expected_stage):
                with tempfile.TemporaryDirectory() as directory:
                    status, metadata = self.run_mocked_campaign(
                        directory, exits=exits
                    )
                self.assertEqual(status, expected_exit)
                self.assertEqual(metadata["status"], "failed")
                self.assertEqual(metadata["exit_code"], expected_exit)
                self.assertEqual(metadata["failure_stage"], expected_stage)
                self.assertTrue(metadata["failure_message"])
                self.assertIsNotNone(metadata["end_time"])

    def test_missing_elf_and_missing_trace_record_precise_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            status, metadata = self.run_mocked_campaign(
                directory, exits=(0,), elf_present=False
            )
        self.assertEqual(status, 1)
        self.assertEqual(metadata["failure_stage"], "artifact")

        with tempfile.TemporaryDirectory() as directory:
            status, metadata = self.run_mocked_campaign(
                directory, mode="rvls", exits=(0, 0), trace_present=False
            )
        self.assertEqual(status, 1)
        self.assertEqual(metadata["failure_stage"], "trace")
        self.assertFalse(metadata["trace_generated"])
        self.assertIsNone(metadata["trace_path"])

    def test_internal_exception_and_interrupts_update_metadata(self):
        cases = (
            (OSError("internal failure"), "failed", "internal", 1),
            (KeyboardInterrupt(), "interrupted", "build", 130),
            (
                run_dirtygen_perf.CampaignInterrupted(signal.SIGTERM),
                "interrupted", "build", 143,
            ),
        )
        for exception, expected_status, expected_stage, expected_exit in cases:
            with self.subTest(exception=type(exception).__name__):
                with tempfile.TemporaryDirectory() as directory:
                    status, metadata = self.run_mocked_campaign(
                        directory, exits=(0,), exception=exception
                    )
                self.assertEqual(status, expected_exit)
                self.assertEqual(metadata["status"], expected_status)
                self.assertEqual(metadata["exit_code"], expected_exit)
                self.assertEqual(metadata["failure_stage"], expected_stage)
                self.assertTrue(metadata["failure_message"])
                self.assertIsNotNone(metadata["end_time"])

    def test_dry_run_has_no_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = run_dirtygen_perf.main(
                    [
                        "--suite",
                        "smoke",
                        "--mode",
                        "architecture",
                        "--output-root",
                        str(output),
                        "--dry-run",
                    ]
                )
            self.assertEqual(status, 0)
            self.assertFalse(output.exists())
            self.assertIn("--no-rvls-check", stdout.getvalue())
            self.assertIn("dirtygen_perf_report.py", stdout.getvalue())
            self.assertEqual(stdout.getvalue().count("SIMULATE "), 1)

    def test_scheduled_dry_run_propagates_all_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = run_dirtygen_perf.main(
                    [
                        "--suite", "sensitivity",
                        "--mode", "architecture",
                        "--schedule-id", "S1",
                        "--seed", "23",
                        "--output-root", str(output),
                        "--dry-run",
                    ]
                )
            rendered = stdout.getvalue()
            self.assertEqual(status, 0)
            self.assertFalse(output.exists())
            self.assertIn("PERF_CONFIG_MASK=0xf000f000", rendered)
            self.assertIn("PERF_SCHEDULE_ID=1", rendered)
            self.assertIn("build/perf-sensitivity-s1/dirtygen_perf.elf", rendered)
            self.assertIn("--schedule-id S1", rendered)
            self.assertIn("--seed 23", rendered)
            self.assertEqual(rendered.count("SIMULATE "), 1)


if __name__ == "__main__":
    unittest.main()
