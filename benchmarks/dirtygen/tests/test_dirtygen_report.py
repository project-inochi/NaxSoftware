import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import dirtygen_report


CTL_BASE = 0x8000C000
FAULT_SEPC = 0x768


def record(kind, fields):
    rendered = []
    for key, value in fields.items():
        rendered.append(
            f"{key}=0x{value:x}" if isinstance(value, int) else f"{key}={value}"
        )
    return f"DIRTYGEN_{kind} " + " ".join(rendered)


def make_fault(case_id, repetition, ordinal, action):
    spec = dirtygen_report.CASE_SPECS[case_id]
    buffer = ordinal if spec.kind == "chain" else 0
    stval = dirtygen_report.TRACKED_GPA_BASE
    if spec.kind == "chain":
        stval += (ordinal + 1) * dirtygen_report.PAGE_SIZE
    return {
        "case": spec.name,
        "id": case_id,
        "rep": repetition,
        "ordinal": ordinal,
        "buffer": buffer,
        "index": (spec.initial_idx if spec.kind == "boundary" else spec.capacity),
        "action": action,
        "replacement_buffer": (
            dirtygen_report.NO_BUFFER
            if action == dirtygen_report.FAULT_STOP
            else buffer + 1
        ),
        "replacement_idx": spec.replacement_idx,
        "fault_cycles": 200 + repetition + ordinal,
        "service_cycles": 0 if action == dirtygen_report.FAULT_STOP else 30 + ordinal,
        "retry_cycles": 0 if action == dirtygen_report.FAULT_STOP else 40 + ordinal,
        "scause": dirtygen_report.FAULT_CAUSE,
        "sepc": FAULT_SEPC,
        "stval": stval,
        "htval": stval >> 2,
    }


def make_epoch(case_id, repetition, ordinal):
    spec = dirtygen_report.CASE_SPECS[case_id]
    start = (ordinal * spec.epoch_stride) & 127
    bitmap = [0, 0]
    for index in range(spec.epoch_touched):
        page = (start + index) & 127
        bitmap[page >> 6] |= 1 << (page & 63)
    guest = 100 + ordinal
    guest_instret = 50 + ordinal
    phases = {
        "freeze_cycles": 10 + ordinal,
        "drain_cycles": 20 + spec.epoch_touched + ordinal,
        "reset_cycles": 5 + ordinal,
        "fence_cycles": 6 + ordinal,
        "resume_cycles": 7 + ordinal,
    }
    ctl = (CTL_BASE >> 12) << 10
    return {
        "case": spec.name,
        "id": case_id,
        "rep": repetition,
        "epoch": ordinal,
        "expected": spec.epoch_touched,
        "idx_before": spec.epoch_touched,
        "idx_after": 0,
        "entries": spec.epoch_touched,
        "unique": spec.epoch_touched,
        "duplicates": 0,
        "missing": 0,
        "extra": 0,
        "bitmap0": bitmap[0],
        "bitmap1": bitmap[1],
        "pte_missing": 0,
        "pte_extra": 0,
        "pte_after_clear": 0,
        "data_errors": 0,
        "control_errors": 0,
        "traps": 0,
        "guest_cycles": guest,
        "guest_instret": guest_instret,
        **phases,
        "end_to_end_cycles": guest + sum(phases.values()) + 11,
        "frozen_ctl": ctl,
        "resumed_ctl": ctl | 1,
        "status": 0,
    }


