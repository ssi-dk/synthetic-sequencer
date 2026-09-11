# Agent Guidance

This repository is public-safe. Read CONTEXT.md, docs/agents/*.md, and relevant
docs/adr/ before changes. Keep saved datasets, credentials, environment paths,
and private deployment details in the private deploy repository.

Run tests with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
Do not change FASTQ bytes during replay. Preserve atomic publication and
separate producer/reader identities. Agents perform local development only;
never connect to or execute on servers. Server work is `[USER — SERVER]` and
verification evidence is `[USER — RELAY]`.

Read docs/HARDLINKS.md before adding mirrored documentation.

## Shared workflow

Before routing work, read [Shared Repository Workflow](docs/agents/shared-workflow.md)
for preferences, wiki/GitHub tracking, authorship, and execution boundaries.
Read [repository tracker settings](docs/agents/issue-tracker.md) for local mappings.
The shared file is wiki-owned and hardlinked here; see [the link contract](docs/HARDLINKS.md).
