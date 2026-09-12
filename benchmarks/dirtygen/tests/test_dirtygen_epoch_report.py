import copy
import io
import tempfile
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import dirtygen_epoch_report as report


def single_sample(sample=0, backend="pte-scan-serial", pages=1):
    values = {name: 0 for name in report.SINGLE_SAMPLE_FIELDS
              if name not in report.STRING_FIELDS}
    values.update({"sample": sample, "warmup": int(sample == 0),
                   "repetition": 0 if sample == 0 else sample - 1,
                   "pattern": "UNIQUE", "harvest_backend": report.BACKENDS[backend][0],
                   "runtime_mode": report.BACKENDS[backend][1], "hart_count": 1,
                   "tracked_pages": 128, "dirty_pages": pages, "operations": pages,
                   "workload_cycle_start": 100, "workload_cycle_end": 110,
                   "workload_cycles": 10, "workload_instret": 12,
                   "quiesce_cycles": 2, "discover_cycles": 3,
                   "normalize_cycles": 4, "clear_d_cycles": 5,
                   "hfence_cycles": 6, "backend_reset_cycles": 7,
                   "resume_cycles": 8, "harvest_cycles": 25,
                   "pause_cycles": 35, "epoch_cycles": 45,
                   "canonical_dirty_pages": pages,
                   "expected_bitmap0": (1 << min(pages, 64)) - 1,
                   "expected_bitmap1": (1 << max(0, pages - 64)) - 1,
                   "canonical_bitmap0": (1 << min(pages, 64)) - 1,
                   "canonical_bitmap1": (1 << max(0, pages - 64)) - 1,
                   "hfence_acks": 1, "reset_acks": 1, "rearm_pages": pages,
                   "actual_cause": 10})
    if backend == "pte-scan-serial":
        values["pte_entries_scanned"] = 128
    else:
        values.update({"raw_log_entries": pages, "committed_log_entries": pages,
                       "idx_after": pages})
    return values


def single_document(backend="pte-scan-serial", pages=1):
    samples = [single_sample(index, backend, pages) for index in range(6)]
    begin = {"abi": 1, "harvest_backend": report.BACKENDS[backend][0],
             "runtime_mode": report.BACKENDS[backend][1], "pattern": "UNIQUE",
             "hart_count": 1, "tracked_pages": 128, "dirty_pages": pages,
             "operations": pages, "samples": 6}
    return {"begin": begin, "samples": samples, "harts": [],
            "end": {"samples": 6, "failures": 0, "status": 0},
            "order": [("sample", index, None) for index in range(6)]}


def mc_document(backend="shdlt-log", harts=2):
    samples, hart_rows, order = [], [], []
    for sample_id in range(6):
        row = {name: 0 for name in report.MC_SAMPLE_FIELDS
               if name not in report.STRING_FIELDS}
        row.update({"sample": sample_id, "warmup": int(sample_id == 0),
                    "repetition": 0 if sample_id == 0 else sample_id - 1,
                    "hart_count": harts, "workload": "SAME_PTE",
                    "harvest_backend": report.BACKENDS[backend][0],
                    "runtime_mode": report.BACKENDS[backend][1],
                    "tracked_pages": 128, "total_operations": harts,
                    "distinct_dirty_pages": 1, "workload_cycles": 15,
                    "hart0_cycle_start": 100, "quiesce_boundary": 117,
                    "quiesce_cycles": 2, "discover_cycles": 3,
                    "normalize_cycles": 4, "clear_d_cycles": 5,
                    "hfence_cycles": 6, "backend_reset_cycles": 7,
                    "resume_cycles": 8, "harvest_cycles": 25,
                    "pause_cycles": 35, "epoch_cycles": 50,
                    "canonical_dirty_pages": 1, "expected_bitmap0": 1,
                    "canonical_bitmap0": 1, "hfence_acks": harts,
                    "reset_acks": harts, "rearm_pages": 1,
                    "d_transitions": 1, "pte_cas_attempts": 1})
        if backend == "pte-scan-serial":
            row["pte_entries_scanned"] = 128
        else:
            row.update({"raw_log_entries": 1, "committed_log_entries": 1,
                        "idx_after_total": 1, "committed_appends": 1})
        samples.append(row); order.append(("sample", sample_id, None))
        for hart in range(harts):
            item = {name: 0 for name in report.MC_HART_FIELDS}
            item.update({"sample": sample_id, "hart": hart,
                         "warmup": int(sample_id == 0),
                         "repetition": 0 if sample_id == 0 else sample_id - 1,
                         "operations": 1, "cycle_start": 100 + hart,
                         "cycle_end": 115 + hart, "workload_cycles": 15,
                         "instret_start": 1000, "instret_end": 1010,
                         "workload_instret": 10, "scause": 10,
                         "hfence_done": sample_id + 1,
                         "reset_done": sample_id + 1, "done": 1})
            if hart == 0:
                item.update({"d_transitions": 1, "pte_cas_attempts": 1})
                if backend == "shdlt-log":
                    item.update({"idx_after": 1, "committed_appends": 1})
            hart_rows.append(item); order.append(("hart", sample_id, hart))
    return {"begin": {"abi": 1, "hart_count": harts,
            "workload": "SAME_PTE", "harvest_backend": report.BACKENDS[backend][0],
            "runtime_mode": report.BACKENDS[backend][1], "tracked_pages": 128,
            "samples": 6}, "samples": samples, "harts": hart_rows,
            "end": {"samples": 6, "failures": 0, "status": 0}, "order": order}


