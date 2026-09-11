# Synthetic Sequencer

Replay a saved NextSeq 1000/2000 FASTQ dataset as new runs for downstream file
transfer testing. Every replay creates new run and sample identities while
preserving the compressed FASTQ bytes. This tool performs no sequencing,
base calling, demultiplexing, or biological simulation.

The app owns the Python CLI and producer image. Saved sequencing datasets,
deployment configuration, SSH endpoints, credentials, and cron belong to the
separate deploy repository. No saved datasets or credentials are in this image.

## Run locally

Python 3.11+ and a POSIX filesystem are required. The Docker image uses Python
3.12 on Linux. There are no application runtime dependencies.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/synthetic-sequencer --config /path/to/replay.json validate
.venv/bin/synthetic-sequencer --config /path/to/replay.json replay
```

Example configuration; paths are examples, not deployment locations:

```json
{
  "template": "/templates/nextseq-demo",
  "output_root": "/usr/local/Illumina/runs",
  "work_root": "/usr/local/Illumina/.replay",
  "instrument_id": "VHSYNTH01",
  "directory_mode": "2750",
  "file_mode": "0640",
  "copy_delay_seconds": 0,
  "run_interval_seconds": 3600,
  "max_runs": 10
}
```

The first three fields are required. Relative paths resolve against the config
file; the others have the defaults shown, except `max_runs`, which defaults to
`null` (unlimited) when omitted for backward compatibility. Output and work roots must be separate
directories on the same filesystem, outside the template tree. All producers
for one output root must use the same work root and numeric user/group identity.

The CLI emits JSON. A failed operation exits 1; a completed operation exits 0.
An overlapping replay exits 0 with `status: skipped` and a reason, so cron can
report a skipped tick separately from failure. Validation reads and checks all
compressed FASTQs; its cost grows with the dataset size.

## Template and replay contract

The initial profile accepts one analysis with paired, gzip-compressed FASTQs:

```text
saved-run/
  SampleSheet.csv
  Analysis/1/Data/
    SampleSheet.csv             # optional matching copy
    Reports/SampleSheet.csv     # optional matching copy
    fastq/
      SAMPLE001_S1_L001_R1_001.fastq.gz
      SAMPLE001_S1_L001_R2_001.fastq.gz
