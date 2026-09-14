# Synthetic Sequencer Context

- **Saved Run Template:** Read-only processed FASTQs and sample sheets used for replay.
- **Replay:** A byte-preserving copy of the template's FASTQs under new run and sample identities.
- **Run Root:** Consumer-visible directories, published only after replay completes.
- **Work Root:** Private staging, lock, and sequence counter; shares a filesystem with the run root.
- **Profile:** A supported vendor-style output layout; initially NextSeq 1000/2000 analysis 1.
- **Producer:** Non-root process that owns and writes run data.
- **Reader:** Separate consumer identity with read-only source access.

This public app owns CLI behavior, the producer Docker image, unit tests, and
portable documentation. Private deploy repositories own saved datasets,
environment-specific configuration, credentials, schedules, endpoints, and
integration orchestration. Shared automation invokes a deploy-owned adapter.

Version one replays paired FASTQs; it does not generate biology or raw signals.
FASTQ contents, including embedded read identifiers, remain unchanged.
Nanopore support is deferred. Follow docs/adr/0001-saved-run-replay.md.

Scheduling uses a configured positive interval in seconds. Manual replay stays
available independently of that timer. An optional positive max_runs cap removes
the oldest recognized completed simulator runs only after successful publication.
The local deployment enables an hourly Docker scheduler and a ten-run cap.

Every machine supplies its output_root and separate work_root in config. The
scheduler atomically updates output_root/heartbeat.json, including while copying.
Liveness and last successful publication are separate UTC timestamps. Manual
and scheduled publications persist last-success state in the private work root.
