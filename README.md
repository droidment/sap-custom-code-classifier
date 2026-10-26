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
   contains the package folders; for an abapGit repo that is usually `<repo>/src`). If a system was exported
   as chained text chunks (`ZDEV/z1_0001.abapchunk`, `z1_0002.abapchunk`, ...) add `"format": "chunks"`;
   `/unchunk` rebuilds it into abapGit-style files under `work/unchunked/` before `/inventory`
   (see "Chunked exports" below).
4. Optional: `tools/taxonomy/rules_custom.json` with your own Z-tables and naming conventions (see the
   `sap-module-taxonomy` skill in `.opencode/skills/`).
5. Smoke test without any LLM: `py tools/tests/test_pipeline.py` (runs on synthetic fixtures).

## Running
Start `opencode` in this folder and stay in your normal (build) agent. The project commands run as subagents
(`subtask: true` in `.opencode/commands/*.md`): script output and LLM work stay in the subagent's context and
only its final report comes back to your conversation. `/unchunk`, `/review` and `/target-packages` run directly
as `abap-splitter`, `abap-reviewer` and `abap-architect`; `/inventory`, `/explorer`, `/tree`, `/status` and
`/inspect-chunks` run as the `sap-migration` orchestrator subagent. The one exception is `/classify`: it runs in
your current agent and launches one `abap-classifier` subagent per batch from there, because a subagent may not
launch further subagents on older OpenCode versions (the `subagent_depth` setting only exists from 1.18.5 on).
Its own output in your conversation is just the three script summary lines and the batch reports.

| Command | What it does | Output |
|---|---|---|
| `/inspect-chunks SYS PKG` | chunked exports: show chunk files, gaps and the detected object marker | |
| `/unchunk` | chunked exports: rebuild objects into `work/unchunked/<SYS>/`, name leftovers with the LLM | `work/unchunked/` |
| `/inventory` | walk the exports | `work/inventory.jsonl` |
| `/classify` | score evidence, classify pending batches with the LLM (parallel), merge, overlaps. Re-run until `0 pending`. | `work/classification.json`, `work/overlaps.json` |
| `/classify --limit 1` | smoke test with one LLM batch | |
| `/classify --min-confidence 0.6` | re-run weak objects (new batch ids `R001...`) | |
| `/review` | consistency review (Sol) and apply corrections | `work/review.md`, classification updated |
| `/explorer` | **first deliverable**: single offline HTML file | `output/explorer.html` |
| `/tree` | Markdown tree + CSV for Excel + data copy | `output/tree.md`, `output/objects.csv` |
| `/target-packages` | proposed S/4 package hierarchy and move list (Sol) | `output/target_packages.md`, `output/object_moves.csv` |
| `/status` | where things stand, what to run next | |

Suggested order for the management report: (`/unchunk` for chunked systems) -> `/inventory` -> `/classify`
(loop) -> `/review` -> `/explorer`.

### Chunked exports
`tools/unchunk.py` concatenates each package's chunks in numeric order (warns on gaps), auto-detects the
marker line that starts each object (or uses `object_marker` from the config: a regex with named groups
`type` (optional) and `name`), rebuilds programs, classes, interfaces and function groups (FUNCTION blocks
attach to the preceding FUNCTION-POOL, otherwise to a synthetic group flagged `synthetic_fugr`), takes the
description from the first header comment, and writes `_manifest.jsonl`. Segments it cannot name are listed
in `work/unchunk_unresolved.json`; `/unchunk` hands those to the `abap-splitter` subagent and applies its
answers. Re-runs only rebuild packages whose chunk files changed.
Later: `/tree`, `/target-packages`.

### One system at a time
You can run the whole chain for one company first and add the others later; nothing has to be redone.
Put only that system in `migration.config.json` (or keep all and use `/classify --only-system S1D`), run
`/inventory`, `/classify` until 0 pending, `/review`, then `/explorer --systems S1D` for its own
`output/explorer_S1D.html` (and `/tree --systems S1D` for `tree_S1D.md` / `objects_S1D.csv`). When you add
the next system, `/inventory` and `/classify` extend the existing state: object keys carry the system id and
LLM batches are numbered per system (`S1D-001`, `S2D-001`, ...), so earlier results are kept and only the new
objects go to the LLM. Overlaps between systems appear once two or more systems are in the config, and the
unfiltered `/explorer` then shows them.

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
| orchestrator, `/classify` batches (`abap-classifier`), `abap-splitter` | `azure/az-gpt-5.6-terra` |
| `/review` (`abap-reviewer`), `/target-packages` (`abap-architect`) | `azure/az-gpt-5.6-sol` |
| `/inventory`, `/explorer`, `/tree`, `/status` summaries, `small_model` | `azure/az-gpt-5.6-luna` |

Change them in the `model:` line of `.opencode/agents/*.md` / `.opencode/commands/*.md` or in `opencode.json`.
The ids assume the Azure OpenAI provider is registered in OpenCode as `azure`; if yours uses another provider
id, replace the `azure/` prefix in those files (the deployment names `az-gpt-5.6-*` stay).
For a cheaper first pass set the classifier to Luna; for a final pass on weak objects set it to Sol and run
`/classify --min-confidence 0.6`.

## Business process view
Besides the SAP module, every object gets business-process assignments in the style of SAP's Reference
Business Architecture (process group > process module, e.g. Source to Pay > Procure to Receive). The catalog in
`tools/taxonomy/processes.json` is a local alias set written for this project, not an SAP publication; replace
it with the official snapshot when you have one and keep the ids stable. Most assignments come from the
module-to-process crosswalk (`tools/taxonomy/crosswalk.json`, basis `crosswalk`) at no LLM cost; the classifier
sets `process` explicitly only when an object belongs to a different process than its module implies or serves
several (basis `llm`), and the reviewer can override (basis `review`). Each assignment has a role: direct,
supporting or context. The explorer can group by process, the CSV has process columns and `tree.md` has a
process section. Packages for the S/4 target stay organised by module; the process view is for comparing
capabilities across the companies.

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
.opencode/agents/     sap-migration (orchestrator subagent), abap-splitter, abap-classifier, abap-reviewer, abap-architect
.opencode/commands/   inspect-chunks, unchunk, inventory, classify, review, explorer, tree, target-packages, status
.opencode/skills/     sap-module-taxonomy, abapgit-layout, classification-rules
tools/                unchunk, inventory, evidence, prep_batches, merge, overlaps, review_candidates,
                      render_html, render_tree, target_skeleton, status, pending, common
tools/taxonomy/       nodes.json, rules_*.json (add rules_custom.json), processes.json, crosswalk.json
tools/tests/          make_fixtures.py, test_pipeline.py, fixtures/
work/  output/        generated (git-ignored)
```
