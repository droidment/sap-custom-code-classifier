# Step 01: Scaffold, config, common.py and the taxonomy nodes

> This is step 01 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Create the folder layout, `.gitignore`, `migration.config.json` (section 3 shape, placeholder roots), `tools/common.py` exactly as specified in section 4 (including the `ProcessCatalog` loader described in section 5.3, which may stay unused until step 03), and `tools/taxonomy/nodes.json` with the weights and all 106 nodes of section 5.1 (add `"version": "<today>"`).

## Specification

## 2. Folder layout to produce

```
opencode.json  AGENTS.md  README.md  migration.config.json  .gitignore (work/, output/, __pycache__/, tools/tests/_tmp/)
.opencode/agents/      abap-splitter.md  abap-classifier.md  abap-reviewer.md  abap-architect.md
.opencode/commands/    inspect-chunks.md  unchunk.md  inventory.md  classify.md  review.md  explorer.md  tree.md  target-packages.md  status.md
.opencode/skills/      sap-module-taxonomy/SKILL.md  abapgit-layout/SKILL.md  classification-rules/SKILL.md
tools/                 common.py  unchunk.py  inventory.py  evidence.py  prep_batches.py  merge.py  overlaps.py
                       review_candidates.py  render_html.py  render_tree.py  target_skeleton.py  status.py  pending.py  schema.json
tools/taxonomy/        nodes.json  rules_hcm.json  rules_fi_co.json  rules_fi_extra.json  rules_co.json  rules_mm.json  rules_lo.json
                       rules_sd.json  rules_sd_le.json  rules_pp.json  rules_pm_qm_ps.json  rules_bc.json  rules_bc_ca.json
tools/tests/           make_fixtures.py  test_pipeline.py  fixtures/migration.config.json  (fixtures/SYS_A, SYS_B, SYS_C generated)
```

## 3. Configuration: `migration.config.json`

```json
{
  "systems": [
    {"id": "SYSA", "company": "Company A", "root": "C:/exports/SYSA/src"},
    {"id": "SYSB", "company": "Company B", "root": "C:/exports/SYSB/src"},
    {"id": "SYSC", "company": "Company C", "root": "C:/exports/SYSC", "format": "chunks", "chunk_glob": "*.abapchunk", "object_marker": null}
  ],
  "work_dir": "work", "output_dir": "output", "taxonomy": "tools/taxonomy",
  "classification": {"auto_min_score": 6.0, "auto_min_margin": 3.0, "sub_level_share": 0.3, "batch_size": 20,
                     "batches_per_run": 10, "excerpt_max_lines": 140, "excerpt_max_chars": 7000,
                     "propagation_passes": 2, "propagation_cap": 4.0, "propagation_factor_users": 1.0,
                     "propagation_factor_uses": 0.6, "propagated_auto_min_score": 3.5, "propagated_auto_min_margin": 2.0},
  "review": {"low_confidence": 0.6},
  "overlaps": {"similar_name_threshold": 0.82, "min_shared_tables": 2}
}
```
`format` defaults to `abapgit`. Relative paths resolve against the config file's folder. Every script takes
`--config <path>` (default `migration.config.json`), prints progress to stderr and exactly one summary line
to stdout: `INVENTORY_OK ...`, `UNCHUNK_OK ...`, `EVIDENCE_OK ...`, `PREP_OK ...`, `MERGE_OK ...`,
`OVERLAPS_OK ...`, `REVIEW_CANDIDATES_OK ...`, `EXPLORER_OK ...`, `TREE_OK ...`, `TARGET_OK ...`.

## 4. `tools/common.py`

- `load_config(path) -> Config` with deep-merged defaults (the values above), properties `systems`,
  `work_dir`, `output_dir`, `taxonomy_path`, `classification`, `review`, `overlaps`, and file locations
  `inventory_file` (work/inventory.jsonl), `evidence_file`, `auto_file` (work/auto.json), `batches_dir`,
  `llm_dir`, `classification_file`, `overlaps_file`, `review_candidates_file`, `review_patch_file`,
  `target_draft_file`; `fmt(system)` -> "abapgit"|"chunks"; `unchunked_dir(system)` = work/unchunked/<id>;
  `system_root(system)` = unchunked_dir for chunks else resolved root; `roots()` dict id->Path.
- JSON/JSONL helpers; `read_text(path)` tries utf-8-sig, utf-8, cp1252, latin-1.
- `make_key(system, type, name)` = `SYSTEM|TYPE|NAME`; `split_key`.
- `parse_abapgit_filename("zcl_foo.clas.locals_imp.abap") -> ("ZCL_FOO","CLAS","locals_imp.abap")`;
  `#ns#` decodes to `/NS/`; names upper-cased.
- `strip_line_comment(line)`: removes a trailing `"` comment that is outside `'...'`, `` `...` ``, `|...|`
  literals. `code_lines(text)` yields (lineno, line) skipping full-line `*` comments and blank lines.
  `comment_lines(text)` yields the text of `*` comment lines that are not pure decoration (`*&----`).
