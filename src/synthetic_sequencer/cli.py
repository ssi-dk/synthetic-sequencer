"""A small, dependency-free NextSeq FASTQ replayer (POSIX filesystem)."""

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import threading
import time
import uuid


class InvalidTemplate(ValueError):
    pass


FASTQ = re.compile(r"(.+)(_S\d+(?:_L\d{3})?_R([12])_\d{3}\.fastq\.gz)$")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def sheet_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def sample_rows(rows):
    """Return (row index, columns) for v1 or v2 sample data."""
    columns = None
    active = False
    found = False
    for index, row in enumerate(rows):
        if not row or not any(row):
            continue
        if row[0].startswith("["):
            active = row[0] in ("[Data]", "[BCLConvert_Data]")
            columns = None
            continue
        if not active:
            continue
        if columns is None:
            columns = {name: pos for pos, name in enumerate(row)}
            if "Sample_ID" not in columns:
                raise InvalidTemplate("Sample sheet data needs a Sample_ID column")
            continue
        if len(row) <= max(columns.values()):
            raise InvalidTemplate("Short sample sheet data row")
        found = True
        yield index, columns
    if not found:
        raise InvalidTemplate("Sample sheet has no sample data")


def identities(rows):
    samples = {}
    aliases = {}
    for index, columns in sample_rows(rows):
        row = rows[index]
        sid = row[columns["Sample_ID"]]
        name = row[columns["Sample_Name"]] if "Sample_Name" in columns else ""
        if not SAFE_ID.fullmatch(sid) or (name and not SAFE_ID.fullmatch(name)):
            raise InvalidTemplate("Sample identifiers must use letters, digits, _ or -")
        # Multiple lanes for one sample are allowed; inconsistent names are not.
        if sid in samples and samples[sid] != name:
            raise InvalidTemplate(f"Inconsistent sample name for {sid}")
        samples[sid] = name
        for alias in (sid, name):
            if alias:
                if alias in aliases and aliases[alias] != sid:
                    raise InvalidTemplate(f"Ambiguous sample identifier: {alias}")
                aliases[alias] = sid
    return samples, aliases


def check_fastq(path):
    count = 0
    with gzip.open(path, "rt", encoding="ascii") as handle:
        while True:
            header = handle.readline()
            if not header:
                break
            sequence, plus, quality = [handle.readline().rstrip("\r\n") for _ in range(3)]
            if not header.startswith("@") or not plus.startswith("+") or not sequence:
                raise InvalidTemplate(f"Invalid FASTQ record: {path.name}")
            if len(sequence) != len(quality):
                raise InvalidTemplate(f"Sequence/quality length mismatch: {path.name}")
            count += 1
    if not count:
        raise InvalidTemplate(f"Empty FASTQ: {path.name}")
    return count


def validate(template):
    template = Path(template)
    if not template.is_dir() or template.is_symlink():
        raise InvalidTemplate("Template must be an ordinary directory")
    if any(path.is_symlink() for path in template.rglob("*")):
        raise InvalidTemplate("Template symlinks are not supported")
    root_sheet = template / "SampleSheet.csv"
    samples, aliases = identities(sheet_rows(root_sheet))
    sheets = [root_sheet] + sorted((template / "Analysis/1").rglob("SampleSheet.csv"))
    for sheet in sheets[1:]:
        if identities(sheet_rows(sheet))[0] != samples:
            raise InvalidTemplate(f"Sample identities differ in {sheet.relative_to(template)}")
    files = sorted((template / "Analysis/1/Data/fastq").glob("*.fastq.gz"))
    if not files:
        raise InvalidTemplate("No FASTQs in Analysis/1/Data/fastq")
    if set(template.rglob("*.fastq.gz")) != set(files):
        raise InvalidTemplate("All FASTQs must be directly in Analysis/1/Data/fastq; additional analyses are not supported")
    pairs = {}
    observed = set()
    for path in files:
        match = FASTQ.fullmatch(path.name)
        if not match or match[1] not in aliases:
            raise InvalidTemplate(f"Unmapped or unsupported FASTQ filename: {path.name}")
        observed.add(aliases[match[1]])
        pair_key = match[1] + re.sub(r"_R[12]_", "_R?_", match[2])
        pairs.setdefault(pair_key, {})[match[3]] = check_fastq(path)
    if observed != set(samples):
        raise InvalidTemplate("Every sample sheet sample must have FASTQs")
    if any(set(pair) != {"1", "2"} or pair["1"] != pair["2"] for pair in pairs.values()):
        raise InvalidTemplate("FASTQs must have R1/R2 pairs with equal record counts")
    return {"samples": samples, "aliases": aliases, "sheets": sheets, "files": files}


