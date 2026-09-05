import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import shdlt_validation_audit as audit


def matrix_document():
    record = {
        "run_id": "run0",
        "status": "PASS",
        "trace_available": True,
        "invariants": {
            "status": "PASS",
            "trace": {"attribution_errors": 0},
            "violations": [],
        },
    }
    return {
        "status": "PASS",
        "totals": {
            "runs": 1,
            "trace_available_runs": 1,
            "trace_unavailable_runs": 0,
            "invariant_failures": 0,
            "attribution_errors": 0,
        },
        "expected": ["run0"],
        "records": [record],
    }


def attribution(mode="ctc"):
    if mode == "ctc":
        return {
            "mode": "ctc",
            "architectural_logger_stores": 1,
            "architectural_mmu_stores": 2,
            "attempts": 2,
            "duplicate_attempt_states": 0,
            "open_pending": 0,
            "states": {"committed": 1, "error": 0, "pending": 2, "superseded": 1},
            "status": "PASS",
        }
    return {
        "mode": "fault",
        "architectural_logger_stores": 1,
        "architectural_mmu_stores": 1,
        "attempts": 1,
        "duplicate_attempt_states": 0,
        "open_pending": 0,
        "states": {"committed": 0, "error": 1, "pending": 0, "superseded": 0},
        "status": "PASS",
    }


