import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import dirtygen_perf_mc_compare as compare
import dirtygen_perf_mc_report as mc
from test_dirtygen_perf_mc_report import EPOCH_START, EPOCH_END, trace_for, valid_report


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def make_report(harts, workload, baseline, attempts=None):
    report = valid_report(harts, workload.replace("-", "_").upper(), baseline,
                          attempts)
    baseline_number = int(baseline[1:])
    for sample in report.samples:
        cycle = 100 + baseline_number * 10 + int(sample["sample"])
        sample["max_local_cycles"] = cycle
        sample["completion_cycles"] = cycle
        rows = [row for row in report.harts if row["sample"] == sample["sample"]]
        for row in rows:
            row["workload_cycles"] = cycle
            row["cycle_end"] = row["cycle_start"] + cycle
        sample["absolute_start_min"] = min(row["cycle_start"] for row in rows)
        sample["absolute_end_max"] = max(row["cycle_end"] for row in rows)
    report.validate(harts, workload.replace("-", "_").upper(), baseline)
    return report


def metadata(harts, workload, baseline, block="I0", mode="architecture",
             experiment="experiment", seed=2, minute_base=0):
    position = compare.BLOCKS[block].index(baseline)
    selection = f"{harts}-{workload}-{baseline}"
    run_id = f"{experiment}-{mode}-{block}-h{harts}-{workload}-{baseline}"
    heads = {name: digest(name)[:40] for name in compare.REPOSITORIES}
    cpu = {"xlen": 64, "cpu_count": harts, "seed": seed,
           "lsu_l1_coherency": harts > 1, "memory_latency": 0}
    workload_id = {"private-strong": 0, "private-weak": 1,
                   "same-pte": 2, "prefilled-same-pte": 3}[workload]
    return {
        "schema": compare.METADATA_SCHEMA, "status": "passed", "exit_code": 0,
        "counter_contract": "abi-v2:5*N+5;CSR-I-fences",
        "failure_stage": None, "failure_message": None,
        "start_time": f"2026-09-08T00:{minute_base + position * 2:02}:00+08:00",
        "end_time": f"2026-09-08T00:{minute_base + position * 2 + 1:02}:00+08:00",
        "run_id": run_id, "process_run_id": run_id,
        "experiment_id": experiment, "isolation_block_id": block,
        "launch_order": list(compare.BLOCKS[block]), "launch_position": position,
        "fresh_reset": True, "hart_count": harts, "workload": workload,
        "baseline": baseline, "mode": mode, "simulation_seed": seed,
        "trace_required": True, "trace_requested": True,
        "trace_generated": True, "trace_path": "tracer.log",
        "repositories": {name: {"head": head} for name, head in heads.items()},
        "top_level_gitlinks": {}, "toolchain": {"gcc": "test"},
        "cpu_config": cpu,
        "commands": {
            "build": {"argv": ["make"]},
            "simulation": {"argv": ["mill", "--cpu-count", str(harts),
                                      "--seed", str(seed)]},
            "report": {"argv": ["report", "--hart-count", str(harts),
                                "--workload", workload, "--baseline", baseline]},
        },
        "artifact": {
            "elf_sha256": digest(selection), "text_sha256": "a" * 64,
            "text_init_sha256": "b" * 64, "workload_code_sha256": "c" * 64,
            "timed_window_sha256": "d" * 64,
            "selection": {"magic": "0x1", "abi_version": 2,
                          "hart_count": harts, "workload": workload_id,
                          "baseline": int(baseline[1:]), "runs": 6},
        },
        "build_exit_code": 0, "simulation_exit_code": 0, "report_exit_code": 0,
    }


def write_campaign(root, harts, workload, baseline, block="I0",
                   mode="architecture", experiment="experiment", attempts=None):
    report = make_report(harts, workload, baseline, attempts)
    trace = mc.check_trace(iter(trace_for(report)), report, 0x40, 0x80, EPOCH_START, EPOCH_END)
    document, _ = mc.documents(report)
    path = root / f"{mode}-{block}-h{harts}-{workload}-{baseline}"
    (path / "report").mkdir(parents=True)
    samples = path / "report" / "samples.json"
    meta = path / "metadata.json"
    samples.write_text(json.dumps(document))
    (path / "report" / "trace-report.json").write_text(json.dumps(trace))
    meta.write_text(json.dumps(metadata(harts, workload, baseline, block, mode,
                                        experiment)))
    return compare.load_campaign(samples, meta)


def ordinary_blocks(root):
    campaigns = []
    for block in compare.BLOCKS:
        for baseline in compare.BASELINES:
            campaigns.append(write_campaign(root, 2, "same-pte", baseline, block))
    return campaigns