def rewrite_sheet(source, destination, mapping, run_id, date):
    rows = sheet_rows(source)
    for index, columns in sample_rows(rows):
        for key in ("Sample_ID", "Sample_Name"):
            if key in columns and rows[index][columns[key]]:
                rows[index][columns[key]] = mapping[rows[index][columns[key]]]
    in_header = False
    for row in rows:
        if not row:
            continue
        if row[0].startswith("["):
            in_header = row[0] == "[Header]"
        elif in_header and len(row) > 1:
            if row[0] in ("RunName", "Run Name", "Experiment Name"):
                row[1] = run_id
            elif row[0] == "Date":
                row[1] = date
    with destination.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def load_config(path):
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")
    required = {"template", "output_root", "work_root"}
    if required - set(config):
        raise ValueError(f"Missing config keys: {sorted(required - set(config))}")
    allowed = {"template", "output_root", "work_root", "instrument_id", "directory_mode", "file_mode", "copy_delay_seconds", "run_interval_seconds", "heartbeat_interval_seconds", "max_runs"}
    if set(config) - allowed:
        raise ValueError(f"Unknown config keys: {sorted(set(config) - allowed)}")
    for key in ("template", "output_root", "work_root"):
        if not isinstance(config[key], str) or not config[key]:
            raise ValueError(f"{key} must be a nonempty path string")
        value = Path(config[key]).expanduser()
        if not value.is_absolute():
            value = Path(path).resolve().parent / value
        config[key] = value.resolve()
    config.setdefault("instrument_id", "VHSYNTH01")
    if not isinstance(config["instrument_id"], str) or not SAFE_ID.fullmatch(config["instrument_id"]):
        raise ValueError("Invalid instrument_id")
    for key, default in (("directory_mode", "2750"), ("file_mode", "0640")):
        config[key] = int(str(config.get(key, default)), 8)
        if config[key] & ~0o2777 or config[key] & 0o002:
            raise ValueError("Unsupported or world-writable permissions")
    config["copy_delay_seconds"] = float(config.get("copy_delay_seconds", 0))
    if not 0 <= config["copy_delay_seconds"] <= 3600:
        raise ValueError("copy_delay_seconds must be between 0 and 3600")
    config.setdefault("run_interval_seconds", 3600)
    config.setdefault("heartbeat_interval_seconds", 30)
    config.setdefault("max_runs", None)
    for key in ("run_interval_seconds", "heartbeat_interval_seconds", "max_runs"):
        if key == "max_runs" and config[key] is None:
            continue
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer" + (" or null" if key == "max_runs" else ""))
    paths = [config[key] for key in ("template", "output_root", "work_root")]
    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError("Template, output and work roots must be separate, non-nested directories")
    return config


def prune_runs(output, max_runs, new_run):
    """Only remove recognizable published simulator runs, oldest first."""
    removed = []
    if max_runs is None:
        return removed, []
    candidates = []
    for path in output.iterdir():
        if path.name == new_run or path.is_symlink() or not path.is_dir():
            continue
        marker = path / "synthetic-run.json"
        if marker.is_symlink() or not marker.is_file():
            continue
        try:
            metadata = json.loads(marker.read_text())
            if not isinstance(metadata, dict) or metadata.get("synthetic") is not True:
                continue
            if metadata.get("profile") != "nextseq-1000-2000" or metadata.get("run_id") != path.name:
                continue
            created = datetime.fromisoformat(metadata["created_at"])
            if created.tzinfo is None:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        candidates.append((created, path.name, path))
    for _, _, path in sorted(candidates)[:max(0, len(candidates) + 1 - max_runs)]:
        try:
            shutil.rmtree(path)
        except OSError as error:
            return removed, [{"run_id": path.name, "error": str(error)}]
        removed.append(path.name)
    return removed, []


def prepare_roots(config):
    output, work = config["output_root"], config["work_root"]
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    os.chmod(work, 0o700)
    if output.stat().st_dev != work.stat().st_dev:
        raise ValueError("Output and work roots must share a filesystem for atomic publication")


