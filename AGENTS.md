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
