import csv
import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import dirtygen_perf_compare
import dirtygen_perf_report


def sample(config, warmup, repetition):
    row = {
        "config": config,
        "warmup": warmup,
        "repetition": repetition,
    }
    row.update(dirtygen_perf_report.expected_config(config))
    group = config // 4
    baseline = config & 3
    row.update(
        {
            "workload_cycles": 1000 + group * 100 + baseline * 10 + repetition,
            "workload_instret": 50 + group * 10 + repetition,
            "prepare_cycles": 200 + repetition,
            "collect_cycles": 30 + repetition,
            "epoch_cycles": 400 + repetition,
        }
    )
    row.update({field: 0 for field in dirtygen_perf_report.ERROR_FIELDS})
    return row


def samples_document(schedule_id="legacy"):
    configs = dirtygen_perf_report.ordered_configs("smoke", schedule_id)
    rows = []
    for config in configs:
        rows.append(sample(config, 1, 0))
        for repetition in range(dirtygen_perf_report.MEASURED_REPETITIONS):
            rows.append(sample(config, 0, repetition))
    return {
        "schema": dirtygen_perf_compare.SAMPLES_SCHEMA,
        "suite": "smoke",
        "begin": {"abi": 1, "configs": len(configs), "samples": len(rows)},
        "samples": rows,
        "end": {
            "configs": len(configs),
            "samples": len(rows),
            "failures": 0,
            "status": 0,
        },
    }


def isolated_samples_document(config):
    rows = [sample(config, 1, 0)] + [
        sample(config, 0, repetition)
        for repetition in range(dirtygen_perf_report.MEASURED_REPETITIONS)
    ]
    return {
        "schema": dirtygen_perf_compare.SAMPLES_SCHEMA,
        "suite": "isolated",
        "begin": {"abi": 1, "configs": 1, "samples": len(rows)},
        "samples": rows,
        "end": {
            "configs": 1,
            "samples": len(rows),
            "failures": 0,
            "status": 0,
        },
    }


def metadata(run_id="run-0", schedule_id="legacy", seed=2, sha="1" * 64):
    repositories = {
        name: {"head": str(index) * 40}
        for index, name in enumerate(
            ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS"), start=1
        )
    }
    return {
        "schema": dirtygen_perf_compare.METADATA_SCHEMA,
        "run_id": run_id,
        "schedule_id": schedule_id,
        "suite": "smoke",
        "mode": "architecture",
        "status": "passed",
        "exit_code": 0,
        "failure_stage": None,
        "failure_message": None,
        "start_time": "2026-09-05T00:00:00+08:00",
        "end_time": "2026-09-05T00:01:00+08:00",
        "trace_required": False,
        "trace_requested": False,
        "trace_generated": False,
        "trace_path": None,
        "simulation_seed": seed,
        "repositories": repositories,
        "top_level_gitlinks": {
            name: {"gitlink_head": repositories[name]["head"]}
            for name in ("NaxSoftware", "Spike", "RVLS")
        },
        "toolchain": {"gcc": "test toolchain"},
        "cpu_config": {"xlen": 64, "seed": seed, "memory_latency": 0},
        "commands": {
            "simulation": {"argv": ["mill", "--seed", str(seed)]},
            "report": {
                "argv": ["report", "--schedule-id", schedule_id]
            },
        },
        "artifact": {"elf": "dirtygen_perf.elf", "sha256": sha},
        "build_exit_code": 0,
        "simulation_exit_code": 0,
        "report_exit_code": 0,
    }


def isolated_metadata(config, block_id="I0", seed=2, experiment="experiment-a"):
    baseline = f"B{config & 3}"
    order = list(dirtygen_perf_compare.ISOLATION_BLOCKS[block_id])
    position = order.index(baseline)
    run_id = f"run-{experiment}-{block_id.lower()}-c{config}-seed{seed}"
    result = metadata(run_id=run_id, seed=seed, sha=f"{config:x}"[-1] * 64)
    result.update(
        {
            "schedule_id": "isolated",
            "suite": "isolated",
            "experiment_id": experiment,
            "isolation_block_id": block_id,
            "config_id": config,
            "baseline": baseline,
            "fresh_reset": True,
            "launch_order": order,
            "launch_position": position,
            "process_run_id": run_id,
            "start_time": f"2026-09-05T00:{position * 2:02}:00+08:00",
            "end_time": f"2026-09-05T00:{position * 2 + 1:02}:00+08:00",
        }
    )
    result["commands"]["simulation"]["argv"] = [
        "mill", "Test[2.13.12].runMain", "--seed", str(seed)
    ]
    result["commands"]["report"]["argv"] = [
        "report", "--suite", "isolated", "--config-id", str(config)
    ]
    result["artifact"].update(
        {
            "elf_sha256": result["artifact"]["sha256"],
            "text_sha256": "a" * 64,
            "text_size": 100,
            "text_init_sha256": "b" * 64,
            "text_init_size": 200,
            "workload_code_sha256": "c" * 64,
            "workload_symbol_range": {
                "start_symbol": "dirtygen_perf_guest_entry",
                "end_symbol": "dirtygen_perf_trap_handler",
                "start_address": "0x0000000080000280",
                "end_address": "0x00000000800002f8",
                "size": 120,
                "section": ".text.init",
            },
        }
    )
    return result


