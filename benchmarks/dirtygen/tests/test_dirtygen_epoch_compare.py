import copy
import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dirtygen_epoch_compare as compare
from test_dirtygen_epoch_report import single_document
import dirtygen_epoch_report as report


def metadata(backend, start, end, code="code", block="E0"):
    return {"schema": compare.METADATA_SCHEMA, "status": "passed", "exit_code": 0,
            "process_run_id": backend + start, "run_id": backend + start,
            "mode": "architecture", "experiment_id": "unit",
            "epoch_block_id": block, "profile": "single", "hart_count": 1,
            "workload": "unique", "value": 1, "backend": backend,
            "simulation_seed": 2, "start_time": start, "end_time": end,
            "launch_position": compare.BLOCKS[block].index(backend),
            "repositories": {"NaxSoftware": {"head": "head"}},
            "top_level_gitlinks": {"NaxSoftware": {"gitlink_head": "old"}},
            "toolchain": {"mill": {"path": "/mill", "sha256": "m"}},
            "cpu_config": {"cpu_count": 1, "seed": 2},
            "source_fingerprint": {"digest": "source"},
            "artifact": {"elf_sha256": backend, "workload_code_sha256": code,
                         "timed_window_sha256": "timed"}}


def sample_doc(backend, delta=0):
    parsed = single_document(backend)
    doc = report.validate_console(parsed, "single", "unique", 1, 1, backend)
    if backend == "shdlt-log":
        for row in doc["samples"]:
            row["workload_cycles"] += delta
            row["workload_cycle_end"] += delta
            row["epoch_cycles"] += delta
    return doc


def write_run(root, backend, start, end, delta=0, code="code", block="E0"):
    root.mkdir(parents=True)
    (root / "report").mkdir()
    (root / "metadata.json").write_text(json.dumps(metadata(backend, start, end, code, block)))
    (root / "report/samples.json").write_text(json.dumps(sample_doc(backend, delta)))
    trace = {"schema": compare.TRACE_SCHEMA, "status": "PASS",
             "profile": "single", "backend": backend,
             "samples": [{"sample": sample} for sample in range(6)]}
    (root / "report/trace-report.json").write_text(json.dumps(trace))
    return root


