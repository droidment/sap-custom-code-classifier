# Step 07: Stage 2a/2b: evidence scoring, propagation, batches

> This is step 07 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/evidence.py`, `tools/prep_batches.py` and `tools/pending.py` as specified in sections 8.1 and 8.2, and un-skip `test_02_evidence`. The scoring subtleties (deepest-node-once-per-module, propagation thresholds, per-system batch ids) are the parts most often got wrong; implement them literally.

## Specification

### 8.1 `tools/evidence.py` -> `work/evidence.jsonl`
Extraction on comment-free upper-cased lines (regexes):
`FROM <t>`, `JOIN <t>`, `UPDATE <t>` (not SCREEN/TABLE), `MODIFY <t>` (not TABLE/SCREEN/LINE/CURRENT),
`DELETE FROM <t>`, `INSERT [INTO] <t> FROM|VALUES|CLIENT`, `TABLES: a, b.` -> tables;
`TYPE|LIKE [TABLE OF|LINE OF|RANGE OF] <t>` -> types; `REF TO <c>`, `<c>=>`, `CREATE OBJECT x TYPE <c>`,
`NEW <c>(`, `INHERITING FROM <c>`, `INTERFACES <i>` -> classes (IF_EX_* also -> badis without the prefix;
IF_WORKFLOW/BI_OBJECT/BI_PERSISTENT -> flag WORKFLOW_OBJECT; /IWBEP/ or /IWFND/ -> flag GATEWAY);
`CALL FUNCTION '<f>'` -> functions (+ flag RFC_CALL when DESTINATION / STARTING NEW TASK / IN BACKGROUND TASK);
`INCLUDE <i>.`, `SUBMIT <p>` -> includes/submits; `CALL TRANSACTION '<t>'`, `LEAVE TO TRANSACTION` -> tcodes;
`MESSAGE-ID x`, `MESSAGE ID 'x'`, `MESSAGE e001(x)` -> msgclasses; `INFOTYPES: 0001, 2001` and
`TYPE P0001` -> infotypes; `NODES pernr`, `GET PERNR|PAYROLL|OBJEC|PERAS|GROUP` -> ldb_nodes (PERNR->PNP,
PAYROLL/PERAS/GROUP->PNPCE, OBJEC->PCH); `rp_provide_from_last` etc. -> flag HR_MACRO;
`AUTHORITY-CHECK OBJECT 'x'` -> authobjs; `ENHANCEMENT-POINT x SPOTS s`, `ENHANCEMENT n x` -> badis/
enhancements; `GET BADI x TYPE t`. Ignore variable-looking tokens (LT_, LS_, LV_, GT_, IT_, ET_, CT_, WA_,
`<fs>`), ABAP built-in types and SY-fields. Also take refs from the inventory xml (SPOT_NAME, BADI_DEF,
EXIT_NAME -> badis; PROGRAM/PGMNA/INCLUDE -> includes; CLSNAME/IMPL_CLASS/SUPERCLASS -> classes; TABNAME/
CHECKTABLE/ROLLNAME -> types; LDBNAME -> ldb; TABL field checktables/rollnames -> types; xml_tokens).

Scoring: a rule index maps each kind to exact values and prefixes (longest prefix first). For every
extracted value try the kinds in order (tables -> table; types -> table then type_ref, with table hits
re-labelled type_ref; functions -> function; classes -> class then badi; includes/submits -> include;
tcodes; msgclasses; authobjs; badis/enhancements -> badi; ldb; xml_tokens -> table/function/class/badi at
0.6 weight). PA####/PB####/P#### names also fire infotype rules. Signal weight =
`weights[kind] * rule.weight * diminishing(count)` with diminishing = `min(2.0, 1 + 0.25*(count-1))`.
**Within one module, credit only the deepest node of an ancestor chain and split the weight between
sibling nodes** (so EKKO listed on MM-PUR and both its areas counts once toward MM). Also: object
`name_prefix` (first matching prefix; FM names at 0.5), `package_keyword` (whole word in package name/desc),
`keyword` (substring of lower-cased description + package desc + header comments + FM texts, count-scaled),
`object_type`.

Aggregation: effective score of a node = own + all descendants. Module = top-level (not UNKNOWN) with the
highest effective score; submodule = child with effective >= max(2, sub_level_share * parent) and lead >= 1
over siblings; area likewise under the submodule.

Dependency graph (same system only): object A uses B when a table/type/class/include/submit name of A is a
custom object name, or a called FM belongs to a custom FUGR. Propagation (`propagation_passes` times): for an
object whose own module-level max < auto_min_score, add Σ over neighbours (users × factor_users, uses ×
factor_uses) of the neighbour's module vector scaled so its max is at most `propagation_cap`. Record
`propagated_from`.

Decision: `auto` if best >= auto_min_score and best-second >= auto_min_margin (for propagation-only objects
use propagated_auto_min_score/margin, and flag `via_propagation`); else `needs_llm`. Confidence =
min(0.95, 0.45 + 0.03*best + 0.02*margin), -0.08 without submodule, -0.1 if propagated, floor 0.05.
Row: `{key, decision, module, submodule, area, confidence, top[(node,score)x3], margin, via_propagation,
propagated_from, signals[<=40 {kind,value,node,weight,count}], refs{kind:{value:count}}, rfc_call, uses[],
used_by[]}`. Summary `EVIDENCE_OK objects= auto= needs_llm= modules: ...`.

### 8.2 `tools/prep_batches.py`
Writes `work/auto.json` `{"count", "records":[{key, module, submodule, area, confidence, source:
"heuristic"|"heuristic+propagation", purpose: description, rationale: top signals, flags:[]}]}` and
`work/batches/NNN.json` (sorted by system, package, type, name; `batch_size` objects each):
`{"batch_id","taxonomy":[{id,name,parent}],"objects":[{key, system, type, name, package, package_desc,
description, loc, children[{name,description}], heuristic_top, heuristic_pick{module,submodule,area},
evidence[<=15 "kind:value->node"], refs{tables,functions,classes,tcodes,badis,includes,authobjs}, uses_custom,
used_by_custom, excerpt}]}`. Excerpt per source file: file name, up to 15 header comments, the first 25
code lines and every line matching SELECT/FROM/JOIN/UPDATE/MODIFY/INSERT/DELETE/CALL FUNCTION/CALL METHOD/
CALL TRANSACTION/SUBMIT/INFOTYPES/TABLES/INCLUDE/MESSAGE/AUTHORITY-CHECK/ENHANCEMENT/INTERFACES/INHERITING/
CREATE OBJECT/REPORT/FUNCTION/CLASS ... DEFINITION/METHODS/FORM/GET PERNR/NODES/PARAMETERS/SELECT-OPTIONS/
RAISE/GET BADI/OPEN DATASET/`CL_x=>`/`NEW x(`, capped by excerpt_max_lines/chars. Batches are numbered PER SYSTEM: `<SYS>-001`, `<SYS>-002`, ... (keys grouped by system, each group sorted
by package, type, name), so adding a system later never renumbers existing batches. Skip batches that
already have `work/llm/<id>.json` (unless `--force`). Options `--limit N`, `--min-confidence X` (re-batch
objects below X from classification.json, ids prefixed `R`), `--only-module M`, `--only-system SYS`. Summary `PREP_OK needs_llm=
batches_total= batches_written= batches_done= batch_dir= llm_dir=`.
`tools/pending.py` prints `PENDING total= done= batches_per_run=`, `THIS_RUN <ids or none>`,
`REMAINING_AFTER_THIS_RUN n`.

## Acceptance check

`py -I tools/evidence.py --config tools/tests/fixtures/migration.config.json` prints `EVIDENCE_OK` with auto >= 8 and needs_llm <= 3 on the fixtures, and test_02 passes: HR report -> HCM / HCM-PT / HCM-PT-TS auto; Z table and helper class -> HCM via propagation; PO class -> MM / MM-PUR; FI report -> FI; doc helper -> needs_llm. `prep_batches.py` writes batches named `SYSA-001` style with excerpts; `pending.py` prints the THIS_RUN line.
