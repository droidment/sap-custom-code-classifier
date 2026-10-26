# Step 00: Project context and conventions (read with every step)

## Task

Do not build anything from this file alone. It is the shared context for steps 01 to 11: paste it, or keep it open as `AGENTS.md` in the build folder, so every step sees the same rules.

## Specification

## 1. Problem and constraints

- Three ECC 6.0 systems (one per company). Years of custom code, mixed into wrongly named packages. Before
  merging into one S/4HANA system, every custom object must be assigned to a module (HCM, FI, MM, ...),
  submodule (HCM-PT, MM-PUR, ...) and where possible an area (HCM-PT-TS timesheet, MM-PUR-PO, ...), with a
  one-sentence business purpose, and duplicates/variants across systems must be flagged.
- Input is on disk, one root folder per system, in one of two formats:
  1. **abapGit export**: one folder per package, files named `<object>.<type>.<rest>`
     (`zcl_x.clas.abap`, `zcl_x.clas.xml`, `zprog.prog.abap`, `zfg.fugr.xml`, `zfg.fugr.z_fm.abap`, ...),
     `package.devc.xml` per folder.
  2. **Chunked export**: one folder per package holding chained plain-text files `z1_0001.abapchunk`,
     `z1_0002.abapchunk`, ... Chunks are size-based (an object or even a line can be cut between the end of
     one file and the start of the next). Objects inside are separated by marker lines. No metadata.
- The source folders are read-only. All state goes to `work/` (resumable intermediates) and `output/`
  (deliverables).
- Everything must be chunked and resumable: thousands of objects, limited session time and memory.
  Re-running any command continues where it stopped.
- Deterministic work in Python; the LLM only decides what heuristics cannot, in bounded batches.
- No pip packages. Python 3.11+, launcher `py`. No CDN in the HTML (must open offline).

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

## 13. Pitfalls already met (do not repeat)

- Appending a newline per chunk during concatenation splits lines cut at chunk boundaries. Concatenate raw.
- A marker regex that requires a name never starts a segment for nameless markers; make type/name optional.
- A table listed on a node and on its children triple-counts the module; credit the deepest node once.
- Propagation-only objects never reach the normal auto threshold; use the lower propagated thresholds.
- Rule lists with invented or numbered names, generic words, or prefixes shared across branches (`ZCL`,
  `ZPAY`, `ZDOC`, `ZREQ`, `ZPI`, `ZPO` in BC) cause silent misclassification. Keep lists short and real.
- Shell one-liners with nested quotes in command files break on Windows; put logic in a script
  (`pending.py`) and call that.
- Write `work/unchunk_unresolved.json` from the union of newly found and still-unresolved-from-unchanged
  packages, or a re-run silently forgets them.

## Acceptance check

Nothing to run. Confirm you have read the layout, the config shape, and the pitfalls, then proceed to step 01.
