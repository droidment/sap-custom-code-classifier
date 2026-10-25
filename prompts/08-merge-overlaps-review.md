# Step 08: Stage 2c/2d/3a: merge, overlaps, review candidates

> This is step 08 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/schema.json`, `tools/merge.py`, `tools/overlaps.py` and `tools/review_candidates.py` as specified in sections 8.3, 8.4 and 9, and un-skip the first half of `test_03` (batches, mocked LLM file with one invalid record, merge, review patch, overlaps, review candidates). Rendering comes in step 09.

## Specification

### 8.3 LLM contract (`tools/schema.json`) and `tools/merge.py`
Classifier writes `work/llm/<batch_id>.json`: `{"batch_id","model","prompt_version","results":[{"key","module",
"submodule"|null,"area"|null,"confidence" 0..1,"purpose","rationale","flags":[],
"secondary":[{"module","submodule","area","role": "supporting"|"context","rationale"}]}]}` (secondary optional,
max 5 kept, invalid entries dropped and reported). The review patch may additionally set `review_state`
("reviewed"|"rejected") and `reviewed_by`; merge defaults review records to reviewed / abap-reviewer and keeps
the underlying LLM provenance. merge adds to every object: `outcome` (classified | needs_context for UNKNOWN or
flag needs-human | shared_technical for BC/CA with flag utility or cross-module | extraction_failed when the
inventory found no source and no xml | pending when no result), `review_state` (default proposed),
`reviewed_by`, `provenance {source, model, batch, prompt_version, taxonomy_version (from nodes.json "version"),
generated}`. These appear as CSV columns and explorer filters (outcome, review state) and detail rows. Allowed flags:
cross-module, utility, obsolete-candidate, test-code, mixed-fugr, needs-human, mislabeled-package,
interface, report-only, generated, copy-of-standard, dead-code.
merge: load auto.json, then every llm file sorted by mtime (later wins per key), then with
`--apply-review` the `work/review_patch.json` list (source review). Normalise: deepest valid taxonomy id
wins and the chain is rebuilt from it; reject unknown key / unknown ids / confidence outside 0..1 / empty
purpose (listed in `work/merge_report.md`; object stays source `missing`, module UNKNOWN). Output
`work/classification.json`: `{generated, systems[{id,company}], taxonomy nodes, stats, objects:[{key, system,
company, type, name, package, package_desc, description, loc, children, source_hash, files, module,
submodule, area, confidence, source, model, purpose, rationale, flags, heuristic{module,submodule,area,top,
decision}, evidence[<=12 strings], refs, uses, used_by, rfc_call}]}`. Summary `MERGE_OK objects=
unclassified= llm_valid= llm_invalid= errors= report=`.

### 8.4 `tools/overlaps.py` -> `work/overlaps.json`
`same_name`: same TYPE+NAME in >= 2 systems; `identical` if source hashes equal else `diverged` with
difflib ratio of normalised sources; fields type, name, status, similarity, systems, in_all_systems, keys,
loc per system, packages, modules. `collisions` = diverged. `similar`: pairs from different systems in the
same submodule (skip UNKNOWN/BC, only PROG/CLAS/FUGR/INTF/ENHO/SXCI/DDLS, skip submodules with > 1500
objects) where canonical names (strip a leading `Z<up to 3>_` company prefix) have ratio >= threshold, or
they share >= min_shared_tables standard tables covering >= 60% of the larger set. `index` key -> {status,
systems, similarity, similar_to[]}. Summary `OVERLAPS_OK same_name= identical= diverged= similar_pairs= file=`.

## 9. Stage 3: review

`tools/review_candidates.py` -> `work/review_candidates.json` groups (max 150 each): unknown, low_confidence
(< review.low_confidence), disagree_heuristic (LLM module != heuristic module when heuristic top >= 5),
llm_flags (needs-human/cross-module/mixed-fugr), cross_system_mismatch (same name, different modules),
package_outliers (module differs from the >= 80% dominant module of a package with >= 5 objects, ignoring
BC/CA/UNKNOWN). Each candidate: key, type, name, package, description, module, submodule, area,
confidence, source, purpose, rationale, heuristic, evidence, flags, children. Summary
`REVIEW_CANDIDATES_OK group=count ... file=`. The reviewer agent writes `work/review_patch.json` (list of
corrected records, same shape as 8.3) and `work/review.md`; `merge.py --apply-review` applies.

## Acceptance check

On the fixtures: merge reports `llm_invalid=1`; the classification carries secondary, process (explicit LLM list wins, else crosswalk), outcome, review_state and provenance as asserted in section 12; after `--apply-review` the reviewed object has review_state reviewed and keeps its LLM provenance; overlaps report ZCL_PO_CHECK diverged, ZCL_UTIL_STRING identical, ZHR_TS_REPORT identical across SYSA/SYSC and the A/B timesheet pair as similar.