def trace_lines(samples, backend, layout, mismatch_hart=None):
    lines = []
    harts = layout["harts"]
    for sample in range(6):
        for hart in range(harts):
            lines.append(f"rv commit {hart} {layout['epoch_start']:016x} 00000013")
            lines.append(f"rv commit {hart} {layout['timed_start']:016x} 00000013")
        page = 0
        clean = (((layout["tracked_physical"] + page * 4096) >> 12) << 10) | 0x57
        dirty = clean | 0x80
        if backend == "shdlt-log":
            lines.append(f"rv mmu physical-store 0 1 {sample + 1} 20 {layout['log_bases'][0]:016x} 8 {report.TRACKED_GPA:016x} 0 pending")
        lines.append(f"rv mmu pte-cas 0 1 {sample + 1} 21 {layout['pte_base']:016x} 8 {clean:016x} {dirty:016x} {clean:016x} 0 1")
        if backend == "shdlt-log":
            lines.append(f"rv mmu physical-store 0 1 {sample + 1} 20 {layout['log_bases'][0]:016x} 8 {report.TRACKED_GPA:016x} 0 committed")
            lines.append(f"rv mmu store 0 {layout['log_bases'][0]:016x} 8 {report.TRACKED_GPA:016x} 0")
        lines.append(f"rv mmu store 0 {layout['pte_base']:016x} 8 {dirty:016x} 0")
        if mismatch_hart is not None:
            hart = mismatch_hart
            if backend == "shdlt-log":
                lines.append(f"rv mmu physical-store {hart} 1 {sample + 101} 22 {layout['log_bases'][hart]:016x} 8 {report.TRACKED_GPA:016x} 0 pending")
            lines.append(f"rv mmu pte-cas {hart} 1 {sample + 101} 23 {layout['pte_base']:016x} 8 {clean:016x} {dirty:016x} {dirty:016x} 0 0")
            if backend == "shdlt-log":
                lines.append(f"rv mmu physical-store {hart} 1 {sample + 101} 22 {layout['log_bases'][hart]:016x} 8 {report.TRACKED_GPA:016x} 0 superseded")
        for hart in range(harts):
            lines.append(f"rv commit {hart} {layout['timed_end']:016x} 00000013")
            lines.append(f"rv commit {hart} {layout['epoch_end']:016x} 00000013")
    return lines


