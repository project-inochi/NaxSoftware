import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import collect_dirtygen_epoch_phase4 as collector
import run_dirtygen_epoch_phase4 as phase4


class Completed:
    def __init__(self, returncode):
        self.returncode = returncode


def comparison_document():
    sources, pairings = [], []
    for config in phase4.configurations():
        for block in ("E0", "E1"):
            for backend in ("pte-scan-serial", "shdlt-log"):
                sources.append({"root": f"/{config.key}/{block}/{backend}",
                                "run_id": f"{config.key}-{block}-{backend}",
                                "backend": backend, "trace_status": "NOT_COLLECTED",
                                "elf_sha256": backend})
            for repetition in range(5):
                cycles = {"pte-scan-serial": {name: 20 for name in collector.CYCLE_METRICS},
                          "shdlt-log": {name: 10 for name in collector.CYCLE_METRICS}}
                metrics = {name: 10 for name in collector.METRICS}
                pairings.append({"mode": "architecture", "experiment_id": "unit",
                    "epoch_block_id": block, "profile": config.profile,
                    "hart_count": config.harts, "workload": config.workload,
                    "value": config.value, "simulation_seed": 2,
                    "repetition": repetition, "cycles": cycles, "metrics": metrics})
    return {"schema": "shdlt-dirtygen-epoch-comparison-v1", "status": "PASS",
            "counts": {"sources": 68, "groups": 34, "measured_pairings": 170},
            "sources": sources, "pairings": pairings}


class EpochPhase4Test(unittest.TestCase):
    def test_schedule_cardinality_canary_priority_and_order(self):
        pairs = phase4.pair_schedule()
        self.assertEqual(len(phase4.configurations()), 17)
        self.assertEqual(len(pairs), 34)
        self.assertEqual(pairs[0].key, "E0:single:h1:unique:1")
        self.assertEqual(tuple(row.backend for row in pairs[0].selections),
                         ("pte-scan-serial", "shdlt-log"))
        e0 = [pair for pair in pairs if pair.block == "E0"]
        e1 = [pair for pair in pairs if pair.block == "E1"]
        self.assertEqual(len(e0), 17); self.assertEqual(len(e1), 17)
        self.assertEqual(tuple(row.backend for row in e1[0].selections),
                         ("shdlt-log", "pte-scan-serial"))
        self.assertEqual(e0[1].config.harts, 4)

    def test_dry_run_reports_complete_matrix(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(phase4.main(["--dry-run"]), 0)
        data = json.loads(stream.getvalue())
        self.assertEqual((data["pair_count"], data["selection_count"]), (34, 68))
        self.assertEqual((data["raw_sample_count"], data["measured_sample_count"],
                          data["measured_pairing_count"]), (408, 340, 170))
        self.assertEqual(data["jobs"], 4)
        self.assertEqual(data["trace_policy"], "on-failure")

    def test_primary_command_disables_trace_and_binds_prebuild(self):
        selection = phase4.pair_schedule()[0].selections[0]
        command = phase4.run_command(Path("/repo"), selection, "unit", 2, 5400,
            Path("/out"), {"elf_sha256": "a" * 64}, "b" * 64, "disabled")
        self.assertEqual(command[command.index("--trace-mode") + 1], "disabled")
        self.assertEqual(command[command.index("--prebuilt-elf-sha256") + 1], "a" * 64)
        self.assertEqual(command[command.index("--expected-source-fingerprint") + 1],
                         "b" * 64)

    def test_first_failure_stops_and_runs_one_traced_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"

            def fake_prebuild(_repo, _root, manifest, save):
                for config in phase4.configurations():
                    for backend in ("pte-scan-serial", "shdlt-log"):
                        manifest["artifacts"][phase4.artifact_key(config, backend)] = {
                            "elf_sha256": "a" * 64}
                save()

            calls = []
            def fake_run(command, **_kwargs):
                calls.append(command)
                return Completed(7 if len(calls) == 1 else 0)

            with mock.patch("run_dirtygen_epoch_phase4.find_repo_root",
                            return_value=Path("/repo")), \
                 mock.patch("run_dirtygen_epoch_phase4.source_fingerprint",
                            return_value={"digest": "b" * 64}), \
                 mock.patch("run_dirtygen_epoch_phase4.prebuild",
                            side_effect=fake_prebuild), \
                 mock.patch("run_dirtygen_epoch_phase4.group_environment",
                            return_value={"SPINALSIM_WORKSPACE": "/sim",
                                          "MILL_OUTPUT_DIR": "/out"}), \
                 mock.patch("run_dirtygen_epoch_phase4.subprocess.run",
                            side_effect=fake_run):
                self.assertEqual(phase4.main(["--experiment-id", "unit", "--jobs", "1",
                    "--output-root", str(output)]), 7)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][calls[0].index("--trace-mode") + 1], "disabled")
            self.assertEqual(calls[1][calls[1].index("--trace-mode") + 1], "required")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertTrue(manifest["diagnostic"]["trace_requested"])
            self.assertEqual(sum(pair["status"] == "failed"
                                 for pair in manifest["pairs"]), 1)
            self.assertTrue(all(pair["status"] == "pending"
                                for pair in manifest["pairs"][1:]))

    def test_combined_summary_requires_complete_no_trace_matrix(self):
        document = comparison_document()
        summary = collector.summary_document(document, "c" * 64)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["counts"]["selections"], 17)
        self.assertEqual(summary["counts"]["measured_pairings"], 170)
        self.assertTrue(all(row["measured_pairings"] == 10
                            for row in summary["selections"]))
        bad = copy.deepcopy(document)
        bad["sources"][0]["trace_status"] = "PASS"
        with self.assertRaises(collector.SummaryError):
            collector.summary_document(bad, "c" * 64)


if __name__ == "__main__":
    unittest.main()
