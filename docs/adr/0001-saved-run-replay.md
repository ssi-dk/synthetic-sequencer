# ADR 0001: Replay processed NextSeq data

Status: accepted, 2026-09-11.

## Context

Downstream transfer tests need distinct runs and samples, realistic folder
boundaries, and source permissions. Full sequencing simulation is unnecessary.

## Decision

Replay an immutable saved template using unique run and sample identities.
Retain FASTQ bytes, updating only filenames and sample sheets. Initially accept
NextSeq 1000/2000 analysis 1 with paired gzip FASTQs. Exclude raw base calls and
diagnostics. Stage outside the output root and publish by same-filesystem rename.
Use a shared work-root lock to prevent overlapping runs. Add no pretend vendor
completion markers. Keep vendor-specific extensions explicit.

## Consequences

Transfer correctness can be checked against unchanged payload checksums.
Read headers still identify the saved template. Consumers see completed runs;
observing a real instrument's partial writes or completion flags is outside this
profile. Deployment supplies data and independent producer/reader permissions.
Nanopore can be added as a separate profile without changing this ownership.

## Cadence and retention amendment — 2026-09-11

The user requested config-driven automatic cadence and a maximum run count.
The app now exposes a schedule operation; the deploy config supplies the interval
and cap. Local setup enables the Docker scheduler (hourly, ten retained runs).
Host cron remains untouched. Immediate manual replay does not reset the timer.
After successful publication, remove oldest recognized completed runs under the
replay lock. Keep the new run and report any pruning failure. This supersedes
the initial absence of automatic retention and the disabled-scheduling default.