def write_json(path, data, mode):
    """Readers see either the previous complete document or the new one."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(json.dumps(data, indent=2) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def heartbeat(config):
    """A scheduler owns liveness; successful publications have separate state."""
    prepare_roots(config)
    with (config["work_root"] / "scheduler.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A scheduler is already running for this work root") from None
        os.chmod(config["output_root"], config["directory_mode"])
        done = threading.Event()

        def update(status):
            try:
                success = json.loads((config["work_root"] / "last-successful-run.json").read_text())
            except FileNotFoundError:
                success = {}
            write_json(config["output_root"] / "heartbeat.json", {
                "sequencer": config["instrument_id"], "status": status,
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "heartbeat_interval_seconds": config["heartbeat_interval_seconds"],
                "last_successful_run": success.get("completed_at"),
                "last_successful_run_id": success.get("run_id"),
            }, config["file_mode"])

        def pulse():
            while not done.wait(config["heartbeat_interval_seconds"]):
                try:
                    update("running")
                except (ValueError, OSError) as error:
                    print(json.dumps({"status": "heartbeat_failed", "error": str(error)}),
                          file=sys.stderr, flush=True)

        update("running")
        worker = threading.Thread(target=pulse, daemon=True)
        worker.start()
        try:
            yield
        finally:
            done.set()
            worker.join()
            update("stopped")


def replay(config):
    prepare_roots(config)
    output, work = config["output_root"], config["work_root"]
    with (work / "replay.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "replay already running"}
        template = config["template"]
        validated = validate(template)
        os.chmod(output, config["directory_mode"])
        counter = work / "counter"
        sequence = int(counter.read_text()) + 1 if counter.exists() else 1
        temporary_counter = work / "counter.tmp"
        temporary_counter.write_text(str(sequence))
        temporary_counter.replace(counter)
        now = datetime.now(timezone.utc)
        suffix = uuid.uuid4().hex[:12]
        run_id = f"{now:%y%m%d}_{config['instrument_id']}_{sequence:04d}_SYNTH{suffix}"
        destination = output / run_id
        if destination.exists():
            raise ValueError("Refusing to overwrite a run")
        staging = work / run_id
        staging.mkdir(mode=0o700)
        mapping = {alias: f"{alias}_{suffix}" for alias in validated["aliases"]}
        manifest = []
        try:
            for source in validated["sheets"]:
                target = staging / source.relative_to(template)
                target.parent.mkdir(parents=True, exist_ok=True)
                rewrite_sheet(source, target, mapping, run_id, now.date().isoformat())
            for source in validated["files"]:
                match = FASTQ.fullmatch(source.name)
                target = staging / source.relative_to(template).with_name(mapping[match[1]] + match[2])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if config["copy_delay_seconds"]:
                    time.sleep(config["copy_delay_seconds"])
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    with path.open("rb") as handle:
                        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
                    manifest.append({"path": str(path.relative_to(staging)), "size": path.stat().st_size, "sha256": checksum})
            (staging / "synthetic-run.json").write_text(json.dumps({
                "synthetic": True, "profile": "nextseq-1000-2000", "run_id": run_id,
                "created_at": now.isoformat(), "template": template.name,
                "sample_mapping": mapping, "files": manifest,
            }, indent=2) + "\n")
            for path in staging.rglob("*"):
                os.chmod(path, config["directory_mode"] if path.is_dir() else config["file_mode"])
            os.chmod(staging, config["directory_mode"])
            # No pretend vendor completion flags: the directory becomes visible only when ready.
            staging.rename(destination)
            write_json(work / "last-successful-run.json", {
                "run_id": run_id, "completed_at": datetime.now(timezone.utc).isoformat(),
            }, 0o600)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        result = {"status": "completed", "run_id": run_id, "output": str(destination), "samples": len(validated["samples"])}
        try:
            removed, errors = prune_runs(output, config.get("max_runs"), run_id)
        except OSError as error:
            removed, errors = [], [{"error": str(error)}]
        result["removed_runs"] = removed
        if errors:
            result.update(status="retention_failed", retention_errors=errors)
        return result


def schedule(config, stop):
    with heartbeat(config):
        run_schedule(config, stop)


def run_schedule(config, stop):
    """Fixed interval starts; wait before the first run, skip missed ticks."""
    interval = config["run_interval_seconds"]
    print(json.dumps({"status": "scheduler_started", "run_interval_seconds": interval,
                      "max_runs": config["max_runs"]}), flush=True)
    next_due = time.monotonic() + interval
    while not stop.wait(max(0, next_due - time.monotonic())):
        try:
            result = replay(config)
        except (ValueError, OSError, EOFError) as error:
            result = {"status": "failed", "error": str(error)}
        print(json.dumps(result), flush=True)
        next_due += interval
        now = time.monotonic()
        if next_due <= now:
            next_due = now + interval
    print(json.dumps({"status": "scheduler_stopped"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON configuration file")
    parser.add_argument("operation", choices=("validate", "replay", "schedule"))
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.operation == "validate":
            result = validate(config["template"])
            print(json.dumps({"status": "valid", "samples": len(result["samples"]), "fastqs": len(result["files"])}))
        elif args.operation == "schedule":
            stop = threading.Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: stop.set())
            schedule(config, stop)
        else:
            result = replay(config)
            print(json.dumps(result))
            return 1 if result["status"] == "retention_failed" else 0
    except (ValueError, OSError, EOFError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