def isolated_block(root, group=12, block_id="I0", seed=2):
    campaigns = []
    for baseline in range(4):
        config = group + baseline
        paths = write_campaign(
            root / f"c{config}",
            document=isolated_samples_document(config),
            campaign_metadata=isolated_metadata(config, block_id, seed),
        )
        campaigns.append(dirtygen_perf_compare.load_campaign(*paths))
    return campaigns


def write_campaign(root, document=None, campaign_metadata=None):
    root.mkdir(parents=True)
    samples_path = root / "samples.json"
    metadata_path = root / "metadata.json"
    campaign_metadata = campaign_metadata or metadata()
    document = document or samples_document(campaign_metadata["schedule_id"])
    samples_path.write_text(
        json.dumps(document), encoding="utf-8"
    )
    metadata_path.write_text(
        json.dumps(campaign_metadata), encoding="utf-8"
    )
    return samples_path, metadata_path


class DirtygenPerfCompareTest(unittest.TestCase):
    def test_valid_isolated_block_pairs_four_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = isolated_block(Path(directory) / "block")
            document = dirtygen_perf_compare.comparison_document(campaigns)
        self.assertEqual(
            document["schema"],
            dirtygen_perf_compare.ISOLATED_COMPARISON_SCHEMA,
        )
        self.assertEqual(len(document["sources"]), 4)
        self.assertEqual(len(document["pairings"]), 5)
        self.assertEqual(len(document["summaries"]), 1)
        self.assertEqual(len(document["block_distributions"]), 1)
        self.assertEqual(document["pairings"][0]["enable_cycles"], 10)
        self.assertEqual(document["pairings"][0]["svadu_cycles"], 20)
        self.assertEqual(document["pairings"][0]["log_cycles"], 10)
        self.assertEqual(document["pairings"][0]["total_cycles"], 30)
        self.assertEqual(document["pairings"][0]["active_total"], 20)

    def test_isolated_four_blocks_produce_cross_block_distribution_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaigns = []
            for block_id in dirtygen_perf_compare.ISOLATION_BLOCKS:
                campaigns.extend(isolated_block(root / block_id, block_id=block_id))
            document = dirtygen_perf_compare.comparison_document(campaigns)
            output = root / "output"
            dirtygen_perf_compare.write_outputs(document, output)
            written = json.loads((output / "comparison.json").read_text())
            with (output / "comparison.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(len(written["sources"]), 16)
        self.assertEqual(len(written["pairings"]), 20)
        self.assertEqual(len(written["summaries"]), 4)
        self.assertEqual(len(written["block_distributions"]), 1)
        self.assertEqual(
            [item["isolation_block_id"]
             for item in written["block_distributions"][0]["blocks"]],
            ["I0", "I1", "I2", "I3"],
        )
        self.assertEqual(len(rows), 4)
        self.assertIn("isolation_block_id", rows[0])

    def test_isolated_block_rejects_missing_and_duplicate_baselines(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = isolated_block(Path(directory) / "block")
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "baseline set"
        ):
            dirtygen_perf_compare.comparison_document(campaigns[:-1])
        duplicate = copy.deepcopy(campaigns[0])
        duplicate.metadata["run_id"] = "duplicate-b0"
        duplicate.metadata["process_run_id"] = "duplicate-b0"
        campaigns[-1] = duplicate
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "duplicate baseline"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

    def test_isolated_metadata_requires_fresh_distinct_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = isolated_block(Path(directory) / "block")
        campaigns[0].metadata["fresh_reset"] = False
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "fresh_reset"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)
        campaigns[0].metadata["fresh_reset"] = True
        campaigns[1].metadata["run_id"] = campaigns[0].run_id
        campaigns[1].metadata["process_run_id"] = campaigns[0].run_id
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "duplicate process_run_id"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

    def test_isolated_rejects_declared_order_and_config_elf_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaigns = isolated_block(root / "i0")
        campaigns[0].metadata["launch_position"] = 1
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "launch_position"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaigns = isolated_block(root / "i0", block_id="I0")
            campaigns.extend(isolated_block(root / "i1", block_id="I1"))
        repeated_config = next(
            campaign for campaign in campaigns
            if campaign.metadata["isolation_block_id"] == "I1"
            and campaign.metadata["config_id"] == 12
        )
        repeated_config.metadata["artifact"]["sha256"] = "e" * 64
        repeated_config.metadata["artifact"]["elf_sha256"] = "e" * 64
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "multiple ELF SHA256"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

    def test_isolated_rejects_launch_overlap_and_code_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = isolated_block(Path(directory) / "block")
        ordered = sorted(
            campaigns, key=lambda item: item.metadata["launch_position"]
        )
        ordered[1].metadata["start_time"] = ordered[0].metadata["start_time"]
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "overlap"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)
        ordered[1].metadata["start_time"] = "2026-09-05T00:02:00+08:00"
        ordered[1].metadata["artifact"]["text_sha256"] = "d" * 64
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "code hashes"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

    def test_isolated_rejects_cpu_head_repetition_and_instret_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            campaigns = isolated_block(Path(directory) / "block")
        campaigns[1].metadata["cpu_config"]["memory_latency"] = 1
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "incompatible experiment"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)
        campaigns[1].metadata["cpu_config"]["memory_latency"] = 0
        campaigns[1].metadata["repositories"]["RVLS"]["head"] = "9" * 40
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "incompatible experiment"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)
        campaigns[1].metadata["repositories"]["RVLS"]["head"] = "4" * 40
        campaigns[1].samples.pop()
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "baseline set"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)
        campaigns[1].samples.append(sample(13, 0, 4))
        campaigns[1].samples[-1]["workload_instret"] += 1
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "workload_instret"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

    def test_isolated_and_scheduled_campaigns_cannot_mix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaigns = isolated_block(root / "block")
            scheduled_paths = write_campaign(root / "scheduled")
            campaigns.append(dirtygen_perf_compare.load_campaign(*scheduled_paths))
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "cannot mix"
        ):
            dirtygen_perf_compare.comparison_document(campaigns)

    def test_valid_single_campaign_pairs_measured_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_campaign(Path(directory) / "run")
            campaign = dirtygen_perf_compare.load_campaign(*paths)
            document = dirtygen_perf_compare.comparison_document([campaign])
        self.assertEqual(document["status"], "PASS")
        self.assertEqual(len(document["pairings"]), 10)
        self.assertEqual(len(document["summaries"]), 2)
        self.assertTrue(document["warmup_samples_excluded"])
        self.assertTrue(document["cycle_deltas_are_descriptive_only"])
        self.assertTrue(
            all(row["pair_count"] == 5 for row in document["summaries"])
        )

    def test_multiple_schedules_may_use_different_elf_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths0 = write_campaign(
                root / "s0",
                campaign_metadata=metadata("run-s0", "S0", sha="1" * 64),
            )
            paths1 = write_campaign(
                root / "s1",
                campaign_metadata=metadata("run-s1", "S1", sha="2" * 64),
            )
            campaigns = [
                dirtygen_perf_compare.load_campaign(*paths0),
                dirtygen_perf_compare.load_campaign(*paths1),
            ]
            document = dirtygen_perf_compare.comparison_document(campaigns)
        self.assertEqual(len(document["pairings"]), 20)
        self.assertEqual(len(document["summaries"]), 4)
        self.assertTrue(
            all(
                len(group["runs"]) == 2
                for group in document["schedule_distributions"]
            )
        )
        self.assertTrue(
            all(
                group["median_distributions"]["log_cycles"]["count"] == 2
                for group in document["schedule_distributions"]
            )
        )

    def test_schedule_and_report_argv_must_match_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_report = metadata("run-wrong-report", "S0")
            wrong_report["commands"]["report"]["argv"][-1] = "S1"
            paths = write_campaign(
                root / "wrong-report", campaign_metadata=wrong_report
            )
            with self.assertRaisesRegex(
                dirtygen_perf_compare.ComparisonError, "report schedule"
            ):
                dirtygen_perf_compare.load_campaign(*paths)

            paths = write_campaign(
                root / "wrong-samples",
                document=samples_document("S1"),
                campaign_metadata=metadata("run-wrong-samples", "S0"),
            )
            with self.assertRaisesRegex(
                dirtygen_perf_report.ReportError, "sample order.*S0"
            ):
                dirtygen_perf_compare.load_campaign(*paths)

    def test_seed_must_match_cpu_and_mill_argv(self):
        for field in ("cpu", "mill"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                campaign_metadata = metadata("run-seed", "S0", seed=7)
                if field == "cpu":
                    campaign_metadata["cpu_config"]["seed"] = 8
                    message = "CPU seed"
                else:
                    campaign_metadata["commands"]["simulation"]["argv"][-1] = "8"
                    message = "Mill seed"
                paths = write_campaign(
                    Path(directory) / field,
                    campaign_metadata=campaign_metadata,
                )
                with self.assertRaisesRegex(
                    dirtygen_perf_compare.ComparisonError, message
                ):
                    dirtygen_perf_compare.load_campaign(*paths)
    def test_multiple_seeds_are_an_explicit_compatible_factor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths2 = write_campaign(
                root / "seed2",
                campaign_metadata=metadata("run-seed2", "S0", seed=2),
            )
            paths3 = write_campaign(
                root / "seed3",
                campaign_metadata=metadata("run-seed3", "S0", seed=3),
            )
            campaigns = [
                dirtygen_perf_compare.load_campaign(*paths2),
                dirtygen_perf_compare.load_campaign(*paths3),
            ]
            document = dirtygen_perf_compare.comparison_document(campaigns)
        self.assertEqual(len(document["pairings"]), 20)
        self.assertEqual(
            {
                group["simulation_seed"]
                for group in document["schedule_distributions"]
            },
            {2, 3},
        )

    def test_missing_and_duplicate_baselines_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_campaign(Path(directory) / "run")
            campaign = dirtygen_perf_compare.load_campaign(*paths)
        group = campaign.samples[0]["config"] // 4
        campaign.samples = [
            row for row in campaign.samples
            if not (
                row["warmup"] == 0
                and row["config"] // 4 == group
                and row["baseline"] == "B3"
            )
        ]
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "baseline set"
        ):
            dirtygen_perf_compare.build_pairings([campaign])

        duplicate = next(
            row for row in campaign.samples
            if row["warmup"] == 0 and row["baseline"] == "B0"
        )
        campaign.samples.append(dict(duplicate))
        with self.assertRaisesRegex(
            dirtygen_perf_compare.ComparisonError, "duplicate baseline"
        ):
            dirtygen_perf_compare.build_pairings([campaign])

    def test_failed_metadata_and_functional_sample_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = metadata()
            failed["status"] = "failed"
            paths = write_campaign(root / "failed", campaign_metadata=failed)
            with self.assertRaisesRegex(
                dirtygen_perf_compare.ComparisonError, "passed campaign"
            ):
                dirtygen_perf_compare.load_campaign(*paths)
            output = root / "failed-output"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    dirtygen_perf_compare.main(
                        [
                            "--input", str(paths[0]), str(paths[1]),
                            "--output-dir", str(output),
                        ]
                    ),
                    1,
                )
            self.assertFalse(output.exists())

            functional = samples_document()
            functional["samples"][0]["status"] = 1
            paths = write_campaign(root / "functional", document=functional)
            with self.assertRaisesRegex(
                dirtygen_perf_report.ReportError, "status"
            ):
                dirtygen_perf_compare.load_campaign(*paths)

    def test_instret_mismatch_is_rejected(self):
        document = samples_document()
        row = next(
            sample for sample in document["samples"]
            if sample["warmup"] == 0 and sample["baseline"] == "B3"
        )
        row["workload_instret"] += 1
        with tempfile.TemporaryDirectory() as directory:
            paths = write_campaign(Path(directory) / "run", document=document)
            campaign = dirtygen_perf_compare.load_campaign(*paths)
            with self.assertRaisesRegex(
                dirtygen_perf_compare.ComparisonError, "workload_instret differs"
            ):
                dirtygen_perf_compare.comparison_document([campaign])

    def test_experiment_metadata_and_schedule_hash_mismatches_are_rejected(self):
        def change_mode(value):
            value["mode"] = "rvls"
            value["trace_required"] = True
            value["trace_requested"] = True
            value["trace_generated"] = True
            value["trace_path"] = "tracer.log"
            value["commands"]["simulation"]["argv"].append("--with-rvls-log")

        mutations = {
            "seed": lambda value: value["cpu_config"].update(seed=3),
            "cpu": lambda value: value["cpu_config"].update(xlen=32),
            "head": lambda value: value["repositories"]["RVLS"].update(
                head="f" * 40
            ),
            "hash": lambda value: value["artifact"].update(sha256="2" * 64),
            "toolchain": lambda value: value.update(toolchain={"gcc": "different"}),
            "mode": change_mode,
        }
        for name, mutate in mutations.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                paths0 = write_campaign(
                    root / "a", campaign_metadata=metadata("run-a", "S0")
                )
                changed = metadata("run-b", "S0")
                mutate(changed)
                paths1 = write_campaign(root / "b", campaign_metadata=changed)
                if name == "seed":
                    with self.assertRaisesRegex(
                        dirtygen_perf_compare.ComparisonError, "CPU seed"
                    ):
                        dirtygen_perf_compare.load_campaign(*paths1)
                    continue
                campaigns = [
                    dirtygen_perf_compare.load_campaign(*paths0),
                    dirtygen_perf_compare.load_campaign(*paths1),
                ]
                with self.assertRaises(dirtygen_perf_compare.ComparisonError):
                    dirtygen_perf_compare.comparison_document(campaigns)

    def test_duplicate_run_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaigns = []
            for schedule in ("S0", "S1"):
                paths = write_campaign(
                    root / schedule,
                    campaign_metadata=metadata("duplicate", schedule),
                )
                campaigns.append(dirtygen_perf_compare.load_campaign(*paths))
            with self.assertRaisesRegex(
                dirtygen_perf_compare.ComparisonError, "duplicate run_id"
            ):
                dirtygen_perf_compare.comparison_document(campaigns)

    def test_paired_median_is_not_a_difference_of_baseline_medians(self):
        document = samples_document()
        b0 = [0, 0, 0, 100, 100]
        b3 = [0, 100, 100, 100, 100]
        for row in document["samples"]:
            if row["warmup"] != 0 or row["pattern"] != "UNIQUE":
                continue
            if row["baseline"] == "B0":
                row["workload_cycles"] = b0[row["repetition"]]
            elif row["baseline"] == "B3":
                row["workload_cycles"] = b3[row["repetition"]]
        with tempfile.TemporaryDirectory() as directory:
            paths = write_campaign(Path(directory) / "run", document=document)
            campaign = dirtygen_perf_compare.load_campaign(*paths)
            result = dirtygen_perf_compare.comparison_document([campaign])
        summary = next(
            row for row in result["summaries"] if row["pattern"] == "UNIQUE"
        )
        self.assertEqual(summary["metrics"]["total_cycles"]["median"], 0)
        self.assertEqual(sorted(b3)[2] - sorted(b0)[2], 100)

    def test_negative_deltas_and_zero_denominators_are_descriptive(self):
        document = samples_document()
        for row in document["samples"]:
            if row["warmup"] == 0 and row["baseline"] == "B1":
                row["workload_cycles"] = 0
        with tempfile.TemporaryDirectory() as directory:
            paths = write_campaign(Path(directory) / "run", document=document)
            campaign = dirtygen_perf_compare.load_campaign(*paths)
            result = dirtygen_perf_compare.comparison_document([campaign])
        self.assertTrue(any(row["enable_cycles"] < 0 for row in result["pairings"]))
        self.assertIsNone(dirtygen_perf_compare.safe_divide(7, 0))
        empty = dirtygen_perf_compare.summarize([None, None])
        self.assertEqual(
            empty,
            {
                "count": 0,
                "min": None,
                "median": None,
                "max": None,
                "mad": None,
            },
        )

    def test_json_csv_outputs_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = write_campaign(root / "run")
            output = root / "output"
            arguments = [
                "--input", str(paths[0]), str(paths[1]),
                "--output-dir", str(output),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dirtygen_perf_compare.main(arguments), 0)
            result = json.loads((output / "comparison.json").read_text())
            with (output / "comparison.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(rows), 2)
            stderr = io.StringIO()
            old_stderr = sys.stderr
            try:
                sys.stderr = stderr
                self.assertEqual(dirtygen_perf_compare.main(arguments), 1)
            finally:
                sys.stderr = old_stderr
            self.assertIn("already exists", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
