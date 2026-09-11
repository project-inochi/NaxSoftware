import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import run_dirtygen_perf_mc_phase3 as phase3


class Phase3CampaignTest(unittest.TestCase):
    def test_rvls_gate_is_exact_d0_matrix(self):
        rows = phase3.rvls_gate_schedule()
        self.assertEqual(len(rows), 24)
        self.assertEqual(sum(1 for row in rows if row.mode == "rvls"), 12)
        self.assertEqual({row.harts for row in rows}, {2, 4})
        self.assertEqual({row.workload for row in rows},
                         {"private-weak", "same-pte", "prefilled-same-pte"})
        self.assertEqual({row.baseline for row in rows}, {"B2", "B3"})
        for offset in range(0, len(rows), 2):
            pair = rows[offset:offset + 2]
            self.assertEqual([row.mode for row in pair],
                             ["architecture", "rvls"])
            self.assertEqual(len({row.baseline for row in pair}), 1)
        for offset in range(0, len(rows), 4):
            self.assertEqual([row.baseline for row in rows[offset:offset + 4]],
                             ["B3", "B3", "B2", "B2"])

    def test_every_rvls_gate_run_immediately_follows_its_pair(self):
        rows = phase3.rvls_gate_schedule()
        for index, row in enumerate(rows):
            if row.mode != "rvls":
                continue
            self.assertGreater(index, 0)
            self.assertEqual(rows[index - 1],
                             phase3.dataclasses.replace(row,
                                                        mode="architecture"))

    def test_parallel_gate_groups_preserve_pair_and_baseline_order(self):
        groups = phase3.parallel_groups(phase3.rvls_gate_schedule())
        self.assertEqual(len(groups), 6)
        self.assertTrue(all(len(group) == 4 for group in groups))
        for group in groups:
            self.assertEqual(
                [(row.baseline, row.mode) for row in group],
                [("B3", "architecture"), ("B3", "rvls"),
                 ("B2", "architecture"), ("B2", "rvls")])
            self.assertEqual(len({(row.harts, row.workload)
                                  for row in group}), 1)

    def test_architecture_parallelism_keeps_block_barriers(self):
        stages = phase3.execution_stages("architecture")
        self.assertEqual([stage[0].block for stage in stages],
                         ["I0", "I1", "I2", "I3"])
        self.assertTrue(all({row.block for row in stage} == {stage[0].block}
                            for stage in stages))
        for stage in stages:
            for group in phase3.parallel_groups(stage):
                self.assertEqual([row.baseline for row in group],
                                 list(phase3.BLOCKS[group[0].block]))
                self.assertEqual(len({(row.harts, row.workload)
                                      for row in group}), 1)

    def test_architecture_schedule_contains_576_main_samples(self):
        rows = phase3.architecture_schedule()
        references = [row for row in rows if row.harts == 1]
        main = [row for row in rows if row.harts in (2, 4)]
        self.assertEqual(len(references), 12)
        self.assertEqual(len(main), 96)
        self.assertEqual(len(main) * 6, 576)
        for block, order in phase3.BLOCKS.items():
            selected = [row.baseline for row in rows
                        if row.block == block and row.harts == 2 and
                        row.workload == "private-strong"]
            self.assertEqual(selected, list(order))

    def test_dry_run_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing"
            with redirect_stdout(io.StringIO()):
                status = phase3.main(["--phase", "rvls-gate", "--limit", "1",
                                      "--output-root", str(output), "--dry-run"])
            self.assertEqual(status, 0)
            self.assertFalse(output.exists())

    def test_gate_pair_rejects_cycle_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arch = root / "arch"
            rvls = root / "rvls"
            for path in (arch, rvls):
                (path / "report").mkdir(parents=True)
                metadata = {"artifact": {name: name for name in (
                    "elf_sha256", "text_sha256", "text_init_sha256",
                    "workload_code_sha256", "timed_window_sha256",
                    "selection_sha256", "selection")}, "cpu_config": {"seed": 2}}
                (path / "metadata.json").write_text(json.dumps(metadata))
                (path / "report" / "samples.json").write_text(
                    json.dumps({"samples": [{"completion_cycles": 10}]}))
                (path / "report" / "trace-report.json").write_text(
                    json.dumps({"status": "PASS"}))
            (rvls / "report" / "samples.json").write_text(
                json.dumps({"samples": [{"completion_cycles": 11}]}))
            selection = phase3.Selection("rvls-gate", 2, "same-pte",
                                         "B3", "I0", "architecture")
            with self.assertRaisesRegex(RuntimeError, "DUT-cycle mismatch"):
                phase3.gate_pair_document(arch, rvls, selection)

    def test_rejects_unsafe_experiment_identifier(self):
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                phase3.parse_args(["--experiment-id", "../escape"])

    def test_rejects_unsafe_parallelism(self):
        for jobs in (0, 17):
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    phase3.parse_args(["--jobs", str(jobs)])

    def test_orchestrator_upgrade_rejects_non_runner_source(self):
        previous = {
            "digest": "old",
            "NaxSoftware": {"head": "h", "branch": "b", "digest": "a",
                            "files": [{"path": "benchmarks/dirtygen/a.c",
                                       "sha256": "old"}]},
        }
        current = {
            "digest": "new",
            "NaxSoftware": {"head": "h", "branch": "b", "digest": "z",
                            "files": [{"path": "benchmarks/dirtygen/a.c",
                                       "sha256": "new"}]},
        }
        manifest = {"source_fingerprint": previous}
        with self.assertRaisesRegex(RuntimeError, "disallowed source changes"):
            phase3.adopt_orchestrator_upgrade(manifest, current)


if __name__ == "__main__":
    unittest.main()
