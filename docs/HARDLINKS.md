# Documentation Hardlinks

This manifest declares repo-owned documentation exposed in the private wiki.
The repository remains canonical; mirrored files must share inodes with their
sources. Git does not preserve hardlinks; recreate them after a fresh checkout.
Read the workspace wiki/99_Meta/Documentation Hardlinks.md before adding or replacing
mirrors. Reconcile differing target content before replacing it.

Wiki reference root: `wiki/20_Products/Synthetic Sequencer/Reference`.

| Repo path | Wiki path | Required |
| --- | --- | --- |
| `README.md` | `wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-README.md` | yes |
| `CONTEXT.md` | `wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-CONTEXT.md` | if present |
| `CHANGELOG.md` | `wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-CHANGELOG.md` | if present |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, `GOVERNANCE.md` | `wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-<filename>` | if present |
| `docs/**/*.md` except `docs/agents/**` | `wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-docs/` (preserve hierarchy) | if present |

Exclude AGENTS.md, PLAN.md, docs/agents/, configuration, saved sequencing data,
credentials, and generated runtime output. This manifest is itself mirrored.
Product-level notes remain wiki-owned synthesis and navigation.

## Incoming shared agent guidance

Canonical owner: team wiki. This is an incoming public-safe policy file, not
an outgoing product documentation mirror. Keep it out of product Reference folders.

| Wiki source (workspace-relative) | Repo destination | Required |
| --- | --- | --- |
| `wiki/99_Meta/Agents/Shared/repository-workflow.md` | `docs/agents/shared-workflow.md` | yes |

Commit the destination as ordinary Markdown so standalone clones retain it.
Git does not preserve hardlinks. Reconcile any content differences before
relinking; verify matching device and inode. The wiki source owns shared edits.
Setup and restoration: `wiki/99_Meta/Agents/Shared Agent Hardlinks.md`.
