# Step 09: Stage 4/5: explorer, tree, CSV, target packages, status

> This is step 09 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/render_html.py`, `tools/render_tree.py`, `tools/target_skeleton.py` and `tools/status.py` as specified in section 10, and un-skip the rest of `test_03`. The explorer is one offline HTML file with no external resources.

## Specification

## 10. Outputs

- `tools/render_html.py` -> `output/explorer.html`: one file, no CDN, data embedded in
  `<script type="application/json">` (escape `</` as `<\/`). Header with summary cards (objects, systems,
  packages, modules, auto/heuristic, LLM, low confidence, unclassified, identical/diverged across systems,
  objects per system); filters: search (name, description, purpose, package, tables, FMs), system, type,
  module, confidence band (>=0.8 / 0.6-0.8 / <0.6), overlap (identical/diverged/similar/none), source;
  expand/collapse all; theme toggle plus `prefers-color-scheme`. Tree of `<details>`: Module › Submodule ›
  Area › table of objects (type, name + FM count chip + overlap chip, purpose, system chip + package,
  confidence coloured + source). Clicking a row toggles a detail block: classification chain, description,
  package, rationale, flags, heuristic candidates (mark when they differ), evidence, tables, function calls,
  FMs, uses / used by, overlap info, files. Phone width: 16px gutters, hide one column. Option
  `--systems S1D,S2D` restricts to those systems and writes `explorer_S1D_S2D.html`. Summary
  `EXPLORER_OK objects= file= size_kb=`.
- `tools/render_tree.py` -> `output/tree.md` (`## MODULE - name (n)`, `- **SUB - name** (n)`, `- *AREA*`,
  object lines `` `TYPE NAME` - purpose | SYS / PKG | conf 0.xx (FMs: n) [identical: A,B] ``),
  `output/objects.csv` (utf-8-sig; columns system, company, package, package_desc, type, name, description,
  module, module_name, submodule, submodule_name, area, area_name, confidence, source, purpose, flags,
  overlap_status, overlap_systems, loc, function_modules, files), copy of classification.json. Option
  `--systems` as for the explorer (suffix `_S1D` on tree and csv, no classification copy). `TREE_OK`.
- `tools/target_skeleton.py [--prefix Z_] [--min-confidence 0.6]` -> `work/target_draft.json`,
  `output/object_moves.csv`, `output/target_packages_draft.md`. Package per taxonomy node in use:
  `Z_HCM`, `Z_HCM_PT`, `Z_HCM_PT_TS` (ids with `-` -> `_`), `Z_UNASSIGNED` for UNKNOWN; parents created
  implicitly; counts per system and type. Move action per object: `triage` (UNKNOWN or confidence below
  threshold), `dedupe` (identical across systems; the first key keeps, others "drop, duplicate of"),
  `resolve` (diverged: rename per system or merge logic), else `move`. `TARGET_OK packages= moves= ...`.
- `tools/evidence.py` input signature: `{files: {inventory: [size, mtime_ns], <each taxonomy/*.json>: [...]},
  classification: <config section>}` saved with the summary line in `work/evidence_sig.json`; when it equals the
  saved one and evidence.jsonl exists, print the saved summary + ` (unchanged, skipped)` and exit 0 (`--force`
  rescored). Test: second run skipped, `--force` not skipped, after a new inventory not skipped.
- `tools/status.py`: roots OK/MISSING (+ unchunk state for chunk systems), inventory counts, evidence
  auto/needs_llm, batches prepared/with results/pending, classification stats, overlaps summary, review patch
  presence, output files with sizes, and a final `NEXT: <command>` line.

## Acceptance check

All four tests pass. Open `tools/tests/_tmp/output/explorer.html` in a browser: no console errors, the module tree and the business-process grouping both render, filters work, clicking a row opens the detail. `--systems SYSA` writes `explorer_SYSA.html` without SYSB objects.