- `normalize_source(text)`: comment-free, whitespace-collapsed, upper-cased; `source_hash` = sha1 of it.
- `Taxonomy`: loaded from a directory: `nodes.json` (`weights`, `nodes:[{id,name,parent}]`) plus every
  `rules_*.json` merged (`{"rules":[...]}`). Methods: `top_level`, `parent`, `ancestors(id)` (root..id),
  `module_of`, `split(id) -> (module, submodule, area)`, `children`, `name(id)`,
  `is_valid_path(module, submodule, area)`. Fail loudly on duplicate ids, unknown parents, rules naming
  unknown nodes.

## 5. Taxonomy
### 5.1 Nodes (`tools/taxonomy/nodes.json`), 102 nodes, 3 levels
Weights: `table 5, table_prefix 4, type_ref 2.5, function 5, function_prefix 3, class 5, class_prefix 3,
include 4, include_prefix 3, ldb 6, infotype 5, infotype_range 4, badi 6, badi_prefix 4, tcode 3,
tcode_prefix 2, msgclass 3, msgclass_prefix 2, authobj 4, authobj_prefix 3, keyword 1.5, name_prefix 1.5,
package_keyword 1, object_type 1.5`.

Modules and children (id - name):
- HCM Human Capital Management: HCM-PA Personnel Administration; HCM-PT Time Management (HCM-PT-TS Time
  Sheet/CATS, HCM-PT-EV Time Evaluation, HCM-PT-ABS Absences/Attendances/Quotas); HCM-PY Payroll
  (HCM-PY-POST Posting to FI/CO); HCM-OM Org Management; HCM-PD Personnel Development; HCM-PE Training;
  HCM-BN Benefits; HCM-RC Recruitment; HCM-CM Compensation; HCM-ESS ESS/MSS; HCM-WF HR Workflows
  (HCM-WF-LEAVE Leave/Time Requests).
- FI: FI-GL; FI-AP (FI-AP-PAY payment run/media); FI-AR (FI-AR-DUN dunning); FI-AA assets; FI-BL bank;
  FI-TV travel; FI-SL special ledger; FI-TX taxes; FI-CLS closing.
- CO: CO-OM overhead (cost centers, internal orders); CO-PC product costing/material ledger; CO-PA;
  CO-PCA profit centers.
- MM: MM-PUR purchasing (MM-PUR-PO, MM-PUR-PR requisitions/release, MM-PUR-CON contracts/agreements/
  source lists); MM-IM inventory mgmt (MM-IM-PI physical inventory); MM-IV invoice verification;
  MM-SRV external services; MM-MD vendor purchasing master.
- LO: LO-MD material master; LO-BM batches; LO-VC variant configuration; LO-HU handling units.
- SD: SD-SLS sales docs; SD-BIL billing; SD-BF basic functions (SD-BF-PR pricing, SD-BF-OUT output/NAST);
  SD-MD customer sales views; SD-EDI sales EDI.
- LE: LE-SHP deliveries; LE-WM warehouse; LE-TRA transportation.
- PP: PP-SFC production orders; PP-MRP; PP-BD BOM/routing/work center; PP-PI process orders; PP-REM.
- PM: PM-EQM technical objects; PM-WOC orders & notifications; PM-PRM maintenance plans.
- QM: QM-IM inspection lots/results/UD; QM-QN quality notifications; QM-PT inspection planning.
- PS: PS-STR structures (WBS, networks); PS-COS costs/settlement.
- FSCM: FSCM-CR credit; FSCM-COL collections/dispute.
- BC Technical: BC-WF workflow tech; BC-ALE IDoc/ALE/EDI; BC-ESI interfaces (RFC, web services, proxies,
  OData/Gateway, Fiori); BC-SEC authorizations/users; BC-SRV output (BC-SRV-FORM forms, BC-SRV-MAIL email,
  BC-SRV-FILE file upload/download/Excel); BC-ABA utilities (BC-ABA-JOB background jobs); BC-CTS transport/
  dev tools; BC-BW extractors; BC-UI ALV/Dynpro/Web Dynpro without business context.
- CA Cross-application: CA-BP business partner; CA-ADR addresses; CA-DMS documents; CA-CL classification;
  CA-GEN change docs, number ranges, texts, units, currencies.
- Aerospace & Defense facets as submodules of their base module (4 nodes, total 106): PS-GPD Grouping,
  Pegging and Distribution; CO-GOV Government Contract Accounting (cost-plus, progress billing, earned
  value); PM-MRO Maintenance, Repair and Overhaul; LO-EFF Configuration Control and Effectivity.
- UNKNOWN.

## Acceptance check

`py -c "import sys;sys.path.insert(0,'tools');from common import load_taxonomy;t=load_taxonomy('tools/taxonomy');print(len(t.nodes),t.top_level)"` prints 106 and the 16 top-level ids (HCM, FI, CO, MM, LO, SD, LE, PP, PM, QM, PS, FSCM, BC, CA, UNKNOWN plus none other). It must fail loudly on a duplicate id or unknown parent.
