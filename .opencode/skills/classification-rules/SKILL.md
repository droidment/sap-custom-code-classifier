---
name: classification-rules
description: How an object's module is decided (heuristic scoring, propagation, auto vs needs_llm thresholds), the JSON contract for LLM and review results, and how to re-run or tune. Load when explaining a classification, tuning thresholds, or when merge reports validation errors.
---
# Classification rules

## Pipeline
1. `inventory.py` lists objects.  2. `evidence.py` extracts references from the ABAP (tables in
SELECT/UPDATE/MODIFY/INSERT/DELETE/TABLES/TYPE, CALL FUNCTION, class refs, INCLUDE/SUBMIT, CALL TRANSACTION,
MESSAGE classes, INFOTYPES/Pnnnn, logical DB nodes, AUTHORITY-CHECK objects, enhancement spots/BAdIs) plus
xml metadata, scores them with `tools/taxonomy/rules_*.json`, propagates scores along the custom
dependency graph (Z-tables and helpers inherit from their callers) and decides `auto` or `needs_llm`.
3. `prep_batches.py` writes `work/auto.json` and `work/batches/NNN.json`.  4. `abap-classifier` writes
`work/llm/NNN.json` per batch.  5. `merge.py` validates and merges into `work/classification.json`.
6. `overlaps.py` compares systems.  7. `review_candidates.py` + `abap-reviewer` + `merge.py --apply-review`.

## Scoring
- Each matched signal adds `weights[kind] * rule.weight * diminishing(count)` to the rule's node
  (weights in `nodes.json`: table 5, function 5, badi 6, ldb 6, infotype 5, tcode 3, keyword 1.5, ...).
- A value listed on a node and its children counts once per module (deepest node wins, siblings split).
- Node score rolls up to ancestors. Module = top-level with the highest total; submodule/area are chosen
  when a child holds >= `sub_level_share` (30%) of the parent and leads its siblings by >= 1.
- `auto` when module total >= `auto_min_score` (6) and margin to the runner-up >= `auto_min_margin` (3).
  Objects whose evidence is only propagated use `propagated_auto_min_score` (3.5) / `_margin` (2).
- Everything else is `needs_llm`. Thresholds live in `migration.config.json` -> `classification`.

## LLM / review record contract (validated by merge.py)
```json
{"key": "SYSA|CLAS|ZCL_X", "module": "MM", "submodule": "MM-PUR", "area": "MM-PUR-PO",
 "confidence": 0.85, "purpose": "one business sentence", "rationale": "evidence", "flags": ["interface"]}
```
- `key` must exist in the inventory; ids must be taxonomy nodes forming a valid chain (merge repairs the
  chain from the deepest valid id); confidence 0..1; purpose non-empty.
- Invalid records are listed in `work/merge_report.md`; the object stays `source: missing` and is picked up
  again by the next `/classify` (prep skips only batches that have a result file; delete
  `work/llm/<batch>.json` to force a redo).
- Later result files override earlier ones for the same key (by file time); review patches override all.

## Fields aligned with a later analysis database
Every object in `work/classification.json` also carries:
- `secondary`: further assignments `[{module, submodule, area, role: supporting|context, rationale}]`; the
  primary assignment is implicitly role `direct`. Set by the classifier or the reviewer.
- `outcome` (triage status, derived by merge): `classified`, `needs_context` (UNKNOWN or needs-human),
  `shared_technical` (BC/CA with flag utility or cross-module), `extraction_failed` (inventory found no
  source and no xml), `pending` (no result yet).
- `review_state`: `proposed` (default), `reviewed` or `rejected`, plus `reviewed_by`; only the review patch
  sets these. Confidence is a model estimate; review_state is a decision. They are separate on purpose.
- `provenance`: `{source, model, batch, prompt_version, taxonomy_version, generated}`. Bump
  `PROMPT_VERSION` in `tools/merge.py` and `prompt_version` in the classifier agent when the prompt changes;
  `taxonomy_version` comes from `tools/taxonomy/nodes.json`.
All of them appear as CSV columns and in the explorer (outcome and review-state filters).

## Re-running and tuning
- `/classify --limit 1`: smoke test on one batch.  `/classify --min-confidence 0.6`: re-batch weak objects
  (batch ids `R001...`).  `/classify --only-module UNKNOWN`: only the undecided.
- Changing rules: auto results are recomputed on every run; LLM results persist.
- Too many `needs_llm`? Add your Z-tables and naming conventions to `rules_custom.json` and lower
  `auto_min_score` to 5. Too many wrong autos? Raise `auto_min_margin`.
- Large systems: set `batches_per_run` so one `/classify` fits your session; run it in a loop.
