import csv
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from synthetic_sequencer.cli import InvalidTemplate, load_config, replay, schedule, validate


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = self.root / "saved/demo"
        reads = self.template / "Analysis/1/Data/fastq"
        reads.mkdir(parents=True)
        self.rows = [["[Header]"], ["RunName", "original"], ["Date", "2000-01-01"],
                     ["[Data]"], ["Sample_ID", "Sample_Name", "index", "index2", "Lane"],
                     ["TEST001", "sample_one", "ACGT", "TGCA", "1"]]
        for path in (self.template / "SampleSheet.csv", self.template / "Analysis/1/Data/SampleSheet.csv"):
            with path.open("w", newline="") as handle:
                csv.writer(handle).writerows(self.rows)
        for read in (1, 2):
            (reads / f"sample_one_S1_L001_R{read}_001.fastq.gz").write_bytes(
                gzip.compress(f"@synthetic {read}:N:0:ACGT\nACGT\n+\nIIII\n".encode(), mtime=0))
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({"template": "saved/demo", "output_root": "data/runs", "work_root": "data/work"}))
        self.config = load_config(self.config_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_replay_consistency_and_source_immutability(self):
        # BCLs and diagnostics present in a saved dataset must never be copied.
        (self.template / "raw.cbcl").write_bytes(b"not real BCL")
        (self.template / "diagnostics.log").write_text("omit me")
        original = {str(p.relative_to(self.template)): p.read_bytes() for p in self.template.rglob("*") if p.is_file()}
        first, second = replay(self.config), replay(self.config)
        self.assertNotEqual(first["run_id"], second["run_id"])
        maps = []
        for run in (first, second):
            output = Path(run["output"])
            manifest = json.loads((output / "synthetic-run.json").read_text())
            mapping = manifest["sample_mapping"]
            maps.append(mapping)
            for read in (1, 2):
                copied = output / f"Analysis/1/Data/fastq/{mapping['sample_one']}_S1_L001_R{read}_001.fastq.gz"
                self.assertEqual(copied.read_bytes(), original[f"Analysis/1/Data/fastq/sample_one_S1_L001_R{read}_001.fastq.gz"])
                self.assertEqual(copied.stat().st_mode & 0o777, 0o640)
            with (output / "SampleSheet.csv").open(newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[-1], [mapping["TEST001"], mapping["sample_one"], "ACGT", "TGCA", "1"])
            self.assertEqual(rows[1], ["RunName", run["run_id"]])
            self.assertEqual((output / "SampleSheet.csv").read_bytes(), (output / "Analysis/1/Data/SampleSheet.csv").read_bytes())
            self.assertFalse((output / "raw.cbcl").exists())
            self.assertFalse((output / "diagnostics.log").exists())
        self.assertNotEqual(maps[0]["TEST001"], maps[1]["TEST001"])
        self.assertEqual(original, {str(p.relative_to(self.template)): p.read_bytes() for p in self.template.rglob("*") if p.is_file()})

    def test_bad_template_missing_pair(self):
        next(self.template.rglob("*_R2_*.fastq.gz")).unlink()
        with self.assertRaisesRegex(InvalidTemplate, "R1/R2"):
            validate(self.template)

    def test_bad_template_mismatched_sheet(self):
        sheet = self.template / "Analysis/1/Data/SampleSheet.csv"
        sheet.write_text(sheet.read_text().replace("TEST001", "OTHER"))
        with self.assertRaisesRegex(InvalidTemplate, "identities differ"):
            validate(self.template)

    def test_bad_template_unmapped_fastq(self):
        path = next(self.template.rglob("*_R1_*.fastq.gz"))
        path.rename(path.with_name(path.name.replace("sample_one", "unknown")))
        with self.assertRaisesRegex(InvalidTemplate, "Unmapped"):
            validate(self.template)

    def test_extra_analysis_is_not_silently_ignored(self):
        (self.template / "extra.fastq.gz").write_bytes(next(self.template.rglob("*.fastq.gz")).read_bytes())
        with self.assertRaisesRegex(InvalidTemplate, "additional analyses"):
            validate(self.template)

    def test_symlink_rejected(self):
        (self.template / "escape").symlink_to(self.root)
        with self.assertRaisesRegex(InvalidTemplate, "symlinks"):
            validate(self.template)

    def test_corrupt_gzip_rejected(self):
        next(self.template.rglob("*.fastq.gz")).write_bytes(b"broken")
        with self.assertRaises(OSError):
            validate(self.template)

    def test_failed_copy_never_published(self):
        with patch("synthetic_sequencer.cli.shutil.copyfile", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                replay(self.config)
        self.assertEqual(list(self.config["output_root"].iterdir()), [])
        self.assertFalse(any(p.is_dir() for p in self.config["work_root"].iterdir()))

    def test_concurrent_invocation_and_termination(self):
        raw = json.loads(self.config_path.read_text())
        raw["copy_delay_seconds"] = 30
        self.config_path.write_text(json.dumps(raw))
        process = subprocess.Popen([sys.executable, "-m", "synthetic_sequencer.cli", "--config", str(self.config_path), "replay"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.config["work_root"].exists() and any(self.config["work_root"].rglob("*.fastq.gz")):
                    break
                if process.poll() is not None:
                    self.fail(str(process.communicate()))
                time.sleep(0.05)
            else:
                self.fail("Replay did not reach staged copy")
            self.assertEqual(list(self.config["output_root"].iterdir()), [])
            self.assertEqual(replay(self.config)["status"], "skipped")
            process.terminate()
            process.communicate(timeout=5)
            self.assertEqual(list(self.config["output_root"].iterdir()), [])
            self.assertEqual(replay(self.config)["status"], "completed")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_paths_must_not_overlap(self):
        self.config_path.write_text(json.dumps({"template": "saved/demo", "output_root": "saved", "work_root": "work"}))
        with self.assertRaisesRegex(ValueError, "non-nested"):
            load_config(self.config_path)

    def test_missing_config_is_actionable(self):
        self.config_path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "Missing config keys"):
            load_config(self.config_path)

    def test_retention_oldest_first_and_unrelated_data_untouched(self):
        self.config["max_runs"] = 2
        first, second = replay(self.config), replay(self.config)
        output = self.config["output_root"]
        unrelated = output / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("keep")
        (output / "saved-link").symlink_to(self.template)
        malformed = output / "malformed"
        malformed.mkdir()
        (malformed / "synthetic-run.json").write_text("not json")
        os.utime(first["output"], (9999999999, 9999999999))
        third = replay(self.config)
        self.assertEqual(third["removed_runs"], [first["run_id"]])
        self.assertFalse(Path(first["output"]).exists())
        self.assertTrue(Path(second["output"]).exists())
        self.assertTrue(Path(third["output"]).exists())
        self.assertTrue((unrelated / "keep.txt").exists())
        self.assertTrue((self.template / "SampleSheet.csv").exists())
        self.assertTrue((output / "saved-link").is_symlink())
        self.assertTrue(malformed.exists())

    def test_lowered_limit_prunes_all_excess_after_success_only(self):
        previous = [replay(self.config) for _ in range(3)]
        self.config["max_runs"] = 1
        with patch("synthetic_sequencer.cli.shutil.copyfile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                replay(self.config)
        self.assertTrue(all(Path(run["output"]).exists() for run in previous))
        newest = replay(self.config)
        self.assertEqual(newest["removed_runs"], [run["run_id"] for run in previous])
        self.assertEqual(list(self.config["output_root"].iterdir()), [Path(newest["output"])])

    def test_retention_error_preserves_new_run_and_reports_failure(self):
        old = replay(self.config)
        self.config["max_runs"] = 1
        with patch("synthetic_sequencer.cli.shutil.rmtree", side_effect=OSError("cannot remove")):
            new = replay(self.config)
        self.assertEqual(new["status"], "retention_failed")
        self.assertTrue(Path(new["output"]).exists())
        self.assertTrue(Path(old["output"]).exists())
        self.assertIn("cannot remove", new["retention_errors"][0]["error"])

    def test_invalid_cadence_and_limit(self):
        raw = json.loads(self.config_path.read_text())
        for key in ("run_interval_seconds", "heartbeat_interval_seconds", "max_runs"):
            for value in (0, -1, True, "2", 1.5):
                with self.subTest(key=key, value=value):
                    self.config_path.write_text(json.dumps({**raw, key: value}))
                    with self.assertRaisesRegex(ValueError, key):
                        load_config(self.config_path)

    def test_scheduler_retries_on_next_tick_after_failure(self):
        self.config["run_interval_seconds"] = 1
        stop = Mock()
        stop.wait.side_effect = [False, False, True]
        logs = io.StringIO()
        with patch("synthetic_sequencer.cli.time.monotonic", side_effect=[0, 0, 1, 1, 2, 2]), \
             patch("synthetic_sequencer.cli.replay", side_effect=[OSError("temporary"), {"status": "completed"}]) as run, \
             redirect_stdout(logs):
            schedule(self.config, stop)
        self.assertEqual(run.call_count, 2)
        self.assertEqual([call.args[0] for call in stop.wait.call_args_list], [1, 1, 1])
        self.assertEqual([json.loads(line)["status"] for line in logs.getvalue().splitlines()],
                         ["scheduler_started", "failed", "completed", "scheduler_stopped"])

    def test_real_scheduler_and_manual_run_share_retention(self):
        raw = json.loads(self.config_path.read_text())
        raw.update(run_interval_seconds=1, max_runs=2)
        self.config_path.write_text(json.dumps(raw))
        process = subprocess.Popen([sys.executable, "-m", "synthetic_sequencer.cli", "--config", str(self.config_path), "schedule"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            counter = self.config["work_root"] / "counter"
            while time.monotonic() < deadline:
                if counter.exists() and int(counter.read_text()) >= 3:
                    break
                self.assertIsNone(process.poll())
                time.sleep(0.05)
            else:
                self.fail("Scheduler did not publish three runs")
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertIn('"scheduler_stopped"', stdout.decode())
            runs = list(self.config["output_root"].glob("*/synthetic-run.json"))
            self.assertEqual(len(runs), 2)
            manual = replay(load_config(self.config_path))
            self.assertEqual(manual["status"], "completed")
            self.assertEqual(len(list(self.config["output_root"].glob("*/synthetic-run.json"))), 2)
            self.assertEqual(len(manual["removed_runs"]), 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_heartbeat_during_idle_manual_replay_failure_and_restart(self):
        raw = json.loads(self.config_path.read_text())
        raw.update(heartbeat_interval_seconds=1, run_interval_seconds=3600)
        self.config_path.write_text(json.dumps(raw))
        beat_path = self.config["output_root"] / "heartbeat.json"

        def wait_for(process, predicate):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.assertIsNone(process.poll())
                if beat_path.exists():
                    beat = json.loads(beat_path.read_text())
                    if predicate(beat):
                        return beat
                time.sleep(0.05)
            self.fail("Heartbeat did not reach expected state")

        command = [sys.executable, "-m", "synthetic_sequencer.cli", "--config", str(self.config_path), "schedule"]
        success = None
        for restart in (False, True):
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                first = wait_for(process, lambda beat: beat["status"] == "running")
                self.assertEqual(first["last_successful_run"], success)
                self.assertEqual(beat_path.stat().st_mode & 0o777, 0o640)
                second = wait_for(process, lambda beat: beat["last_heartbeat"] > first["last_heartbeat"])
                self.assertEqual(second["last_successful_run"], success)
                duplicate_config = self.root / "duplicate.json"
                duplicate_config.write_text(json.dumps({**raw, "directory_mode": "0700"}))
                mode = self.config["output_root"].stat().st_mode
                duplicate = subprocess.run([*command[:-2], str(duplicate_config), "schedule"], capture_output=True, timeout=5)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn(b"already running", duplicate.stderr)
                self.assertEqual(self.config["output_root"].stat().st_mode, mode)
                if not restart:
                    result = replay(self.config)
                    completed = wait_for(process, lambda beat: beat["last_successful_run_id"] == result["run_id"])
                    success = completed["last_successful_run"]
                    self.assertIsNotNone(success)
                    with patch("synthetic_sequencer.cli.shutil.copyfile", side_effect=OSError("disk full")):
                        with self.assertRaises(OSError):
                            replay(self.config)
                    failed = wait_for(process, lambda beat: beat["last_heartbeat"] > completed["last_heartbeat"])
                    self.assertEqual(failed["last_successful_run"], success)
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr.decode())
                self.assertEqual(json.loads(beat_path.read_text())["status"], "stopped")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_heartbeat_continues_during_slow_scheduled_copy(self):
        raw = json.loads(self.config_path.read_text())
        raw.update(heartbeat_interval_seconds=1, run_interval_seconds=1, copy_delay_seconds=2)
        self.config_path.write_text(json.dumps(raw))
        process = subprocess.Popen([sys.executable, "-m", "synthetic_sequencer.cli", "--config", str(self.config_path), "schedule"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            beats = []
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                self.assertIsNone(process.poll())
                path = self.config["output_root"] / "heartbeat.json"
                if path.exists():
                    beat = json.loads(path.read_text())
                    if beat["last_successful_run"]:
                        break
                    if any(self.config["work_root"].rglob("*.fastq.gz")):
                        beats.append(beat["last_heartbeat"])
                time.sleep(0.05)
            else:
                self.fail("Slow scheduled replay did not complete")
            self.assertGreaterEqual(len(set(beats)), 2)
            process.terminate()
            _, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, stderr.decode())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