```

Sample sheets may use `[Data]` or `[BCLConvert_Data]`; `Sample_ID` is required
and `Sample_Name` is optional. IDs and names must use letters, digits, underscores
or hyphens. Repeated rows for lanes are supported when sample names agree.
FASTQ prefixes must match a sample ID or sample name unambiguously. A lane
component is optional, and each R1/R2 pair must contain equal record counts.
Every listed sample must have data. FASTQs elsewhere, additional analyses,
symlinks, corrupt gzip data, unmatched files, and inconsistent sheet identities
fail validation instead of silently generating a partial run. Undetermined
reads are not supported unless explicitly represented as a sample.

Each run is named `YYMMDD_<instrument>_<counter>_SYNTH<unique-suffix>` in UTC.
Each sample ID and nonempty sample name gains the same run-specific suffix.
All retained sample-sheet copies and matching FASTQ prefixes are updated.
Existing header fields `RunName`, `Run Name`, `Experiment Name`, and `Date` are
updated; missing fields are not invented. Indexes, lane fields, pairing, and
all other sheet values remain unchanged. FASTQ read headers intentionally
retain the template's original identities because FASTQ bytes are not rewritten.

Only the sample sheets and mapped FASTQs are copied. BCL/CBCL files, reports,
metrics, XML, and diagnostics are excluded. `synthetic-run.json` records the
profile, run identity, template basename, sample mapping, UTC time, payload
sizes, and SHA-256 checksums. It contains no absolute template path. It is
simulator provenance, not an Illumina file.

The simulator stages files in the private work root, applies requested modes,
then renames the directory into the output root. Consumers therefore see only
completed runs. No `COMPLETE`, `CopyComplete.txt`, or other vendor flag is
fabricated. A consumer that requires a vendor completion flag needs an explicit
adapter; vendor marker detection and sequencer-sync integration are not claimed.

A filesystem lock serializes validation and replay. Failed copies are removed
when an exception can be handled. Forced termination or host failure can leave
a hidden staging folder; later runs use new identities and never publish it.
Retention applies only to completed simulator runs, never private staging.
There is no automatic recovery of interrupted runs. Once no replay is running, the operator may inspect and remove abandoned staging directories;
keep `replay.lock` and `counter`. Publication is atomic visibility, not a promise
of power-loss durability across all filesystems.

## Automatic cadence, manual runs, and retention

`run_interval_seconds` is a positive integer cadence in seconds, defaulting to
3600. Start the long-running scheduler with:

```sh
synthetic-sequencer --config /path/to/replay.json schedule
```

The first run starts after one full interval. Subsequent start times follow a
monotonic interval clock; if replay takes longer than the interval, missed ticks
are skipped without a catch-up burst. Failures are logged as JSON and retried
at a later tick. SIGTERM/SIGINT stop future ticks after any current replay finishes.
Restart the scheduler to apply config changes; restarting begins a fresh interval.

The ordinary `replay` command forces an immediate run outside the schedule. It
does not reset the scheduler's timer. Manual and automatic invocations share the
same lock and retention policy; a busy producer reports `skipped` rather than
starting an overlapping copy.

Set `max_runs` to a positive integer to retain at most that many completed
simulator runs in the configured output root, including the newly created run.
After successful publication, remove the oldest excess runs under the same lock.
Age comes from `created_at` in `synthetic-run.json`, not directory modification
time. The just-published run is always retained. Reducing the limit removes all
excess old runs after the next successful replay; editing config alone deletes
nothing. There may briefly be one extra run between publication and cleanup.

Only real directories with a matching simulator manifest and valid timestamp
are eligible. Templates, staging, symlinked directories, and unrelated or
unrecognized folders are never counted or deleted. The cap is per output root
across templates/instruments, not per sample. Retention does not wait for a
consumer to finish copying, so size the cap for the desired extraction window.

If copying fails, existing runs are untouched. If pruning fails after publication,
keep the new run and report `retention_failed`, `retention_errors`, and any
`removed_runs`; manual replay exits 1. The scheduler logs the error and continues
on the next tick. An unsuccessful cleanup may leave more than the configured
limit. Successful replay JSON also lists `removed_runs` for auditability.

## Image and permissions

```sh
docker build -t synthetic-sequencer:local .
```

The image defaults to UID 20001 and GID 20000. Deployment prepares the mounted
volume and may override the numeric IDs. Files default to `0640`, directories
to `2750`: owner writes, shared group reads/traverses, others have no access.
Container isolation alone does not enforce these identities. The separate
consumer must have a different non-root UID; it may share the reader group.
Do not run the producer or remote reader as root when testing permission denial.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests construct tiny invented FASTQs in temporary directories; they do not
store a saved sequencing dataset in this repository. Deployment owns the
Docker/SSH integration tests and reusable saved fixture.

## Layout references and limits

The NextSeq 1000/2000 local run directory and analysis hierarchy are based on
[Illumina's file-path reference](https://knowledge.illumina.com/instrumentation/nextseq-1000-2000/instrumentation-nextseq-1000-2000-reference_material-list/000002443).
The instrument's configured output destination may differ from its local run
directory. See also [DRAGEN output structure](https://support-docs.illumina.com/IN/NextSeq10002000/Content/IN/NextSeq2000_1000/DRAGEN_SequencingOutputStructure.htm).
This is a reduced processed-FASTQ profile, not complete vendor output emulation.
Nanopore is a future profile. Repository context is in `CONTEXT.md`; the design
decision is in `docs/adr/0001-saved-run-replay.md`. The wiki product index links
their reading surfaces separately.
