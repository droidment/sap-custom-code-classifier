# Step 04: Synthetic fixtures and the test harness

> This is step 04 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/tests/make_fixtures.py`, `tools/tests/fixtures/migration.config.json` and the skeleton of `tools/tests/test_pipeline.py` as specified in section 12. At this step only the fixture generation needs to work; create the test file with the four test methods as described but mark the ones whose scripts do not exist yet with `unittest.skip('step N')`. Later steps remove the skips.

## Specification

## 12. Build order and test

Build in this order and run `py -I tools/tests/test_pipeline.py` after each step from step 3 on:
1. common.py, nodes.json, the rule files.  2. unchunk.py.  3. inventory.py + make_fixtures.py + test.
4. evidence.py, prep_batches.py, pending.py.  5. merge.py, overlaps.py, review_candidates.py.
6. render_html.py, render_tree.py, target_skeleton.py, status.py.  7. OpenCode files and docs.

`tools/tests/make_fixtures.py` creates under `tools/tests/fixtures/`:
- SYS_A (abapGit): package `zmisc` ("Miscellaneous developments") with `ZHR_TS_REPORT` (REPORT, LDB PNP,
  INFOTYPES 0001 0002, rp_provide_from_last, SELECT FROM catsdb, MODIFY zhrts_log, call
  `zcl_util_string=>pad_left`, CALL FUNCTION 'CATS_READ_RECORDS', AUTHORITY-CHECK P_ORGIN), table
  `ZHRTS_LOG` (xml only, fields PERNR/CATSHOURS), class `ZCL_UTIL_STRING` (no evidence), class
  `ZCL_PO_CHECK` (INTERFACES if_ex_me_process_po_cust, TYPE ekko/ekpo, SELECT FROM ekko, BAPI_PO_GETDETAIL1,
  MESSAGE e001(zmm)), class `ZCL_DOC_HELPER` (one SELECT from bkpf and one from ekko: ambiguous ->
  needs_llm); package `ztools` with FUGR `ZWF_HR` (xml with FUNCTIONS Z_WF_HR_START, top include with
  TABLES pa0001, FM calling SAP_WAPI_START_WORKFLOW and selecting swwwihead).
- SYS_B: `ZCL_PO_CHECK` with a changed limit (diverged), `ZFI_POST` (SELECT bkpf, BAPI_ACC_DOCUMENT_POST),
  `ZHR_TS_REPORT_B` (copy of the HR report, table ZB_TS_LOG), `ZCL_UTIL_STRING` identical copy.
- SYS_C (chunks): the SYS_A sources as one stream with `*** OBJECT <TYPE> <NAME> ***` markers, the PO class
  split into a DEFINITION marker and an IMPLEMENTATION marker, the FUGR as `*** OBJECT FUGR ZWF_HR ***` +
  pool line and `*** OBJECT FUNC Z_WF_HR_START ***` + FM, plus `*** OBJECT ***` followed by a nameless
  fragment; sliced into 900-byte files `zchunked/z1_0001.abapchunk` ... written raw (no newline added).
- `fixtures/migration.config.json`: SYSA, SYSB, SYSC(chunks); work/output under `../_tmp/`; taxonomy
  `../../taxonomy`; batch_size 5.

`test_pipeline.py` (unittest, subprocess calls with `sys.executable -I`): (00) unchunk --inspect mentions
the detected marker; unchunk reports unresolved=1; manifest has exactly PROG ZHR_TS_REPORT, CLAS
ZCL_UTIL_STRING, CLAS ZCL_PO_CHECK, CLAS ZCL_DOC_HELPER, FUGR ZWF_HR with fms [Z_WF_HR_START]; the PO class
file contains both DEFINITION and IMPLEMENTATION; a second run reports unchanged_packages=1 and still 1
unresolved; applying a mocked resolution (PROG ZFRAGMENT) writes the file and empties the unresolved list.
(01) inventory: 11 objects across SYSA+SYSB; SYSC report hash equals SYSA report hash; FUGR children.
(02) evidence: HR report -> HCM / HCM-PT / HCM-PT-TS auto; Z table and helper class -> HCM via propagation;
PO class -> MM / MM-PUR; FUGR -> HCM; FI report -> FI; doc helper -> needs_llm. (03) batches contain the doc
helper with an excerpt; a mocked llm file with one invalid record -> merge reports llm_invalid=1; second
prep reports batches_done=1; overlaps: ZCL_PO_CHECK diverged, ZCL_UTIL_STRING identical, ZHR_TS_REPORT
identical (SYSA vs SYSC), the A/B timesheet reports in `similar`; review_candidates, render_html (contains
ZHR_TS_REPORT, no raw `</script>` inside the data block), render_tree (`## HCM`, `HCM-PT-TS`), objects.csv,
target_skeleton (`resolve=` in output), status (`NEXT:`) all succeed.

## Acceptance check

`py -I tools/tests/make_fixtures.py` creates SYS_A (6 objects in 2 packages), SYS_B (5 objects) and SYS_C (5 chunk files, written raw with no added newlines, where at least one chunk boundary falls inside a line). `py -I tools/tests/test_pipeline.py` runs and reports the skipped tests without errors.
