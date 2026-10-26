# SAP custom-code classification project - rules for agents

Purpose: classify the custom ABAP of three ECC 6.0 company systems by SAP module / submodule / area,
find overlaps between the systems, and propose the target package design for the S/4HANA merge.

## Hard rules
- The abapGit exports under the `root` paths in `migration.config.json` are READ-ONLY. Never write there.
- Write only under `work/` (intermediate, resumable state) and `output/` (deliverables).
- Python is invoked as `py` (Windows launcher), never `python3`. Standard library only; no pip installs.
- Deterministic steps are Python scripts in `tools/`. Run them; do not re-implement their logic in prose.
  Each prints one machine-readable summary line (`INVENTORY_OK ...`, `EVIDENCE_OK ...`, `PREP_OK ...`,
  `MERGE_OK ...`, `OVERLAPS_OK ...`, `EXPLORER_OK ...`, `TREE_OK ...`, `TARGET_OK ...`).
- LLM work happens only in the subagents (`abap-splitter`, `abap-classifier`, `abap-reviewer`, `abap-architect`)
  and only on the prepared files (`work/unchunk_unresolved.json`, `work/batches/*.json`,
  `work/review_candidates.json`, `work/target_draft.json`).
- Systems exported as chained `.abapchunk` files (`"format": "chunks"`) must be rebuilt with `/unchunk`
  before `/inventory`. The raw chunk folders are read-only like any other root.
  Never classify objects ad hoc in the main conversation.
- Taxonomy ids (`tools/taxonomy/nodes.json`) are the contract between all stages. Do not invent ids.
  Company-specific rules go in `tools/taxonomy/rules_custom.json`, never in the shipped rule files.
- Process at most `classification.batches_per_run` batches per `/classify`; report the remainder.
- Every `/command` runs as a subagent (`subtask: true`); the user only sees its final message, so the command's
  report must be complete. `/classify` fans out to `abap-classifier` subagents and relies on `subagent_depth: 2`.
- Do not load `work/classification.json` or whole source folders into the conversation. Use
  `py tools/status.py` or a short Python one-liner for numbers.

## Where things are
| Path | What |
|---|---|
| `migration.config.json` | system roots (+ `format: abapgit|chunks` per system), thresholds, batch sizes |
| `work/unchunked/<SYS>/` | abapGit-style rebuild of a chunked export (`tools/unchunk.py`, `/unchunk`); the pipeline reads it instead of the raw chunks |
| `work/unchunk_unresolved.json`, `work/unchunk_resolution.json` | segments the chunk parser could not name; the `abap-splitter` subagent resolves them |
| `tools/taxonomy/` | `nodes.json` + `rules_*.json` (+ optional `rules_custom.json`); `processes.json` (local business-process catalog) + `crosswalk.json` (module -> process defaults) |
| `work/inventory.jsonl` | one record per object |
| `work/evidence.jsonl` | signals, scores, heuristic decision, dependency edges |
| `work/auto.json`, `work/batches/`, `work/llm/` | heuristic results, LLM input batches, LLM results |
| `work/classification.json` | merged classification (source of truth for all outputs) |
| `work/overlaps.json` | identical / diverged / similar objects across systems |
| `work/review_candidates.json`, `work/review_patch.json`, `work/review.md` | review stage |
| `output/explorer.html` | self-contained HTML explorer (management deliverable) |
| `output/tree.md`, `output/objects.csv`, `output/classification.json` | tree, Excel-friendly CSV, data copy |
| `output/target_packages.md`, `output/object_moves.csv` | proposed S/4 package design and move list |

## Models
Default (orchestrator, classifier batches): `azure/az-gpt-5.6-terra`. One-shot judgment stages
(`abap-reviewer`, `abap-architect`): `azure/az-gpt-5.6-sol`. Trivial summaries and `small_model`:
`azure/az-gpt-5.6-luna`. Change them in the agent frontmatter under `.opencode/agents/` or in `opencode.json`.

## Resuming after an interruption
Every stage is idempotent. Re-run the same command. `/classify` skips batches that already have a result
file in `work/llm/`. To redo one batch, delete its `work/llm/<id>.json`. To redo everything from scratch,
delete `work/`.
