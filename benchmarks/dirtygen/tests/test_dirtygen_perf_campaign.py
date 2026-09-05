import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


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
            set(metadata["repositories"]),
            {"VexiiRiscv", "NaxSoftware", "Spike", "RVLS"},
        )
        for state in metadata["repositories"].values():
            self.assertEqual(len(state["head"]), 40)
            self.assertIn("branch", state)
            self.assertIn("dirty", state)
            self.assertIsInstance(state["status"], list)
        self.assertEqual(metadata["cpu_config"]["seed"], 2)
        self.assertEqual(metadata["commands"]["simulation"]["argv"], mill)
        self.assertIn("shell", metadata["commands"]["build"])
        self.assertIn("sha256", metadata["artifact"])

    def test_stale_rvls_trace_is_not_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            output = Path(directory) / "output"
            output.mkdir()
            trace = run_dirtygen_perf.rvls_trace_path(repo, "smoke", "rvls")
            trace.parent.mkdir(parents=True)
            trace.write_text("old trace\n", encoding="utf-8")
            previous = run_dirtygen_perf.trace_signature(trace)
            self.assertFalse(
                run_dirtygen_perf.copy_rvls_trace(
                    repo, "smoke", "rvls", output, previous
                )
            )
            trace.write_text("new trace with changed size\n", encoding="utf-8")
            self.assertTrue(
                run_dirtygen_perf.copy_rvls_trace(
                    repo, "smoke", "rvls", output, previous
                )
            )
            self.assertEqual(
                (output / "tracer.log").read_text(encoding="utf-8"),
                "new trace with changed size\n",
            )

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


if __name__ == "__main__":
    unittest.main()