def make_sample(case_id, repetition, version=4):
    spec = dirtygen_report.CASE_SPECS[case_id]
    events = [
        make_fault(case_id, repetition, ordinal, action)
        for ordinal, action in enumerate(spec.fault_actions)
    ]
    fault = sum(event["fault_cycles"] for event in events)
    service = sum(event["service_cycles"] for event in events)
    retry = sum(event["retry_cycles"] for event in events)
    epoch_events = [
        make_epoch(case_id, repetition, ordinal)
        for ordinal in range(spec.epochs)
    ]
    if spec.kind == "epoch":
        total = sum(event["end_to_end_cycles"] for event in epoch_events)
        guest = sum(event["guest_cycles"] for event in epoch_events)
        instret = sum(event["guest_instret"] for event in epoch_events)
    elif not events:
        total = 1000 + case_id * 10 + repetition
        guest = total
        instret = 500 + case_id
    elif spec.fault_actions == (dirtygen_report.FAULT_STOP,):
        total = fault
        guest = 0
        instret = 500 + case_id
    else:
        guest = retry + 100
        total = fault + service + guest
        instret = 500 + case_id
    sample = {
        "case": spec.name,
        "id": case_id,
        "rep": repetition,
        "tracked": 128,
        "touched": spec.touched,
        "stores": spec.stores,
        "predirty": spec.predirty,
        "cycles": total,
        "instret": instret,
        "entries": spec.entries,
        "unique": spec.entries,
        "duplicates": 0,
        "missing": 0,
        "extra": 0,
        "log_size": spec.log_size,
        "capacity": spec.capacity,
        "initial_idx": spec.initial_idx,
        "replacement_idx": spec.replacement_idx,
        "buffers": spec.buffers,
        "idx0": spec.final_indices[0],
        "idx1": spec.final_indices[1],
        "idx2": spec.final_indices[2],
        "idx3": spec.final_indices[3],
        "faults": len(events),
        "ctl_size": spec.log_size,
        "ctl_base": CTL_BASE,
        "fault_cycles": fault,
        "service_cycles": service,
        "retry_cycles": retry,
        "guest_cycles": guest,
        "end_to_end_cycles": total,
        "status": 0,
    }
    if version == 5:
        sample.update({
            "epochs": spec.epochs,
            "drained": spec.entries if spec.kind == "epoch" else 0,
            **{
                metric: sum(event[metric] for event in epoch_events)
                for metric in dirtygen_report.PHASE_METRICS
            },
        })
    return sample


def valid_log():
    lines = [
        "unrelated Mill line",
        record(
            "BEGIN",
            {
                "version": 4,
                "cases": 24,
                "warmup": 1,
                "reps": 5,
                "capacity": 512,
                "entry_bytes": 8,
                "buffers": 4,
                "max_size": 2,
            },
        ),
    ]
    for case_id, spec in enumerate(
        dirtygen_report.CASE_SPECS[:dirtygen_report.V4_CASE_COUNT]
    ):
        samples = [make_sample(case_id, repetition) for repetition in range(5)]
        for sample in samples:
            lines.append(record("SAMPLE", sample))
            for ordinal, action in enumerate(spec.fault_actions):
                lines.append(
                    record(
                        "FAULT",
                        make_fault(case_id, sample["rep"], ordinal, action),
                    )
                )
        summary = {"case": spec.name, "id": case_id}
        for metric in dirtygen_report.V4_SUMMARY_METRICS:
            values = [sample[metric] for sample in samples]
            summary[f"{metric}_min"] = min(values)
            summary[f"{metric}_median"] = sorted(values)[2]
            summary[f"{metric}_max"] = max(values)
        summary["status"] = 0
        lines.append(record("SUMMARY", summary))
    lines.append("DIRTYGEN_END completed=0x78 failures=0x0 status=0x0")
    return "\n".join(lines) + "\n"


def valid_v5_log(case_first=0, case_limit=dirtygen_report.CASE_COUNT):
    lines = [
        "unrelated Mill line",
        record(
            "BEGIN",
            {
                "version": 5,
                "cases": dirtygen_report.CASE_COUNT,
                "warmup": 1,
                "reps": 5,
                "capacity": 512,
                "entry_bytes": 8,
                "buffers": 4,
                "max_size": 2,
                "max_epochs": 8,
                "case_first": case_first,
                "case_limit": case_limit,
                "desc_bytes": 128,
                "sample_bytes": 192,
                "epoch_bytes": 256,
                "result_bytes": 2048,
            },
        ),
    ]
    for case_id in range(case_first, case_limit):
        spec = dirtygen_report.CASE_SPECS[case_id]
        samples = [make_sample(case_id, repetition, 5) for repetition in range(5)]
        for sample in samples:
            for ordinal in range(spec.epochs):
                lines.append(record("EPOCH", make_epoch(case_id, sample["rep"], ordinal)))
            lines.append(record("SAMPLE", sample))
            for ordinal, action in enumerate(spec.fault_actions):
                lines.append(record("FAULT", make_fault(case_id, sample["rep"], ordinal, action)))
        summary = {"case": spec.name, "id": case_id}
        for metric in dirtygen_report.SUMMARY_METRICS:
            values = [sample[metric] for sample in samples]
            summary[f"{metric}_min"] = min(values)
            summary[f"{metric}_median"] = sorted(values)[2]
            summary[f"{metric}_max"] = max(values)
        summary["status"] = 0
        lines.append(record("SUMMARY", summary))
    lines.append(record("END", {
        "completed": (case_limit - case_first) * 5,
        "failures": 0,
        "status": 0,
    }))
    return "\n".join(lines) + "\n"