def prefilled_modes(root, attempts_b2=2, attempts_b3=2):
    campaigns = []
    for mode in ("architecture", "rvls"):
        for baseline, attempts in (("B3", attempts_b3), ("B2", attempts_b2)):
            campaigns.append(write_campaign(root, 2, "prefilled-same-pte",
                                             baseline, mode=mode,
                                             experiment="prefilled",
                                             attempts=attempts))
    return campaigns


class DirtygenPerfMcCompareTest(unittest.TestCase):
    def test_ordinary_four_blocks_pair_and_use_paired_deltas(self):
        with tempfile.TemporaryDirectory() as directory:
            document = compare.comparison_document(ordinary_blocks(Path(directory)))
        self.assertEqual(document["schema"], compare.COMPARISON_SCHEMA)
        self.assertEqual(document["counts"]["sources"], 16)
        self.assertEqual(document["counts"]["main_pairings"], 20)
        self.assertEqual(document["counts"]["main_summaries"], 4)
        self.assertEqual(document["counts"]["distributions"], 1)
        self.assertEqual(document["summaries"][0]["deltas"]["log_cycles"]["median"], 10)

    def test_rejects_missing_duplicate_nonfresh_and_bad_instret(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = ordinary_blocks(Path(directory))
            for mutated in (campaigns[:-1], campaigns + [campaigns[0]]):
                with self.assertRaises(compare.ComparisonError):
                    compare.comparison_document(mutated)
            campaigns[0].metadata["fresh_reset"] = False
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document(campaigns)
        with tempfile.TemporaryDirectory() as directory:
            campaigns = ordinary_blocks(Path(directory))
            campaigns[1].document["samples"][1]["harts"][0]["workload_instret"] += 1
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document(campaigns)

    def test_rejects_wrong_order_overlap_head_cpu_hash_and_trace(self):
        mutators = (
            lambda c: c[0].metadata.update(schema="shdlt-dirtygen-perf-mc-campaign-v1"),
            lambda c: c[0].metadata.update(counter_contract="abi-v1"),
            lambda c: c[0].metadata["artifact"]["selection"].update(abi_version=1),
            lambda c: c[0].document.update(schema="shdlt-dirtygen-perf-mc-samples-v1"),
            lambda c: c[0].trace.update(schema="shdlt-dirtygen-perf-mc-trace-report-v1"),
            lambda c: c[0].metadata["artifact"].update(timed_window_sha256="e" * 64),
            lambda c: c[0].metadata.update(launch_position=1),
            lambda c: c[1].metadata.update(start_time=c[0].metadata["start_time"]),
            lambda c: c[0].metadata["repositories"]["Spike"].update(head="f" * 40),
            lambda c: c[0].metadata["cpu_config"].update(memory_latency=1),
            lambda c: c[0].metadata["artifact"].update(text_sha256="f" * 64),
            lambda c: c[0].trace.update(status="FAIL"),
        )
        for mutate in mutators:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                campaigns = ordinary_blocks(Path(directory))
                mutate(campaigns)
                with self.assertRaises(compare.ComparisonError):
                    compare.comparison_document(campaigns)

    def test_prefilled_reports_roles_and_conditionally_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            document = compare.comparison_document(prefilled_modes(Path(directory)))
        self.assertEqual(document["schema"], compare.PREFILLED_COMPARISON_SCHEMA)
        self.assertTrue(document["cross_mode_equal"])
        self.assertEqual(document["counts"], {"sources": 4, "observations": 10,
                                               "summaries": 2})
        self.assertTrue(all(row["signature_matched"] for row in document["observations"]))
        self.assertEqual(document["observations"][0]["B3"]["A"], 2)

    def test_prefilled_signature_mismatch_is_descriptive(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = prefilled_modes(Path(directory), attempts_b2=1, attempts_b3=2)
            document = compare.comparison_document(campaigns)
        self.assertTrue(all(not row["signature_matched"] for row in document["observations"]))
        self.assertTrue(all(row["completion_cycles_B3_minus_B2"] is None
                            for row in document["observations"]))

    def test_prefilled_rejects_cross_mode_architectural_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = prefilled_modes(Path(directory))
            rvls_b3 = next(item for item in campaigns
                           if item.mode == "rvls" and item.baseline == "B3")
            rvls_b3.document["samples"][1]["completion_cycles"] += 1
            with self.assertRaises(compare.ComparisonError):
                compare.comparison_document(campaigns)

    def test_output_is_atomic_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = compare.comparison_document(ordinary_blocks(root / "inputs"))
            output = root / "output"
            compare.write_outputs(document, output)
            self.assertEqual(json.loads((output / "comparison.json").read_text())["status"], "PASS")
            self.assertTrue((output / "comparison.csv").is_file())
            with self.assertRaises(compare.ComparisonError):
                compare.write_outputs(document, output)


if __name__ == "__main__":
    unittest.main()
