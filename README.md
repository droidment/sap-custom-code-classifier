# SAP custom code classifier (ECC 6.0 -> S/4HANA merge)

An OpenCode project that takes the abapGit exports of three company systems, works out which SAP
module / submodule / area every custom object belongs to, finds overlaps between the systems, and
produces: an HTML explorer for management, a Markdown tree + CSV, and a proposed S/4HANA target
package design.

Deterministic work (parsing, evidence scoring, dependency propagation, rendering) is Python, standard
library only. The LLM is used only for the objects the heuristics cannot settle, in resumable batches.

## Setup (once, on the machine that has the exports)
1. Install Python 3.11+ (invoked as `py`) and OpenCode. Configure the OpenAI provider in OpenCode.
2. Copy this folder next to the exports (anywhere; the config holds the paths).
3. Edit `migration.config.json`: one entry per system with `id`, `company` and `root` (the folder that
   contains the package folders; for an abapGit repo that is usually `<repo>/src`).
4. Optional: `tools/taxonomy/rules_custom.json` with your own Z-tables and naming conventions (see the
   `sap-module-taxonomy` skill in `.opencode/skills/`).
5. Smoke test without any LLM: `py tools/tests/test_pipeline.py` (runs on synthetic fixtures).

## Running
Start `opencode` in this folder (the `sap-migration` agent is the primary agent), then:

| Command | What it does | Output |
|---|---|---|
| `/inventory` | walk the exports | `work/inventory.jsonl` |
| `/classify` | score evidence, classify pending batches with the LLM (parallel), merge, overlaps. Re-run until `0 pending`. | `work/classification.json`, `work/overlaps.json` |
| `/classify --limit 1` | smoke test with one LLM batch | |
| `/classify --min-confidence 0.6` | re-run weak objects (new batch ids `R001...`) | |
| `/review` | consistency review (Sol) and apply corrections | `work/review.md`, classification updated |
| `/explorer` | **first deliverable**: single offline HTML file | `output/explorer.html` |
| `/tree` | Markdown tree + CSV for Excel + data copy | `output/tree.md`, `output/objects.csv` |
| `/target-packages` | proposed S/4 package hierarchy and move list (Sol) | `output/target_packages.md`, `output/object_moves.csv` |
| `/status` | where things stand, what to run next | |

Suggested order for the management report: `/inventory` -> `/classify` (loop) -> `/review` -> `/explorer`.
Later: `/tree`, `/target-packages`.

### Memory and time on large systems
- `classification.batch_size` (default 20 objects) and `batches_per_run` (default 10) in
  `migration.config.json` bound one `/classify` invocation. With 10 x 20 objects per run and ~15k objects
  needing the LLM, that is ~75 runs; just re-run `/classify` (or loop it) - it continues where it stopped.
- Scripts stream JSONL and never hold source text for all objects at once. `evidence.py` on ~20k objects
  takes a few minutes.
- All runs are idempotent. To redo one batch delete `work/llm/<id>.json`; to start over delete `work/`.

### Models
| Where | Model |
|---|---|
| orchestrator, `/classify` batches (`abap-classifier`) | `openai/gpt-5.6-terra` |
| `/review` (`abap-reviewer`), `/target-packages` (`abap-architect`) | `openai/gpt-5.6-sol` |
| `/inventory`, `/explorer`, `/tree`, `/status` summaries, `small_model` | `openai/gpt-5.6-luna` |

Change them in the `model:` line of `.opencode/agents/*.md` / `.opencode/commands/*.md` or in `opencode.json`.
For a cheaper first pass set the classifier to Luna; for a final pass on weak objects set it to Sol and run
`/classify --min-confidence 0.6`.

## How classification works (short)
`tools/evidence.py` extracts tables, function calls, class references, includes, transactions, message
classes, infotypes, logical databases, authorization objects and enhancement targets from each object,
scores them against `tools/taxonomy/rules_*.json`, lets Z-tables and helpers inherit scores from the
objects that use them, and marks an object `auto` when one module clearly wins. Everything else goes to
the LLM with a compact evidence summary and source excerpt. `tools/merge.py` validates every LLM record
against the taxonomy. Details: `.opencode/skills/classification-rules/SKILL.md`.

## Layout
```
opencode.json  AGENTS.md  migration.config.json
.opencode/agents/     sap-migration (primary), abap-classifier, abap-reviewer, abap-architect
.opencode/commands/   inventory, classify, review, explorer, tree, target-packages, status
.opencode/skills/     sap-module-taxonomy, abapgit-layout, classification-rules
tools/                inventory, evidence, prep_batches, merge, overlaps, review_candidates,
                      render_html, render_tree, target_skeleton, status, pending, common
tools/taxonomy/       nodes.json, rules_*.json  (add rules_custom.json)
tools/tests/          make_fixtures.py, test_pipeline.py, fixtures/
work/  output/        generated (git-ignored)
```
