# Implementation tracking

Issue: [Implement NextSeq FASTQ saved-run replay CLI and Docker image](https://github.com/ssi-dk/synthetic-sequencer/issues/1).

Implement a reusable Python CLI and Docker image that validate a saved NextSeq
1000/2000 template and replay its processed FASTQs into unique run folders.
Assign unique sample identities, update matching sample sheets and filenames,
retain FASTQ bytes, omit BCL/CBCL data, and publish completed runs atomically.

Acceptance: test consistent sample mapping, byte preservation, paired reads,
failed/interrupted copies, concurrent invocation, and explicit template errors.
Keep the image independent of saved datasets and deployment configuration.
Nanopore remains a future profile.

Local implementation and tests are available. The issue is associated with
[ResearchIT TODO](https://github.com/orgs/ssi-dk/projects/16). Source changes have
not been committed or pushed, and no image has been published to a registry.
Link the private deployment issue once its repository remote is established.

The implementation also includes config-driven run_interval_seconds and
max_runs, a Docker scheduler, and immediate manual replay without changing the
schedule. Oldest completed runs are pruned only after successful publication.
Cadence, manual replay, and retention have unit and local container coverage.
