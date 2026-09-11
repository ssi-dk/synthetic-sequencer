# Documentation Hardlinks

This manifest declares repo-owned documentation exposed in the private wiki.
The repository remains canonical; mirrored files must share inodes with their
sources. Git does not preserve hardlinks; recreate them after a fresh checkout.
Read the workspace docs/documentation-hardlinks.md before adding or replacing
mirrors. Reconcile differing target content before replacing it.

Wiki reference root: `Wiki/20_Products/Synthetic Sequencer/Reference`.

| Repo path | Wiki path | Required |
| --- | --- | --- |
| `README.md` | `Wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-README.md` | yes |
| `CONTEXT.md` | `Wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-CONTEXT.md` | if present |
| `CHANGELOG.md` | `Wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-CHANGELOG.md` | if present |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, `GOVERNANCE.md` | `Wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-<filename>` | if present |
| `docs/**/*.md` except `docs/agents/**` | `Wiki/20_Products/Synthetic Sequencer/Reference/apps-synthetic-sequencer-docs/` (preserve hierarchy) | if present |

Exclude AGENTS.md, PLAN.md, docs/agents/, configuration, saved sequencing data,
credentials, and generated runtime output. This manifest is itself mirrored.
Product-level notes remain wiki-owned synthesis and navigation.