class EpochCompareTest(unittest.TestCase):
    def test_pairing_signed_metrics_and_inclusive_iqr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scan = write_run(root / "scan", "pte-scan-serial",
                             "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00")
            log = write_run(root / "log", "shdlt-log",
                            "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00", 3)
            document = compare.comparison_document([compare.load_campaign(scan),
                                                    compare.load_campaign(log)])
            self.assertEqual(document["counts"]["measured_pairings"], 5)
            self.assertEqual(document["pairings"][0]["metrics"]["runtime_overhead"], 3)
            self.assertEqual(document["pairings"][0]["metrics"]["net_epoch_gain"], -3)
            self.assertEqual(document["summaries"][0]["metrics"]["runtime_overhead"]["iqr"], 0)

    def test_rejects_missing_duplicate_and_incompatible_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scan = compare.load_campaign(write_run(root / "scan", "pte-scan-serial",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00"))
            log = compare.load_campaign(write_run(root / "log", "shdlt-log",
                "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00"))
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document([scan])
            duplicate = copy.deepcopy(scan)
            duplicate.metadata["process_run_id"] = "other"
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document([scan, duplicate])
            log.metadata["artifact"]["timed_window_sha256"] = "changed"
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document([scan, log])

    def test_rejects_order_overlap_and_functional_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scan = compare.load_campaign(write_run(root / "scan", "pte-scan-serial",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:04:00+00:00"))
            log = compare.load_campaign(write_run(root / "log", "shdlt-log",
                "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00"))
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document([scan, log])

    def test_rejects_cpu_seed_instret_and_status_mismatch(self):
        mutations = (
            lambda campaign: campaign.metadata["cpu_config"].update(cpu_count=2),
            lambda campaign: campaign.metadata.update(simulation_seed=3),
            lambda campaign: campaign.samples["samples"][1].update(workload_instret=13),
            lambda campaign: campaign.samples["samples"][1].update(status=1),
        )
        for mutation in mutations:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                scan = compare.load_campaign(write_run(root / "scan", "pte-scan-serial",
                    "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00"))
                log = compare.load_campaign(write_run(root / "log", "shdlt-log",
                    "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00"))
                mutation(log)
                with self.assertRaises(compare.ComparisonError):
                    compare.comparison_document([scan, log])

    def test_comparison_outputs_are_atomic_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scan = compare.load_campaign(write_run(root / "scan", "pte-scan-serial",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00"))
            log = compare.load_campaign(write_run(root / "log", "shdlt-log",
                "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00"))
            document = compare.comparison_document([scan, log])
            output = root / "comparison"
            compare.write_outputs(document, output)
            self.assertTrue((output / "comparison.json").is_file())
            with self.assertRaises(compare.ComparisonError):
                compare.write_outputs(document, output)
            scan.metadata["end_time"] = "2026-01-01T00:01:00+00:00"
            log.samples["samples"][1]["canonical_bitmap0"] = 0
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document([scan, log])

    def test_e1_launch_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = compare.load_campaign(write_run(root / "log", "shdlt-log",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00", block="E1"))
            scan = compare.load_campaign(write_run(root / "scan", "pte-scan-serial",
                "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00", block="E1"))
            self.assertEqual(compare.comparison_document([log, scan])["status"], "PASS")

    def test_no_trace_is_accepted_only_for_explicit_architecture_pairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [write_run(root / backend, backend,
                f"2026-01-01T00:0{index * 2}:00+00:00",
                f"2026-01-01T00:0{index * 2 + 1}:00+00:00")
                for index, backend in enumerate(("pte-scan-serial", "shdlt-log"))]
            for path in paths:
                metadata = json.loads((path / "metadata.json").read_text())
                metadata.update(trace_mode="disabled", trace_required=False,
                                trace_requested=False, trace_generated=False,
                                trace_path=None)
                (path / "metadata.json").write_text(json.dumps(metadata))
                trace = json.loads((path / "report/trace-report.json").read_text())
                trace.update(status="NOT_COLLECTED", reason="trace-disabled",
                             samples=[], lifecycles=[], totals=None,
                             sample_segmentation=None)
                (path / "report/trace-report.json").write_text(json.dumps(trace))
            campaigns = [compare.load_campaign(path) for path in paths]
            document = compare.comparison_document(campaigns)
            self.assertEqual({row["trace_status"] for row in document["sources"]},
                             {"NOT_COLLECTED"})
            metadata = json.loads((paths[0] / "metadata.json").read_text())
            metadata["mode"] = "rvls"
            (paths[0] / "metadata.json").write_text(json.dumps(metadata))
            with self.assertRaises(compare.ComparisonError):
                compare.load_campaign(paths[0])

    def test_rejects_mixed_trace_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scan_path = write_run(root / "scan", "pte-scan-serial",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00")
            log_path = write_run(root / "log", "shdlt-log",
                "2026-01-01T00:02:00+00:00", "2026-01-01T00:03:00+00:00")
            metadata = json.loads((scan_path / "metadata.json").read_text())
            metadata.update(trace_mode="disabled", trace_required=False,
                            trace_requested=False, trace_generated=False,
                            trace_path=None)
            (scan_path / "metadata.json").write_text(json.dumps(metadata))
            trace = json.loads((scan_path / "report/trace-report.json").read_text())
            trace.update(status="NOT_COLLECTED", reason="trace-disabled",
                         samples=[], lifecycles=[], totals=None,
                         sample_segmentation=None)
            (scan_path / "report/trace-report.json").write_text(json.dumps(trace))
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document([compare.load_campaign(scan_path),
                                              compare.load_campaign(log_path)])


if __name__ == "__main__":
    unittest.main()