class ValidationAuditTest(unittest.TestCase):
    def test_matrix_accepts_complete_pass(self):
        self.assertEqual(audit.validate_matrix_document(matrix_document(), 1), ["run0"])

    def test_matrix_rejects_missing_run(self):
        document = matrix_document()
        document["records"] = []
        with self.assertRaisesRegex(audit.AuditError, "run count"):
            audit.validate_matrix_document(document, 1)

    def test_matrix_rejects_failed_invariant(self):
        document = matrix_document()
        document["records"][0]["invariants"]["status"] = "FAIL"
        with self.assertRaisesRegex(audit.AuditError, "invariant"):
            audit.validate_matrix_document(document, 1)

    def test_attribution_accepts_winner_and_loser(self):
        value = attribution()
        audit.validate_attribution(value, dict(value))

    def test_attribution_rejects_wrong_lifecycle(self):
        value = attribution()
        expected = json.loads(json.dumps(value))
        value["open_pending"] = 1
        with self.assertRaisesRegex(audit.AuditError, "expectation"):
            audit.validate_attribution(value, expected)

    def test_fault_attribution_cannot_hide_error_as_superseded(self):
        value = attribution("fault")
        expected = json.loads(json.dumps(value))
        value["states"]["error"] = 0
        value["states"]["superseded"] = 1
        expected = value
        with self.assertRaisesRegex(audit.AuditError, "log-fault"):
            audit.validate_attribution(value, expected)

    def test_trace_rejects_open_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.log"
            path.write_text(
                "rv mmu physical-store 0 1 7 99 0000000080004000 8 1 0 pending\n",
                encoding="utf-8",
            )
            result = audit.parse_trace_lifecycle(path)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(len(result["bad_lifecycles"]), 1)

    def test_trace_accepts_all_three_terminal_forms(self):
        lines = [
            "rv mmu physical-store 0 1 1 1 0000000080004000 8 1 0 pending",
            "rv mmu physical-store 0 1 1 1 0000000080004000 8 1 0 committed",
            "rv mmu physical-store 0 1 2 2 0000000080004008 8 2 0 pending",
            "rv mmu physical-store 0 1 2 2 0000000080004008 8 2 0 superseded",
            "rv mmu physical-store 0 1 3 3 0000000080004010 8 3 1 error",
            "rv mmu store 0 0000000080004000 8 1 0",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = audit.parse_trace_lifecycle(path)
        self.assertEqual(result["committed"], 1)
        self.assertEqual(result["superseded"], 1)
        self.assertEqual(result["error"], 1)
        self.assertEqual(result["architectural_mmu_stores"], 1)
        self.assertEqual(result["bad_lifecycles"], [])

    def test_stability_classifies_exact_directional_and_unstable(self):
        self.assertEqual(audit.classify_stability([7, 7, 7, 7]), "exact")
        self.assertEqual(
            audit.classify_stability([7, 8, 9, 7]), "directional/value-sensitive"
        )
        self.assertEqual(audit.classify_stability([-1, 0, 0, 0]), "unstable")
        self.assertEqual(audit.classify_stability([-1, 1, 1, 1]), "unstable")

    def test_paths_reject_absolute_and_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(audit.AuditError, "escapes"):
                audit.resolve_relative(root, "/tmp/file")
            with self.assertRaisesRegex(audit.AuditError, "escapes"):
                audit.resolve_relative(root, "../file")

    def test_duplicate_inputs_rejected(self):
        with self.assertRaisesRegex(audit.AuditError, "duplicate"):
            audit.require_unique(["a", "a"], "input")

    def test_git_status_keeps_tracked_and_untracked_separate(self):
        with mock.patch.object(
            audit,
            "run_git",
            return_value=" M benchmarks/dirtygen/README.md\n?? unrelated.py",
        ):
            tracked, untracked = audit.git_status_paths(Path("."))
        self.assertEqual(tracked, ["benchmarks/dirtygen/README.md"])
        self.assertEqual(untracked, ["unrelated.py"])

    def test_wrong_tested_head_rejected(self):
        campaign = SimpleNamespace(
            metadata={
                "repositories": {
                    name: {"head": "bad" if name == "RVLS" else name, "tracked_dirty": False}
                    for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")
                }
            }
        )
        expected = {name: name for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")}
        with self.assertRaisesRegex(audit.AuditError, "RVLS HEAD"):
            audit.assert_campaign_head(campaign, expected, "run")

    def test_reference_sample_difference_rejected(self):
        clean = [SimpleNamespace(schedule_id="S0", seed=2, document={"samples": [1]})]
        reference = [SimpleNamespace(schedule_id="S0", seed=2, document={"samples": [2]})]
        with self.assertRaisesRegex(audit.AuditError, "Phase-4"):
            audit.validate_reference_samples(clean, reference)

    def test_comparison_drift_rejected(self):
        stored = {
            "schema": "bad", "status": "PASS", "suite": "sensitivity",
            "mode": "architecture", "pair_key_fields": [],
            "warmup_samples_excluded": True,
            "cycle_deltas_are_descriptive_only": True,
            "pairings": [], "summaries": [], "schedule_distributions": [],
        }
        recomputed = dict(stored)
        recomputed["schema"] = "good"
        with mock.patch.object(
            audit.dirtygen_perf_compare, "comparison_document", return_value=recomputed
        ):
            with self.assertRaisesRegex(audit.AuditError, "differs"):
                audit.validate_comparison([], stored)

    def test_hash_mismatch_is_a_failed_check(self):
        checks = audit.Checks()
        with self.assertRaisesRegex(audit.AuditError, "SHA256"):
            checks.equal("artifact", "ELF SHA256", "bad", "good", "elf")
        self.assertEqual(checks.items[0].status, "FAIL")

    def test_atomic_outputs_are_complete_and_refuse_overwrite(self):
        document = {
            "tested_heads": {name: name for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")},
            "top_level_gitlinks": {
                name: {"head": name} for name in ("NaxSoftware", "Spike", "RVLS")
            },
            "commit_chain": {
                name: [name] for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")
            },
            "evidence_digest": "0" * 64,
            "evidence_files": [],
            "checks": [],
            "stability": {
                workload: {
                    "2": {
                        metric: {"medians": [0, 0, 0, 0], "classification": "exact"}
                        for metric in ("enable_cycles", "svadu_cycles", "log_cycles")
                    }
                }
                for workload in ("REPEAT/1/4096", "UNIQUE/128/128")
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "audit"
            audit.atomic_write_outputs(output, document)
            self.assertEqual(
                {path.name for path in output.iterdir()}, {"audit.json", "audit.csv", "audit.md"}
            )
            json.loads((output / "audit.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(audit.AuditError, "already exists"):
                audit.atomic_write_outputs(output, document)

    def test_atomic_failure_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "audit"
            document = {"checks": []}
            with mock.patch.object(audit, "audit_markdown", side_effect=RuntimeError("boom")):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    audit.atomic_write_outputs(output, document)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_atomic_parent_sync_failure_removes_installed_output(self):
        document = {
            "tested_heads": {name: name for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")},
            "top_level_gitlinks": {
                name: {"head": name} for name in ("NaxSoftware", "Spike", "RVLS")
            },
            "commit_chain": {
                name: [name] for name in ("VexiiRiscv", "NaxSoftware", "Spike", "RVLS")
            },
            "evidence_digest": "0" * 64,
            "evidence_files": [],
            "checks": [],
            "stability": {
                workload: {
                    "2": {
                        metric: {"medians": [0, 0, 0, 0], "classification": "exact"}
                        for metric in ("enable_cycles", "svadu_cycles", "log_cycles")
                    }
                }
                for workload in ("REPEAT/1/4096", "UNIQUE/128/128")
            },
        }
        real_fsync = audit.os.fsync
        calls = 0

        def fail_parent_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("sync failed")
            return real_fsync(fd)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "audit"
            with mock.patch.object(audit.os, "fsync", side_effect=fail_parent_sync):
                with self.assertRaisesRegex(OSError, "sync failed"):
                    audit.atomic_write_outputs(output, document)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