class EpochReportTest(unittest.TestCase):
    def test_single_backends_validate(self):
        for backend in report.BACKENDS:
            with self.subTest(backend=backend):
                result = report.validate_console(single_document(backend), "single",
                                                 "unique", 1, 1, backend)
                self.assertEqual(len(result["samples"]), 6)

    def test_mc_backends_validate(self):
        for backend in report.BACKENDS:
            result = report.validate_console(mc_document(backend), "mc",
                                             "same-pte", None, 2, backend)
            self.assertEqual(len(result["samples"][0]["harts"]), 2)

    def test_rejects_bad_timing_bitmap_scan_and_ack(self):
        mutations = (
            lambda row: row.update(harvest_cycles=24),
            lambda row: row.update(canonical_bitmap0=0),
            lambda row: row.update(pte_entries_scanned=127),
            lambda row: row.update(hfence_acks=0),
            lambda row: row.update(status=1),
        )
        for mutation in mutations:
            document = single_document()
            mutation(document["samples"][1])
            with self.assertRaises(report.ReportError):
                report.validate_console(document, "single", "unique", 1, 1,
                                        "pte-scan-serial")

    def test_parser_rejects_duplicate_and_unknown_fields(self):
        text = (report.SINGLE_PREFIX +
                "_BEGIN abi=1 abi=1\n")
        with self.assertRaises(report.ReportError):
            report.parse_console(io.StringIO(text), "single")

    def test_trace_accepts_scan_and_log(self):
        layout = {"harts": 1, "epoch_start": 0x100, "epoch_end": 0x104,
                  "timed_start": 0x40, "timed_end": 0x80,
                  "pte_base": 0x81000000, "tracked_physical": 0x81200000,
                  "log_bases": [0x82010000]}
        for backend in report.BACKENDS:
            normalized = report.validate_console(single_document(backend), "single",
                                                 "unique", 1, 1, backend)
            checked = report.check_trace(iter(trace_lines(normalized, backend, layout)),
                                         normalized, backend, layout)
            self.assertEqual(checked["totals"]["pte_cas_success"], 6)

    def test_trace_accepts_shared_superseded_lifecycle(self):
        layout = {"harts": 2, "epoch_start": 0x100, "epoch_end": 0x104,
                  "timed_start": 0x40, "timed_end": 0x80,
                  "pte_base": 0x81005080, "tracked_physical": 0x81200000,
                  "log_bases": [0x82010000, 0x82810000]}
        doc = mc_document("shdlt-log")
        for sample in doc["samples"]:
            sample["pte_cas_attempts"] = 2; sample["cas_retries"] = 1
        for item in doc["harts"]:
            if item["hart"] == 1:
                item["pte_cas_attempts"] = item["cas_retries"] = 1
        normalized = report.validate_console(doc, "mc", "same-pte", None, 2,
                                             "shdlt-log")
        checked = report.check_trace(iter(trace_lines(normalized, "shdlt-log", layout, 1)),
                                     normalized, "shdlt-log", layout)
        self.assertEqual(checked["totals"]["superseded"], 6)

    def test_trace_negative_lifecycle_store_and_residual(self):
        layout = {"harts": 1, "epoch_start": 0x100, "epoch_end": 0x104,
                  "timed_start": 0x40, "timed_end": 0x80,
                  "pte_base": 0x81000000, "tracked_physical": 0x81200000,
                  "log_bases": [0x82010000]}
        normalized = report.validate_console(single_document("shdlt-log"), "single",
                                             "unique", 1, 1, "shdlt-log")
        base = trace_lines(normalized, "shdlt-log", layout)
        variants = [
            [line for line in base if not line.endswith("committed")],
            base + [next(line for line in base if line.endswith("committed"))],
            [line for line in base if not (line.startswith("rv mmu store 0 0000000081000000"))],
            base + ["residual mmuStoreQueue: 1"],
            base[:-1],
        ]
        for lines in variants:
            with self.assertRaises(report.ReportError):
                report.check_trace(iter(lines), normalized, "shdlt-log", layout)

    def test_trace_rejects_full_width_cas_and_identity_mismatch(self):
        layout = {"harts": 1, "epoch_start": 0x100, "epoch_end": 0x104,
                  "timed_start": 0x40, "timed_end": 0x80,
                  "pte_base": 0x81000000, "tracked_physical": 0x81200000,
                  "log_bases": [0x82010000]}
        normalized = report.validate_console(single_document("shdlt-log"), "single",
                                             "unique", 1, 1, "shdlt-log")
        base = trace_lines(normalized, "shdlt-log", layout)
        cas = next(index for index, line in enumerate(base)
                   if line.startswith("rv mmu pte-cas"))
        wrong = list(base); wrong[cas] = wrong[cas].replace("20480057", "20480457")
        missing = [line for index, line in enumerate(base) if index != cas]
        for lines in (wrong, missing):
            with self.assertRaises(report.ReportError):
                report.check_trace(iter(lines), normalized, "shdlt-log", layout)

    def test_atomic_outputs_refuse_overwrite(self):
        samples = report.validate_console(single_document(), "single", "unique",
                                          1, 1, "pte-scan-serial")
        trace = {"schema": "shdlt-dirtygen-epoch-trace-v1", "status": "PASS"}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            report.write_outputs(samples, trace, output)
            self.assertTrue((output / "samples.json").is_file())
            with self.assertRaises(report.ReportError):
                report.write_outputs(samples, trace, output)


if __name__ == "__main__":
    unittest.main()