class DirtygenReportTest(unittest.TestCase):
    def parse_valid(self):
        report = dirtygen_report.parse_lines(io.StringIO(valid_log()))
        report.validate()
        return report

    def test_valid_v4_matrix_faults_and_rows(self):
        report = self.parse_valid()
        self.assertEqual(len(report.samples), 120)
        self.assertEqual(len(report.faults), 65)
        rows = report.summary_rows()
        self.assertEqual(rows[21]["capacity"], 2048)
        self.assertEqual(rows[22]["kind"], "chain")
        self.assertEqual(rows[23]["idx3"], 512)
        self.assertEqual(rows[23]["faults"], 4)

    def test_v3_is_explicitly_rejected(self):
        text = valid_log().replace("version=0x4", "version=0x3", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "unsupported ABI version 3"):
            report.validate()

    def test_valid_legacy_v5_30_case_log(self):
        text = valid_v5_log(14, 15).replace("cases=0x20", "cases=0x1e", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        report.validate()

    def test_duplicate_sample_is_rejected(self):
        text = valid_log().replace("rep=0x1", "rep=0x0", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "duplicate sample"):
            report.validate()

    def test_duplicate_fault_is_rejected(self):
        text = valid_log()
        fault_line = next(line for line in text.splitlines() if "DIRTYGEN_FAULT" in line)
        report = dirtygen_report.parse_lines(io.StringIO(text + fault_line + "\n"))
        with self.assertRaisesRegex(ValueError, "duplicate fault"):
            report.validate()

    def test_missing_fault_event_is_rejected(self):
        lines = valid_log().splitlines()
        removed = False
        filtered = []
        for line in lines:
            if not removed and "DIRTYGEN_FAULT" in line:
                removed = True
                continue
            filtered.append(line)
        report = dirtygen_report.parse_lines(io.StringIO("\n".join(filtered) + "\n"))
        with self.assertRaisesRegex(ValueError, "fault matrix mismatch"):
            report.validate()

    def test_buffer_transition_is_checked(self):
        text = valid_log().replace(
            "idx0=0x200 idx1=0x200 idx2=0x200 idx3=0x200",
            "idx0=0x200 idx1=0x1ff idx2=0x200 idx3=0x200",
            1,
        )
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "idx1"):
            report.validate()

    def test_dynamic_capacity_is_checked(self):
        text = valid_log().replace("capacity=0x400 initial_idx=0x3ff", "capacity=0x200 initial_idx=0x3ff", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "capacity"):
            report.validate()

    def test_fault_metadata_is_checked(self):
        text = valid_log().replace("stval=0x11000", "stval=0x10000", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "stval"):
            report.validate()

    def test_overflow_fault_index_is_checked(self):
        text = valid_v5_log(30, 31).replace("index=0x201", "index=0x200", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "index"):
            report.validate()

    def test_logger_off_full_index_and_entries_are_checked(self):
        text = valid_v5_log(31, 32).replace("idx0=0x200", "idx0=0x201", 1)
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "idx0"):
            report.validate()

    def test_event_cycle_sum_is_checked(self):
        report = dirtygen_report.parse_lines(io.StringIO(valid_log()))
        event = next(
            event
            for event in report.faults
            if event["id"] == 14 and event["rep"] == 0
        )
        event["fault_cycles"] += 1
        with self.assertRaisesRegex(ValueError, "event sum"):
            report.validate()

    def test_misaligned_control_base_is_checked(self):
        report = dirtygen_report.parse_lines(io.StringIO(valid_log()))
        sample = next(
            sample
            for sample in report.samples
            if sample["id"] == 18 and sample["rep"] == 0
        )
        sample["ctl_base"] += dirtygen_report.PAGE_SIZE
        with self.assertRaisesRegex(ValueError, "misaligned ctl_base"):
            report.validate()

    def test_missing_end_is_rejected(self):
        report = dirtygen_report.parse_lines(
            io.StringIO(valid_log().replace("DIRTYGEN_END", "IGNORED_END"))
        )
        with self.assertRaisesRegex(ValueError, "missing DIRTYGEN_END"):
            report.validate()

    def test_csv_table_and_json_expose_v4_fields(self):
        report = self.parse_valid()
        csv_output = io.StringIO()
        table_output = io.StringIO()
        json_output = io.StringIO()
        dirtygen_report.emit_csv(report, csv_output)
        dirtygen_report.emit_table(report, table_output)
        dirtygen_report.emit_json(report, json_output)
        self.assertIn("guest_cycles_median", csv_output.getvalue().splitlines()[0])
        self.assertIn("boundary and replacement cases", table_output.getvalue())
        self.assertIn("replace_chain_exhaust_stop", table_output.getvalue())
        decoded = json.loads(json_output.getvalue())
        self.assertEqual(len(decoded["faults"]), 65)

    def test_valid_v5_full_matrix(self):
        report = dirtygen_report.parse_lines(io.StringIO(valid_v5_log()))
        report.validate()
        self.assertEqual(len(report.samples), 160)
        self.assertEqual(len(report.faults), 70)
        self.assertEqual(len(report.epochs), 240)
        self.assertEqual(len(report.summaries), 32)
        self.assertEqual(report.summary_rows()[29]["entries"], 1024)

    def test_valid_v5_partial_range(self):
        report = dirtygen_report.parse_lines(
            io.StringIO(valid_v5_log(24, 25))
        )
        report.validate()
        self.assertEqual(len(report.samples), 5)
        self.assertEqual(len(report.epochs), 40)
        self.assertEqual(report.end["completed"], 5)

    def test_missing_epoch_is_rejected(self):
        lines = valid_v5_log(25, 26).splitlines()
        removed = False
        filtered = []
        for line in lines:
            if not removed and "DIRTYGEN_EPOCH" in line:
                removed = True
                continue
            filtered.append(line)
        report = dirtygen_report.parse_lines(
            io.StringIO("\n".join(filtered) + "\n")
        )
        with self.assertRaisesRegex(ValueError, "epoch matrix mismatch"):
            report.validate()

    def test_duplicate_epoch_is_rejected(self):
        text = valid_v5_log(25, 26)
        epoch_line = next(
            line for line in text.splitlines() if "DIRTYGEN_EPOCH" in line
        )
        report = dirtygen_report.parse_lines(
            io.StringIO(text + epoch_line + "\n")
        )
        with self.assertRaisesRegex(ValueError, "duplicate epoch"):
            report.validate()

    def test_epoch_bitmap_is_checked(self):
        text = valid_v5_log(27, 28).replace(
            "bitmap0=0xffff", "bitmap0=0xfffe", 1
        )
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "bitmap0"):
            report.validate()

    def test_epoch_reset_index_is_checked(self):
        text = valid_v5_log(25, 26).replace(
            "idx_after=0x0", "idx_after=0x1", 1
        )
        report = dirtygen_report.parse_lines(io.StringIO(text))
        with self.assertRaisesRegex(ValueError, "idx_after"):
            report.validate()

    def test_epoch_sample_phase_sum_is_checked(self):
        report = dirtygen_report.parse_lines(
            io.StringIO(valid_v5_log(25, 26))
        )
        report.samples[0]["drain_cycles"] += 1
        with self.assertRaisesRegex(ValueError, "epoch sum"):
            report.validate()

    def test_v5_outputs_expose_epoch_metrics(self):
        report = dirtygen_report.parse_lines(
            io.StringIO(valid_v5_log(24, 30))
        )
        report.validate()
        csv_output = io.StringIO()
        table_output = io.StringIO()
        json_output = io.StringIO()
        dirtygen_report.emit_csv(report, csv_output)
        dirtygen_report.emit_table(report, table_output)
        dirtygen_report.emit_json(report, json_output)
        self.assertIn("lifecycle_cycles_median", csv_output.getvalue().splitlines()[0])
        self.assertIn("drain/reuse epoch cases", table_output.getvalue())
        decoded = json.loads(json_output.getvalue())
        self.assertEqual(len(decoded["epochs"]), 240)


if __name__ == "__main__":
    unittest.main()
