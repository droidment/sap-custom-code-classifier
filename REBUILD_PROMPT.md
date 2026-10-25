# Rebuild prompt: SAP custom-code classifier toolkit for OpenCode

Give this whole document to a capable coding model (in OpenCode, run as the `build` agent in an empty
folder) with the instruction: **"Build everything this specification describes. Work stage by stage in the
order of section 12, run the test after each stage, and stop only when the test passes."**

The result is an OpenCode project that classifies the custom ABAP of three SAP ECC 6.0 company systems by
SAP module / submodule / area, finds overlaps between the systems, and produces an HTML explorer, a
Markdown tree + CSV, and a proposed S/4HANA target package design. Python standard library only, invoked as
`py`. Models are Azure OpenAI deployments `az-gpt-5.6-sol`, `az-gpt-5.6-terra`, `az-gpt-5.6-luna`.

---

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
.opencode/agents/      sap-migration.md (primary)  abap-splitter.md  abap-classifier.md  abap-reviewer.md  abap-architect.md
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

### 5.2 Rules (`rules_*.json`)
Each rule: `{"node": "<id>", "<kind>": [...], ..., "weight": optional multiplier}`. Kinds: `table`,
`table_prefix`, `function`, `function_prefix`, `class`, `class_prefix` (also matches interfaces),
`include`, `include_prefix`, `ldb`, `infotype`, `infotype_range` ([["2000","2999"]]), `badi`,
`badi_prefix`, `tcode`, `tcode_prefix`, `msgclass`, `msgclass_prefix`, `authobj`, `authobj_prefix`,
`keyword` (lower-case, matched in descriptions/comments), `name_prefix` (object name), `package_keyword`,
`object_type`.

Quality rules (important, learned the hard way): keep lists short and real (max ~25 entries per list,
only names you are sure exist in ECC 6.0); never invent numbered series; never use a prefix shorter than
3 characters or a generic English word as keyword ("document", "status", "change", "report"); never let
two sibling branches claim the same `name_prefix` (e.g. `ZPAY` payroll vs payment -> use neither; `ZCL`
must never be a prefix since every class starts with it); generic HR signals (PA0001, PNP, HR_* prefix,
infotypes 0000-0003) score the HCM root, specific ones score the submodule; shared tables (AFKO for
PP/PS/PM, QMEL for QM/PM, AUFK for CO/PP) are allowed on several nodes, the LLM disambiguates.

Seed signals per node (expand modestly, one or two lines each):
- HCM root: table_prefix T5,T7,PCL; ldb PNP,PNPCE,PCH; function_prefix HR_,RP_,BAPI_EMPLOYEE_; authobj_prefix P_; name_prefix ZHR,ZHCM; infotype 0000-0003,0006,0007,0105 (root only).
- HCM-PA: infotype_range 0004-0999, 9000-9999; table_prefix PA0,PA9; badi HRPAD00INFTY, HRPAD00AUTH_CHECK; tcode PA20,PA30,PA40; include_prefix MP00..MP09, ZXPAD.
- HCM-PT: infotype_range 2000-2999; table_prefix PA2,PTEX,PTQ,T55x; function_prefix HR_TIME_,PT_; class_prefix CL_PT_; tcode_prefix PT. HCM-PT-TS: CATSDB, CATSCO, CATSHR, CATSPS, CATSMM; function_prefix CATS_, BAPI_CATIMESHEET; badi CATS0001-CATS0012; tcode CAT2, CAT3, CATS_APPR_LITE, CADO. HCM-PT-EV: include RPTIME00, RPTEDT00; T555E, T510S; keyword schema, pcr, cluster b2. HCM-PT-ABS: infotypes 2001-2013; T554S, T556A, PTQUODED; BAPI_ABSENCE_*, HR_QUOTA*.
- HCM-PY: table_prefix T512, T549, T52C/D/E, T5U/K/G/D...; infotypes 0008,0009,0011,0014,0015,0027,...; function CU_READ_RGDIR, PYXX_READ_PAYROLL_RESULT, HR_GET_PAYROLL_RESULTS; include_prefix RPC, RPCALC, RPCLST; tcode_prefix PC00, PC_; keyword payroll, wage type, payslip, retro. HCM-PY-POST: PPOIX, PPOPX, PPDIT, T52EK; include_prefix RPCIPE; badi SMOD_PCPO0001.
- HCM-OM: table_prefix HRP1, HRT1, T777, T778, T77; infotype_range 1000-1999; function_prefix RH_, RHOM_, BAPI_ORGUNIT; ldb PCH; badi_prefix HRBAS; tcode PPOME, PO10, PO13, PP01; authobj PLOG.
- HCM-PD: HRHAP*, T77HAP*, infotype 0024, 1024-1049; function_prefix RHPP_, HRHAP_; tcode_prefix PHAP. HCM-PE: LSO*, T77VS, infotype 1021,1034,1060+; function_prefix RHPE, LSO_; tcode_prefix PV, PSV. HCM-BN: infotypes 0167-0172,0219,0375-0379; T5UB*; function_prefix HR_BEN_; tcode_prefix HRBEN. HCM-RC: table_prefix PB0, PB4, T750, T77RCF; infotype_range 4000-4999, 5100-5199; function_prefix HRRCF, BAPI_APPLICANT. HCM-CM: infotypes 0380-0383, 0758-0799; T71*; function_prefix HR_ECM; tcode_prefix PECM. HCM-ESS: class_prefix CL_HRESS, CL_HRMSS, CL_HRXSS; function_prefix HRXSS_, HRWPC_; T7XSS*. HCM-WF: table_prefix T5ASR, HRASR; class_prefix CL_HRASR; keyword hr workflow, personnel change request, hcm processes and forms. HCM-WF-LEAVE: PTREQ_HEADER, PTREQ_ITEMS; function_prefix PT_ARQ_, PT_COR_; class_prefix CL_PT_REQ; badi PT_ABS_REQ, PT_GEN_REQ; tcode PTARQ.
- FI root: BKPF, BSEG, BSIS, BSAS, T001, T003, T030, TBSL; function BAPI_ACC_DOCUMENT_POST/CHECK, POSTING_INTERFACE_*; badi AC_DOCUMENT, FI_HEADER_SUB_1300, F050S001..; tcode_prefix FB, F-, FS, FAGL, OB; authobj_prefix F_; name_prefix ZFI. FI-GL: SKA1, SKB1, SKAT, FAGLFLEXA/T, GLT0, T030K; BAPI_GL_*, FAGL_*; badi FAGL_DERIVE_SEGMENT; tcode FS00, FB50, FAGLL03, FAGLGVTR. FI-AP: LFA1, LFB1, LFBK, BSIK, BSAK, T077K; BAPI_VENDOR_*, BAPI_CREDITOR_*; badi VENDOR_ADD_DATA; tcode FK01-03, XK01-03, FB60, FBL1N, F-53. FI-AP-PAY: REGUH, REGUP, PAYR, T042*, DMEE_TREE, FDTA; function_prefix FI_PAYMEDIUM_, DMEE_; include_prefix RFFO; tcode F110, FBZP, FCHN, DMEE; keyword payment run, payment medium, sepa, ach, check printing. FI-AR: KNA1, KNB1, KNBK, BSID, BSAD, T077D; BAPI_CUSTOMER_*, BAPI_AR_ACC_*; badi CUSTOMER_ADD_DATA; tcode FD01-03, FB70, FBL5N, F-28. FI-AR-DUN: MHNK, MHND, T047*; include_prefix RFMAHN, SAPF150; tcode F150; keyword dunning. FI-AA: ANLA, ANLB, ANLC, ANLZ, ANEP, ANEK, T093*; BAPI_FIXEDASSET_*, BAPI_ASSET_*; tcode AS01-03, AW01N, AFAB, ABUMN; authobj_prefix A_. FI-BL: FEBEP, FEBKO, BNKA, T012, T028*, AVIK, AVIP; function_prefix FEB_, BAPI_BANK_; badi FIEB_CHANGE_BS_DATA; include_prefix RFEBKA, RFEBLB; tcode FF67, FF_5, FEBA; keyword bank statement, lockbox, cash management. FI-TV: PTRV_HEAD, PTRV_SREC, T706*, infotype 0017, 0470-0475; function_prefix PTRA_, BAPI_TRIP_; tcode PR05, TRIP. FI-SL: GLT1-3, GLU1-3, T881, T882; function_prefix G_; tcode_prefix GB, GC, GD. FI-TX: BSET, T007A, T007S, T059*, WITH_ITEM, J_1B*, J_1I*; function CALCULATE_TAX_*; tcode FTXP, J1B*. FI-CLS: function_prefix SCMA_, FAGL_FC_VAL, FAGLF101; tcode OB52, F.16, F.07, F.05, FAGL_FC_VAL, F101; keyword closing, period end, carryforward.
- CO root: TKA01, COBK, COEP, COSP, COSS, T811*; function_prefix K_; authobj_prefix K_; tcode KB11N..., OKB9, OKKP; name_prefix ZCO. CO-OM: CSKS, CSKT, CSKA, CSKB, CSLA, AUFK; BAPI_COSTCENTER_*, BAPI_INTERNALORDER_*, BAPI_ACTIVITYTYPE_*; badi COOMCCA_ADDITIONAL_FIELDS; tcode KS01-03, KO01-03, KSB1, KOB1, KSU5, KSV5, KA01, KL01. CO-PC: KEKO, KEPH, CKIS, CKML*, MLCD, MBEW; BAPI_COSTESTIMATE_*; tcode CK11N, CK40N, CKM3, MR21. CO-PA: table_prefix CE1, CE2, CE3, CE4, TKE; BAPI_COPAACTUALS_POSTCOSTDATA, RKE_*; badi COPA0001-5; tcode_prefix KE. CO-PCA: CEPC, GLPCA, GLPCT; BAPI_PROFITCENTER_*; tcode KE51-53, KCH1-3.
- MM root: T001W, T001L, T024, T024E, T023, T134, T156, T161; authobj_prefix M_; msgclass M3, M7, ME, 06. MM-PUR: EKKO, EKPO, EKET, EKBE, EKKN, EKES, EBAN, EBKN, EINA, EINE, EORD, T160, T161, T163, T16F*, LFM1; BAPI_PO_*, BAPI_REQUISITION_*, BAPI_PR_*, ME_*, BAPI_CONTRACT_*, BAPI_SAG_*; badi ME_PROCESS_PO_CUST, ME_PROCESS_REQ_CUST, ME_GUI_PO_CUST, ME_PURCHDOC_POSTED, ME_REQ_POSTED, MM06E005, M06B0001-5, MEREQ001; include_prefix ZXM06, ZXM02, SAPMM06E, SAPLMEPO; tcode_prefix ME; authobj M_BEST_*, M_BANF_*, M_RAHM_*, M_EINK_FRG; keyword purchase order, purchase requisition, release strategy. MM-PUR-PO / -PR / -CON: split the above by EKKO/EKPO vs EBAN/EBKN vs EKAB/EINA/EINE/EORD and ME21N-ME29N vs ME51N-ME59 vs ME31K-ME35L, ME41-49, ME11-18, ME01-08. MM-IM: MKPF, MSEG, MARD, MCHB, MSKA, MSLB, T156*, T157*, T158*, RESB, RKPF; BAPI_GOODSMVT_*, MB_CREATE_GOODS_MOVEMENT; badi MB_DOCUMENT_BADI, MB_MIGO_BADI, MBCF0002-9; include_prefix ZXMBC, SAPMM07M, SAPLMIGO; tcode MIGO, MB1A-C, MB51, MB52, MMBE; authobj M_MSEG_*. MM-IM-PI: IKPF, ISEG, T064*; BAPI_PHYSINVENTORY_*; tcode_prefix MI; keyword physical inventory, cycle count. MM-IV: RBKP, RSEG, RBCO, T169*; BAPI_INCOMINGINVOICE_*, MRM_*; badi INVOICE_UPDATE, MRM_HEADER_CHECK, MRM_ITEM_CUSTFIELDS, MRM_PAYMENT_TERMS, LMR1M001-6; include_prefix ZXM08, SAPLMRMP, SAPLMR1M; tcode MIRO, MIR4-7, MR8M, MRBR, MRRL, MRKO, MR11; authobj M_RECH_*. MM-SRV: ESLL, ESSR, ESKN, ESLH, ASMD, T165*; BAPI_ENTRYSHEET_*, MS_*; badi_prefix SRV; tcode ML81N, ML84, ML85, AC01-03; authobj_prefix M_SRV. MM-MD: LFM1, LFM2, WYT3; tcode MK01-03.
- LO-MD: MARA, MAKT, MARC, MVKE, MARM, MEAN, MLAN, T134, T023; BAPI_MATERIAL_SAVEDATA, BAPI_MATERIAL_GET_ALL; badi BADI_MATERIAL_CHECK, BADI_MATERIAL_REF; tcode MM01-03, MM17; authobj_prefix M_MATE. LO-BM: MCHA, MCH1, MCHB, T148, T149; BAPI_BATCH_*, VB_*; badi BATCH_MASTER; tcode MSC1N-4N. LO-VC: CUOB, CUCO, CUKB, CUKN, CUEX, CUVTAB, IBIN, IBSYMBOL, IBST; CUCB_*, CE_C_*; tcode_prefix CU; include_prefix SAPLCUCB. LO-HU: VEKP, VEPO, HUMSEG; HU_*, BAPI_HU_*; tcode HU02, HUMO, VLHUPACK.
- SD root: TVKO, TVTW, TSPA, TVAK, TVAP, TVST, TVLK, TVFK, VBPA, VBUK, VBUP, VBFA, VBKD, VBEP; function_prefix SD_, RV_, BAPI_SALESDOC; authobj_prefix V_; msgclass V1, V2, V4, VF, VL. SD-SLS: VBAK, VBAP, VBEP, VBKD, VBAG, VEDA, VBLB, VBBE; BAPI_SALESORDER_*, SD_SALESDOCUMENT_*, BAPI_QUOTATION_*, BAPI_CUSTOMERCONTRACT_*, BAPI_CUSTOMERRETURN_*; badi BADI_SD_SALES, V45A0001-4, V45E0001-2, V45L0001, V45P0001, V45S0001-4, V45W0001, V46H0001; include_prefix MV45AFZZ, MV45AFZA, MV45AFZB, MV45AFZ4, SAPMV45A, ZXVVA; tcode VA01-05, VA11-13, VA21-23, VA41-43; authobj V_VBAK_AAT, V_VBAK_VKO, V_VBKA_*. SD-BIL: VBRK, VBRP, VBRL, TVFK, VBSK, VBSS, VBOX; BAPI_BILLINGDOC_*, RV_INVOICE_*; badi BADI_SD_BILLING, V60A0001, SDVFX001-12; include_prefix RV60AFZZ, RV60AFZA-C, RV61AFZA, SAPLV60A, SAPLV61A, ZXVVF; tcode VF01-05, VF11, VF31, VFX3, VF04; authobj V_VBRK_FKA, V_VBRK_VKO. SD-BF: TVPA, TPAR, TPAER, TVPG; SD_PARTNER_*, RV_PARTNER_*; badi V09A0001; tcode VOPA, VOTX, VOFM, VOV8. SD-BF-PR: KONV, KONP, KONH, T683, T685, KOMK, KOMP, A004, A005, A305; PRICING, SD_COND_ACCESS, BAPI_PRICES_CONDITIONS; badi PRICING_HEADER_PROC, PRICING_ITEM_PROC; include_prefix RV61A, RV63A, RV64A; tcode VK11-15, VK31-33, V/08, V/06. SD-BF-OUT: NAST, TNAPR, NACH, B001-3; RV_MESSAGE_*, WFMC_*; include_prefix RVADOR, RVADDN, RVADIN, RVADAUS, SAPLV61B; tcode NACE, VV11-13, VV21-23, VV31-33, MN04-06. SD-MD: KNVV, KNVP, KNVI, KNVK, KNVH; SD_CUSTOMER_MAINTAIN_ALL; tcode XD01-03, VD01-03, VDH1N. SD-EDI: E1EDK01, E1EDP01, E1EDKA1, EDPAR, EDSDC; IDOC_INPUT_ORDERS, IDOC_INPUT_ORDRSP, IDOC_OUTPUT_ORDERS, IDOC_OUTPUT_INVOIC, IDOC_OUTPUT_DESADV, IDOC_INPUT_DELINS; badi VEDA0001, VEDB0001, VEDC0001; include_prefix ZXVEDU, ZXVEDF, LVEDA, LVEDB, LVEDC.
- LE root: TVLK, TVST, TVLA, TVTK, T300, T301; function_prefix LE_, SHP_, GN_; authobj_prefix L_, V_LIKP, V_VTTK. LE-SHP: LIKP, LIPS, VBLB, TVLK, TVLP, TVST, VBSK, VBSS, T30A, T30B; BAPI_OUTB_DELIVERY_*, BAPI_INB_DELIVERY_*, BAPI_DELIVERYPROCESSING_EXEC, WS_DELIVERY_UPDATE, GN_DELIVERY_CREATE, SD_DELIVERY_*, RV_DELIVERY_*, SHP_*, WS_REVERSE_GOODS_ISSUE; badi LE_SHP_DELIVERY_PROC, LE_SHP_GOODSMOVEMENT, LE_SHP_TAB_CUST_HEAD/ITEM/OVER, V50PSTAT, V50Q0001, V50R0001-4, V50S0001, V53C0001-2, V53W0001, V56F0001; include_prefix MV50AFZ1-3, MV50AFZZ, SAPMV50A, ZXVVLU; tcode_prefix VL, VLPOD, VLSP; authobj V_LIKP_VST, V_LIKP_VKO. LE-WM: LAGP, LQUA, LTAK, LTAP, LTBK, LTBP, LUBU, LEIN, LINK, LINP, LINV, T300-T34x; L_TO_*, L_TR_*, BAPI_WHSE_*; badi_prefix MWMTO, MWMTR, MWMRF, MWMD0, MWMIDO, MWMIDI, MWMPP, MWMBAP, MWMPL, MWM2S; tcode_prefix LT, LB, LS, LX, LI, LL, LP, LRF, LM; include_prefix SAPLL03A, SAPLL03B, SAPML03T, ZXLTOU; authobj L_LGNUM, L_TCODE, L_BWLVS, L_SFUNC, L_LGTYP, L_LGPLA. LE-TRA: VTTK, VTTP, VTTS, VTSP, VTPA, VTFA, VTRLK, VTRLP, TVTK, TVRO, VFKK, VFKP; BAPI_SHIPMENT_*, SD_SHIPMENT_*, ST_*, SD_SCD_*; badi BADI_LE_SHIPMENT, V56AFCC, V56AGCFL, V56L0001, V56UCHCH, V56USTAT; include_prefix SAPMV56A, SAPLV56A-F, ZXV56U; tcode_prefix VT, VI.
- PP root: AFKO, AFPO, AFVC, AFVV, AFRU, AFFL, AFFH, AUFK, RESB, CAUFV, PLAF, MDKP, MDTB, CRHD, MAPL, MAST, STKO, STPO, PLKO, PLPO; function_prefix BAPI_PRODORD, BAPI_PLANNEDORDER, CSAP_, CS_BOM, BAPI_ROUTING, CR_, CARO_, CAPA_, MD_; authobj_prefix C_AFKO, C_AFPO, C_AFVC, C_AFRU, C_STUE, C_ROUT, C_ARPL, C_PLAF; msgclass CO, C2, CN, RU, 61, 29, CP, MD, CR, CM. PP-SFC: AFKO..AFRU, AFAB, T399X, TCO41, TCO43, TCOKO; BAPI_PRODORD_*, BAPI_PRODORDCONF_*, CO_RU_*, CO_SF_*, CO_ZV_*; badi WORKORDER_UPDATE, WORKORDER_CONFIRM, WORKORDER_GOODSMVT, WORKORDER_INFOSYSTEM, WORKORDER_OPERATION, CONFPP01-7, PPCO0001-23; include_prefix SAPLCOZV, SAPLCOKO, SAPLCOKO1, SAPLCORU, ZXCO; tcode CO01-03, CO11N, CO15, CO40, CO41, COOIS, COHV, COGI, CO88. PP-MRP: PLAF, MDKP, MDTB, MDBS, MDPS, MDMA, T399D, T438*, T439*; BAPI_PLANNEDORDER_*, MD_STOCK_REQUIREMENTS_LIST_API, MD_MRP_LIST_API, BAPI_REQUIREMENTS_*, BAPI_PIR_*; badi MD_ADD_COL_EZ, MD_ADD_ELEMENTS, MD_CHANGE_MRP_DATA, MD_PLDORD_CHANGE, MD_PURREQ_CHANGE, M61X0001-2, MDPL0001-10; tcode MD01-21, MD04, MD05, MD61-63, MDBT; include_prefix SAPMM61X, SAPLM61C. PP-BD: MAST, STKO, STPO, STAS, STZU, PLKO, PLPO, PLAS, PLFL, PLMZ, PLMK, MAPL, CRHD, CRTX, CRCO, CRCA, KAKO, KAPA, KBED, KBKO, T430-T437; CSAP_MAT_BOM_*, CS_BOM_EXPL_MAT_V2, CS_WHERE_USED_MAT, BAPI_ROUTING_*, BAPI_WORKCENTER_*, CR_WORKSTATION_READ; badi BOM_UPDATE, PCSD0001-20, CPAU0001-20, CRAP0001-20; tcode_prefix CS, CA0-CA9, CR, CM; include_prefix SAPLCSDI, SAPLCSAP, SAPLCPDI, SAPLCRAP. PP-PI: COCH, COCF, COMH, COMI, TCOPI*, PLPH, PLMZ; BAPI_PROCORD_*, BAPI_PROCORDCONF_*, BAPI_MASTERRECIPE_*, BAPI_PI_SHEET_*, BAPI_PROCESS_MESSAGE_*; badi CONFPI01-7; tcode COR1-3, COR6N, COOISPI, COHVPI, C201-203; include_prefix SAPLCOPI, SAPLCOCH. PP-REM: SAFK, T437S, BLPK, BLPP; BAPI_REPMANCONF_*, BAPI_REPMANCONF1_*; badi RMPU0001-20, RMCP0001-20; tcode MF50, MFBF, MF12, MF26, MF41-50, MFHU, MFPR, MFS0; include_prefix SAPLRMBF, SAPLRMPU.
- PM root: EQUI, EQKT, EQUZ, ILOA, IFLOT, IFLOTX, AFIH, QMEL, QMIH, VIAUFKST, VIQMEL, T370, T003O, TQ80; BAPI_EQUI_*, BAPI_FUNCLOC_*, BAPI_ALM_*, IWO_*, ALM_*; authobj_prefix I_; msgclass IW, IH, IL, IE, IS, IP, IM. PM-EQM: EQUI, EQKT, EQUZ, EQBS, ILOA, IFLOT, IFLOTX, IFLOS, IHPA, OBJK, SER01-03; BAPI_EQUI_CREATE/CHANGE/GETDETAIL/INSTALL/DISMANTLE, BAPI_FUNCLOC_*; badi EQUI_UPDATE, IEQM0001-7, ILOM0001-2, ITOB0001-4; tcode IE01-03, IE05, IE07, IE4N, IH01-03, IH06, IH08, IL01-03, IL05-07. PM-WOC: AFIH, VIAUFKST, VIAUFKS, VIQMEL, QMEL, QMIH, QMFE, QMMA, QMUR, QMSM, IHPA, T350, T352, T353; BAPI_ALM_ORDER_MAINTAIN/GET_DETAIL/GETLIST, BAPI_ALM_NOTIF_*, BAPI_ALM_CONF_*, IQS4_*; badi IWO1_ORDER_BADI, IWO1_PREQ_BADI, IWO1_SCREEN_MODIFY, IWOC_LIST_TUNING, IWO10001-31, QQMA0001-30, NOTIF_EVENT_SAVE/POST; include_prefix SAPLIWO1, SAPLIWOC, SAPLIQS0, SAPLCOIH, ZXWOC, ZXWOU; tcode_prefix IW. PM-PRM: MPOS, MPLA, MHIS, MMPT, MHIO, T351*; MAINTENANCE_PLAN_*; badi IPRM0001-20; tcode_prefix IP.
- QM root: QALS, QAVE, QAMB, QPRS, QMEL, QPMK, PLMK, QMAT, TQ01-TQ10; function_prefix BAPI_INSPLOT, BAPI_INSPOPER, BAPI_INSPCHAR, BAPI_QUALNOT, QIRF_, QEEM_, QELA_, QEVA_, QA_, QE_; authobj_prefix Q_; msgclass QA, QE, QS, QP, QM. QM-IM: QALS, QAVE, QAMB, QASE, QPRS, QASR, QAMR, QAMV, QAPP, QAPO; BAPI_INSPLOT_*, BAPI_INSPOPER_*, BAPI_INSPCHAR_*, BAPI_INSPPOINT_*, QIRF_GET_*, QPL1_INSPECTION_LOT_CREATE; badi QPL1_SUBSCREEN, QEEM0001-35, QEVA0001-10, QLCO0001-3, QPAP0001-10, QAPP0001-10; tcode_prefix QA, QE, QVM, QGA, QGC, QGD, QGP. QM-QN: QMEL, QMFE, QMMA, QMUR, QMSM, QMIH, QMAT, TQ80-TQ89; BAPI_QUALNOT_*, BAPI_SERVNOT_*, IQS4_*; badi QQMA0001-30, NOTIF_EVENT_SAVE/POST, NOTIF_AUTHORITY_01-10; tcode_prefix QM, IQS. QM-PT: QPMK, QPMT, QPMZ, PLMK, PLMW, QPCT, QPCD, QPGR, QPGT, QPAM, QPAC, QPSD, QPSS, QMAT; BAPI_INSPECTIONPLAN_*, BAPI_MASTERINSPCHAR_*, BAPI_SAMPLINGPROC_*, BAPI_CATALOG_*, BAPI_CODEGROUP_*, BAPI_SELECTEDSET_*, BAPI_QMAT_*; badi QPAP0001-10, QPMK0001-10, PLMK0001-10, PLMW0001-10; tcode_prefix QP, QS, QD.
- PS root: PROJ, PRPS, PRHI, PRTE, PRTX, PSTX, AFKO, AFVC, AFVV, AFAB, RESB, RPSCO, RPSQT, TCJ01-TCJ99; BAPI_PROJECT_MAINTAIN, BAPI_PROJECT_GETINFO, BAPI_PS_INITIALIZATION, BAPI_PS_PRECOMMIT, BAPI_BUS2001_*, BAPI_BUS2054_*, BAPI_BUS2002_*, BAPI_NETWORK_*, BAPI_PROJECTDEF_*, BAPI_WBS_*; badi CNEX0001-50, CNIF0001-50, COPCP001-10; include_prefix SAPLCJWB, SAPLCJTR, SAPLCJPN, SAPLCNTR, SAPLCNWB, ZXCNU, ZXCJU; tcode_prefix CJ, CN, OPS; authobj_prefix C_PROJ, C_PRPS, C_NETW; msgclass CJ, CN, BS, PS. PS-STR: PROJ, PRPS, PRHI, PRTE, PRTX, PSTX, NPLNR; BAPI_PROJECT_MAINTAIN, BAPI_BUS2001_*, BAPI_BUS2054_*, BAPI_BUS2002_*, BAPI_NETWORK_*; tcode CJ01-03, CJ06-08, CJ11-14, CJ20N, CJ2A-D, CJ27, CN01-03, CN11-13, CN21-29, CN41-47. PS-COS: RPSCO, RPSQT, BPGE, BPJA, BPEG, BPEJ, BPPE, BPTR, BPHI, BPIG, BPIJ, BPVG, BPVJ; function_prefix BAPI_PS_COST, BAPI_PS_BUDGET, BAPI_PROJECT_COST, BAPI_BUDGET, K_PROJECT, K_WBS, KBPD_, KBPP_, BP_; tcode CJ30-38, CJ40-49, CJ70-81, CJ88, CJ8G, CJ9B-Q, CJI3, CJI5, CJS2-9, DP90-99.
- FSCM-CR: UKMBP_CMS, UKM_ITEM, UKM_TOTALS, KNKK, KNKA; function_prefix UKM_, BAPI_CREDIT_, SD_CREDIT; badi UKM_R3_ACTIVATE, UKM_FILL, BADI_SD_CM; tcode UKM_BP, UKM_CASE, FD32, VKM1-4, OVA8. FSCM-COL: UDM_WL_ITEM, UDM_CCT_DOC, UDM_CONTACT, UDM_PROMISE, FDM_DCOBJ, FDM_DCPROC, SCMG_T_CASE_ATTR; function_prefix UDM_, FDM_, SCMG_, BAPI_COLLECTIONS, BAPI_DISPUTE; badi_prefix UDM_, FDM_, SCMG_; tcode UDM_SUPERVISOR, UDM_SPECIALIST, UDM_BP, SCASE.
- BC root: only keyword technical, basis, framework, utility, helper, wrapper; name_prefix ZBC, ZBASIS, ZTECH; package_keyword BC, BASIS, TECH, UTIL, TOOLS, COMMON, CORE. BC-WF: SWWWIHEAD, SWW_CONT, SWWLOGHIST, SWWUSERWI, SWWORGTASK, SWFDEVINST, SWEINSTCOU, HRS1000, HRS1001, HRS1201, SWD_HEADER, SWOTLV, table_prefix SWW, SWF, SWP, SWE, SWD, SWO, HRS1; SAP_WAPI_*, SWW_WI_*, SWE_EVENT_CREATE, SWU_AGENT_RESOLVE, SWO_CREATE, RH_SAP_ORG_OBJEC_RELATE; class_prefix CL_SWF_, CL_SWH_, CL_SWW_, IF_WORKFLOW, BI_OBJECT, BI_PERSISTENT; tcode SWDD, SWIA, SWI1, SWI2_*, SWO1, SWE2, SWEL, SWU3, SBWP, PFTC, PFAC; authobj_prefix S_WF_; keyword workflow, work item, agent determination, business object, deadline, substitute. BC-ALE: EDIDC, EDIDD, EDID4, EDIDS, EDP13, EDP21, EDPAR, EDMSG, TBDLS, BDCP, table_prefix E1, Z1, Y1; MASTER_IDOC_DISTRIBUTE, IDOC_INBOUND_*, IDOC_INPUT_*, IDOC_OUTPUT_*, IDOC_WRITE_AND_START_INBOUND, EDI_DOCUMENT_*, ALE_MODEL_*, BAPI_IDOC_INPUT1, CHANGE_POINTERS_*; badi IDOC_DATA_MAPPER, IDOC_CREATION_CHECK, BDMO0001, BDPM0001-20; tcode WE02, WE05, WE19, WE20, WE21, WE30, WE31, WE57, WE81, WE82, BD64, BD87, SALE, SM58; authobj_prefix S_IDOC, B_ALE; keyword idoc, ale, edi, message type, partner profile, change pointer. BC-ESI: RFCDES, SRT_*, /IWFND/*, /IWBEP/*, SPROX*, SXMS*, ICF*; class_prefix /IWBEP/, /IWFND/, /UI2/, /UI5/, CL_SOAP_, CL_PROXY_, CL_HTTP_, CL_REST_, IF_HTTP_EXTENSION; tcode SEGW, SOAMANAGER, SPROXY, SICF, SM59, /IWFND/MAINT_SERVICE, /IWFND/ERROR_LOG, SXMB_MONI; authobj S_RFC, S_ICF, S_SERVICE; keyword odata, gateway, fiori, sapui5, web service, soap, wsdl, proxy, rest, rfc destination; name_prefix ZGW, ZOD, ZODATA, ZFIORI, ZUI5, ZWEBSERVICE, ZSOAP, ZPROXY, ZREST, ZHTTP, ZRFC, ZINTERFACE, ZINTEGRATION, ZAPI. BC-SEC: USR01, USR02, USR21, UST04, AGR_USERS, AGR_1251, AGR_DEFINE, USOBT, USOBX, TOBJ; BAPI_USER_*, SUSR_*, PRGN_*, AUTHORITY_CHECK_TCODE; tcode SU01, SU10, SU53, SU24, PFCG, SUIM, SU3; authobj_prefix S_USER; keyword authorization, authority check, role, user master, single sign-on; name_prefix ZAUTH, ZSEC, ZROLE, ZUSER. BC-SRV: TSP01-03, TNAPR, TOA01-03, TOAOM, SOOD, SOOS, SOST, BCST_*; function_prefix RSPO_, SSFCOMP_, SCMS_, ARCHIV_, SDOK_, ALSM_; name_prefix ZARCH; package_keyword PRINT, FORMS, OUTPUT, MAIL, ARCHIVE, FILE. BC-SRV-FORM: STXFADM, STXFADMI, FPCONTEXT, FPLAYOUT, FPINTERFACE; SSF_FUNCTION_MODULE_NAME, SSF_OPEN/CLOSE, FP_FUNCTION_MODULE_NAME, FP_JOB_OPEN/CLOSE, CONVERT_OTF, CONVERT_OTF_2_PDF, OPEN_FORM, WRITE_FORM, CLOSE_FORM; class_prefix CL_FP_, CL_SSF_; tcode SMARTFORMS, SFP, SE71-78; object_type SSFO, SFPF, SFPI, FORM, STYL; name_prefix ZSF, ZSMARTFORM, ZFORM, ZADOBE, ZAIF, ZSAPSCRIPT, ZPDF, ZOTF, ZPRINT, ZPRT. BC-SRV-MAIL: SOOD, SOOS, SOST, SOC3, SOFFCONT1, BCST_SR; SO_NEW_DOCUMENT_ATT_SEND_API1, SO_NEW_DOCUMENT_SEND_API1, SO_DOCUMENT_SEND_API1, SO_OBJECT_SEND; class_prefix CL_BCS, CL_DOCUMENT_BCS, CL_CAM_ADDRESS_BCS, CL_SAPUSER_BCS, CL_SEND_REQUEST_BCS; tcode SOST, SCOT, SO00-SO50; name_prefix ZMAIL, ZEMAIL, ZSENDMAIL, ZBCS, ZNOTIFY, ZALERT. BC-SRV-FILE: GUI_DOWNLOAD, GUI_UPLOAD, WS_DOWNLOAD, WS_UPLOAD, WS_FILENAME_GET, ALSM_EXCEL_TO_INTERNAL_TABLE, TEXT_CONVERT_XLS_TO_SAP, SAP_CONVERT_TO_XLS_FORMAT, FILE_GET_NAME, EPS_GET_DIRECTORY_LISTING, ARCHIVFILE_*, FTP_CONNECT, FTP_COMMAND, SCMS_XSTRING_TO_BINARY, SCMS_BINARY_TO_XSTRING; class_prefix CL_GUI_FRONTEND_SERVICES, CL_ABAP_ZIP, CL_ABAP_GZIP, CL_XLSX, CL_OPENXML, CL_FDT_XL_SPREADSHEET; tcode AL11, CG3Y, CG3Z, FILE; keyword file upload, download, excel, csv, flat file, application server, ftp, dataset; name_prefix ZFILE, ZUPLOAD, ZDOWNLOAD, ZEXCEL, ZXLS, ZXLSX, ZCSV, ZFTP, ZAL11, ZDATASET. BC-ABA: POPUP_TO_CONFIRM, POPUP_TO_DECIDE, POPUP_GET_VALUES, RS_VARIANT_CONTENTS, RS_REFRESH_FROM_SELECTOPTIONS, DD_DOMVALUES_GET, DDIF_FIELDINFO_GET, DDIF_NAMETAB_GET, TH_POPUP, ENQUEUE_E_TABLE, CONVERSION_EXIT_ALPHA_INPUT/OUTPUT, DATE_CHECK_PLAUSIBILITY, FACTORYDATE_CONVERT_TO_DATE, UNIT_CONVERSION_SIMPLE, CURRENCY_CONVERSION; class_prefix CL_ABAP_; name_prefix ZUTIL, ZUTILS, ZUTILITY, ZHELPER, ZTOOL, ZTOOLS, ZCOMMON, ZSHARED, ZFRAMEWORK, ZLIB, ZBASE, ZEXCEPTION, ZERROR, ZLOG, ZLOGGER, ZTRACE, ZDEBUG, ZTEST, ZUNITTEST, ZWRAPPER, ZADAPTER, ZFACTORY, ZSINGLETON; package_keyword UTIL, UTILS, HELPER, TOOLS, COMMON, SHARED, FRAMEWORK, LIB, CORE, GENERIC. BC-ABA-JOB: TBTCO, TBTCP, TBTCS, BTCEVTJOB; JOB_OPEN, JOB_SUBMIT, JOB_CLOSE, BP_JOB_SELECT, BP_EVENT_RAISE, BP_JOBLOG_READ, GET_JOB_RUNTIME_INFO; tcode SM36, SM37, SM62, SM64; keyword background job, batch job, job scheduling, job log; name_prefix ZJOB, ZBG. BC-CTS: E070, E071, E071K, TADIR, TDEVC, TRDIR, REPOSRC, D010SINF; TR_INSERT_REQUEST_WITH_TASKS, TR_RELEASE_REQUEST, TR_OBJECTS_CHECK, TRINT_TADIR_QUALIFY, RS_CORR_INSERT, RPY_PROGRAM_READ, SVRS_GET_VERSION_DIRECTORY_46, SEO_CLASS_READ, DDIF_TABL_GET; tcode SE01, SE09, SE10, SE03, STMS, SE80, SE38, SE37, SE24, SE11, SE16, SE16N, SE93, SPAU, SPDD, SNOTE, SCC1, SCU0; keyword transport, change request, tadir, version management, code inspector, atc; name_prefix ZCTS, ZTRANSPORT, ZTADIR, ZVERSION, ZSCI, ZATC. BC-BW: ROOSOURCE, ROOSFIELD, ROOSGEN, RSBASIDOC, RSISOSMAP, RSOLTPSOURCE, table_prefix ROOS, ROIS; RSAX_BIW_GET_DATA_SIMPLE, RSAX_BIW_GET_DATA, RSAP_BIW_GET_DATA; class_prefix CL_RSAX, CL_RSAP, CL_BW_; badi RSU5_SAPI_BADI, RSAP0001-10, RSR00001-10, RSROA_VARIABLES_EXIT; tcode RSA1-3, RSA5-9, RSO2-9, LBWE, LBWG, LBWQ, SBIW, RSPC; keyword bw, bi, extractor, datasource, infosource, delta queue, process chain; name_prefix ZBW, ZBIW, ZBI, ZEXTRACT, ZDATASOURCE, ZINFOSOURCE, ZDELTA, ZLBWE. BC-UI (weight 0.5): class_prefix CL_GUI_ALV_GRID, CL_SALV_, CL_GUI_CUSTOM_CONTAINER, CL_GUI_DOCKING_CONTAINER, CL_GUI_SPLITTER_CONTAINER, CL_GUI_CONTAINER, CL_GUI_CONTROL, CL_GUI_TEXTEDIT, CL_GUI_HTML_VIEWER, CL_GUI_TOOLBAR, CL_GUI_SIMPLE_TREE, CL_GUI_ALV_TREE, CL_DD_DOCUMENT, CL_WD_, CL_WDR_, CL_WDY_, CL_BSP_, CL_HTMLB_; REUSE_ALV_GRID_DISPLAY, REUSE_ALV_LIST_DISPLAY, REUSE_ALV_FIELDCATALOG_MERGE, REUSE_ALV_COMMENTARY_WRITE, LVC_FIELDCATALOG_MERGE, DYNP_VALUES_READ, DYNP_VALUES_UPDATE, F4IF_INT_TABLE_VALUE_REQUEST, F4IF_FIELD_VALUE_REQUEST; object_type WDYN, WDYA, WDCA, WDCC, BSP, WAPA, SMIM, W3MI, W3HT; keyword alv, alv grid, sap gui, dynpro, selection screen, module pool, f4 help, search help, web dynpro, bsp; name_prefix ZUI, ZALV, ZDYNPRO, ZSELSCREEN, ZF4, ZSHLP, ZSEARCHHELP, ZWD, ZWEBDYNPRO, ZBSP.
- CA root: keyword cross-application; name_prefix ZCA, ZXAPP, ZCROSS; package_keyword CA, CROSS, XAPP. CA-BP: BUT000, BUT020, BUT021, BUT050-053, BUT100, BUT0BK, BUT0ID, TB001-TB099, CVI_CUST_LINK, CVI_VEND_LINK; BAPI_BUPA_*, BAPI_BUPR_*, BUPA_*, CVI_*; class_prefix CL_BUPA, CL_CVI, CL_MDG_BS_BP; tcode BP, BUP1-9, BUSP; authobj_prefix B_BUPA; name_prefix ZBP, ZBUPA, ZBUSINESSPARTNER, ZPARTNER, ZCVI. CA-ADR: ADRC, ADR2, ADR3, ADR6, ADRP, ADRT, ADCP, TSAD3, T005; ADDR_GET, ADDR_GET_COMPLETE, ADDR_INSERT, ADDR_UPDATE, ADDR_DELETE, ADDR_SEARCH, ADDRESS_INTO_PRINTFORM, BAPI_ADDRESSORG_*, BAPI_ADDRESSPERS_*; class_prefix CL_ADDR, CL_ADDRESS, CL_SZA; tcode SZAD, SZA0-9; authobj_prefix S_ADDRESS; name_prefix ZADR, ZADDR, ZADDRESS, ZCAM. CA-DMS: DRAW, DRAD, DRAT, DRAO, DRAP, DRAZ, TDWA, TDWS, TDWO, TDWP; BAPI_DOCUMENT_*, CVAPI_DOC_*, CV120_DOC_*; class_prefix CL_DMS, CL_DOCUMENT, CL_CV_, CL_CVAPI; tcode CV01N-04N, CV01-99, OAC0-3, DC10-90; authobj_prefix C_DRAW; keyword document management, dms, document info record, content server, kpro; name_prefix ZDMS, ZDIR, ZDOCINFO, ZKPRO. CA-CL: KLAH, KSSK, KSML, AUSP, CABN, CABNT, CAWN, CAWNT, TCLA, TCLS, TCLO, TCLT, INOB; BAPI_OBJCL_*, BAPI_CLASS_*, BAPI_CHARACT_*, CLAF_CLASSIFICATION_OF_OBJECTS, CLAF_OBJECTS_OF_CLASS, CLFM_SELECT_AUSP; class_prefix CL_CLASSIFICATION, CL_CLASS, CL_CHARACTERISTIC, CL_CLAF, CL_CLFM; badi_prefix CLFM; tcode CL01-31, CL20N, CL22N, CL24N, CL30N, CL6AN, CL6BN, CT01-30; authobj_prefix C_KLAH, C_TCLA, C_TCLS, C_CABN; keyword classification, class type, characteristic value, code group, selected set; name_prefix ZCLASSIF, ZCLASSIFICATION, ZCHARACT, ZCHARVAL, ZCLASSTYPE. CA-GEN: CDHDR, CDPOS, NRIV, TNRO, STXH, STXL, TVARV, TVARVC, TCURR, TCURX, TCURC, T247, T246, TFACD, TFACS, THOC, THOL; CHANGEDOCUMENT_OPEN/CLOSE/SINGLE_CASE/MULTIPLE_CASE/READ_HEADERS/READ_POSITIONS, NUMBER_GET_NEXT, NUMBER_RANGE_ENQUEUE, READ_TEXT, SAVE_TEXT, DELETE_TEXT, COMMIT_TEXT, UNIT_CONVERSION_SIMPLE, CONVERT_TO_LOCAL_CURRENCY, CONVERT_TO_FOREIGN_CURRENCY, READ_EXCHANGE_RATE, BAPI_EXCHANGERATE_*, DATE_TO_PERIOD_CONVERT, DATE_CONVERT_TO_FACTORYDATE, FACTORYDATE_CONVERT_TO_DATE, LAST_DAY_OF_MONTHS, RS_VARIANT_CONTENTS, RS_CREATE_VARIANT; class_prefix CL_CHANGEDOCUMENT, CL_NUMBER_RANGE; tcode SCDO, SNRO, SNUM, SO10, CUNI, OB08, OB07, SCAL, STVARV, SM30, SM31, SM34; keyword change document, change log, audit trail, number range, long text, standard text, unit of measure, exchange rate, factory calendar, holiday calendar, selection variant, table maintenance; name_prefix ZGEN, ZCAGEN, ZCHGDOC, ZCHANGEDOC, ZAUDIT, ZNR, ZNUMRNG, ZNUMBERRANGE, ZNRIV, ZLONGTEXT, ZSTDTEXT, ZREADTEXT, ZUOM, ZUNIT, ZCURR, ZCURRENCY, ZEXCHRATE, ZCAL, ZCALENDAR, ZFACTORYCAL, ZHOLIDAY, ZVARIANT, ZTVARV, ZTABMAINT, ZSM30.

### 5.3 Business-process dimension
`tools/taxonomy/processes.json`: `{version, source: "local", groups:[{id, name, modules:[{id, name, description}]}]}`
with groups L2C Lead to Cash (QUOTE, ORDER, DELIVER, INVOICE, SERVICE, CUSTOMER), S2P Source to Pay (SOURCE,
PROCURE, SERVICES, INVOICE, SUPPLIER), P2F Plan to Fulfill (PLAN, PRODUCE, INSPECT, INVENTORY, WAREHOUSE,
TRANSPORT, PRODUCT), R2R Record to Report (LEDGER, CLOSE, COST, PRODUCTCOST, PROFIT, TAX, CASH), H2R Recruit
to Retire (HIRE, ADMIN, TIME, PAY, DEVELOP, REWARD, TRAVEL), A2D Acquire to Decommission (ASSET, MAINTAIN),
I2M Idea to Market (DESIGN, PROJECT), GOV Govern Enterprise Data (PARTNER, COMMON), TEC Technology and
Integration (INTEGRATE, WORKFLOW, OUTPUT, SECURE, OPERATE, REPORT), AND Aerospace and Defense solution
facets (GPD Group/Peg/Distribute, PROGRAM project manufacturing, GOVCON government contract accounting,
EFFECT configuration control and effectivity, MRO maintain/repair/overhaul, PEO S/4 production engineering
and operations as a target concept); 10 groups, 50 modules; module ids are `GROUP.NAME`.
A&D rules live in `rules_and.json` (PS-GPD: PEG_/GPD_ prefixes, PEG/GRM/DIS0 tcodes, pegging/grouping/
distribution keywords; CO-GOV: AD01*/DP90 resource-related billing, cost-plus/progress billing/earned
value/DCAA keywords; PM-MRO: ADPM*/ADSUBCON*/ADFLT* objects, rotable/overhaul/flight-log keywords; LO-EFF:
EFFV*/AENR/AEOI change management, effectivity/as-built keywords) and are explicitly marked as unverified
against a real system. Crosswalk: PS-GPD -> AND.GPD (+ AND.PROGRAM supporting, I2M.PROJECT context);
CO-GOV -> AND.GOVCON (+ R2R.COST supporting, L2C.INVOICE context); PM-MRO -> AND.MRO (+ A2D.MAINTAIN
supporting, L2C.SERVICE context); LO-EFF -> AND.EFFECT (+ P2F.PRODUCT supporting, I2M.DESIGN context).
`tools/taxonomy/crosswalk.json`: `{version, map: {"<taxonomy node>": [{process, role}]}}` for every module
and the submodules whose process differs from the module's (FI-AP -> S2P.INVOICE direct + R2R.LEDGER
supporting; FI-AR -> L2C.INVOICE; FI-AA -> A2D.ASSET; FI-TV -> H2R.TRAVEL; CO-PC -> R2R.PRODUCTCOST; CO-PA ->
R2R.PROFIT; MM-IM -> P2F.INVENTORY; MM-IV -> S2P.INVOICE; MM-PUR-CON -> S2P.SOURCE; MM-SRV -> S2P.SERVICES;
LO-* -> P2F.PRODUCT/INVENTORY; SD-BIL -> L2C.INVOICE; SD-BF-PR -> L2C.QUOTE; LE-SHP -> L2C.DELIVER; LE-WM ->
P2F.WAREHOUSE; LE-TRA -> P2F.TRANSPORT; PP-MRP -> P2F.PLAN; QM -> P2F.INSPECT; PM -> A2D.MAINTAIN; PS ->
I2M.PROJECT; HCM-PT -> H2R.TIME; HCM-PY -> H2R.PAY (+ R2R.LEDGER supporting for HCM-PY-POST); HCM-PD/PE ->
H2R.DEVELOP; HCM-BN/CM -> H2R.REWARD; HCM-RC -> H2R.HIRE; BC-* -> TEC.*; CA-BP/ADR -> GOV.PARTNER; CA-DMS/CL ->
I2M.DESIGN; CA-GEN -> GOV.COMMON; UNKNOWN -> none). `common.load_processes(dir)` returns a `ProcessCatalog`
(groups, modules, crosswalk, `defaults_for(tax, node)` = entries of the most specific node or ancestor,
`label(id)`, `brief()`); it validates ids and roles (direct | supporting | context).
merge derives `process` per object: explicit `process` list from the LLM/review record if present (basis =
source) else crosswalk of the primary node plus crosswalk `direct` entries of each secondary node with the
secondary's role (basis crosswalk). Batch files carry `processes` (catalog brief) and `process_default` per
object; the classifier sets `process` only to override. tree.md gets a "by business process" section, the CSV
`process_primary`, `process_primary_name`, `process_all`, `process_basis`, and the explorer a
"group by SAP module | business process" select plus a process filter (process view: group > module > role).

## 6. Stage 0: `tools/unchunk.py` (chunked exports)

For each system with `format: chunks`:
1. Each subfolder of `root` is a package. Collect files matching `chunk_glob`; parse `<prefix>_<NNNN>.<ext>`;
   group by prefix, sort numerically, warn on gaps; **concatenate raw strings with no separator** (a chunk
   may end mid-line). Decode with `read_text`.
2. Detect the marker: `object_marker` from config (regex, named groups `type` optional and `name`), else the
   first built-in with >= 2 hits in the first 200k chars:
   `^\*{2,}\s*(?:OBJECT|OBJ|BEGIN)(?:\s+OF)?\b[:\s]*(?P<type>[A-Z]{4}\b)?[:\s]*(?P<name>/?[A-Z][A-Z0-9_/]+)?`;
   `^[\*"]\s*#{2,}\s*(?P<type>[A-Z]{4}\b)?\s*(?P<name>...)?`; `^\*&\s*(?:Report|Include|Program)\s+(?P<name>\S+)`;
   `^(?:REPORT|PROGRAM|FUNCTION-POOL)\s+(?P<name>...)|^CLASS\s+(?P<name2>...)\s+DEFINITION\b(?!.*\b(?:LOCAL|DEFERRED|LOAD)\b)|^INTERFACE\s+(?P<name3>...)\s+PUBLIC`.
   Note type and name are optional so a marker without a usable name still starts a segment.
   Save `{sys|pkg: {marker, pattern, chunks, chars}}` to `work/unchunk_format.json`.
3. Split into segments at marker lines (comment-style markers are dropped; statement-style markers stay in
   the segment). Infer type/name from the segment's first statement when the marker lacks them:
   `REPORT/PROGRAM` -> PROG; `FUNCTION-POOL` -> FUGR; `CLASS x DEFINITION` (not LOCAL/DEFERRED/LOAD, not
   LCL_/LTCL_) -> CLAS; `CLASS x IMPLEMENTATION` -> CLAS (merged into the same object); `INTERFACE x PUBLIC`
   -> INTF; `FUNCTION x.` -> FUNC; `*& Include X` header box -> PROG with flag include.
4. Assemble: FUNC segments attach as function modules to the most recent FUGR, else to a synthetic group
   named from the FM name (`Z_WF_HR_START` -> `ZWF_HR`) with flag `synthetic_fugr`; a FUGR segment that
   itself contains `FUNCTION ... ENDFUNCTION` blocks has them split out. Description = first meaningful
   header comment line (skip decoration, "Report X", "OBJECT ...").
5. Write abapGit-style files into `work/unchunked/<SYS>/<pkg lower>/` (PROG: `.prog.abap` + `.prog.xml`
   with TPOOL ID R title; CLAS: `.clas.abap` + VSEOCLASS/DESCRIPT xml; INTF; FUGR: `.fugr.xml` with AREAT and
   FUNCTIONS items, `.fugr.l<fg>top.abap`, `.fugr.<fm>.abap` per FM; `package.devc.xml`). Write
   `_manifest.jsonl` (system, package, type, name, description, fms, lines, segments range, flags, source,
   files, sig). Idempotent per package: signature = sha1 of chunk file names+sizes+mtimes; unchanged packages
   are skipped and keep their manifest rows and their previously unresolved segments.
6. Unresolved segments -> `work/unchunk_unresolved/<SYS>/<pkg>/<seq>.txt` and
   `work/unchunk_unresolved.json` `{"segments":[{id "SYS|PKG|NNNNN", system, package, seq, marker, start_line,
   lines, file, head (first 60 lines)}]}`.
7. `--inspect [SYS] [PKG]` prints chunk files, gaps, detected marker and the first 10 marker lines, or the
   first 15 lines and advice to set `object_marker`. `--apply-resolution` reads
   `work/unchunk_resolution.json` `{"results":[{"segment": id, "type": PROG|CLAS|INTF|FUGR|FUNC|SKIP,
   "name": ..., "parent_fugr": ...}]}` and writes the files (FUNC appends to an existing group's xml), marks
   `source: llm` in the manifest, removes resolved ids from the unresolved file. `--force` rebuilds all.
Summary: `UNCHUNK_OK systems= packages= objects= fms= unresolved= unchanged_packages= out=`.

## 7. Stage 1: `tools/inventory.py`

Walk `cfg.system_root(system)` (error "run unchunk first" for chunk systems without a rebuild). Read
`package.devc.xml` CTEXT per folder (package = folder name upper; `.abapgit.xml` FOLDER_LOGIC PREFIX joins the
folder chain with `_`). One record per `(system, TYPE, NAME)`:
```
{key, system, company, type, name, package, package_path, package_desc, description, files[], source_files[],
 xml_file, children[{type:"FUNC", name, description, remote}], refs{TAG:[values]}, extra{}, loc, source_hash,
 header_comments[<=12], fm_sources{FM: file}}
```
Descriptions from xml by type (CLAS/INTF DESCRIPT; PROG TPOOL item ID R, plus PROGDIR LDBNAME/SUBC into
extra; FUGR AREAT and FUNCTIONS FUNCNAME/SHORT_TEXT; TABL DD02V DDTEXT and DD03P fields into extra; DTEL/
DOMA/TTYP/VIEW/SHLP DDTEXT; MSAG STEXT; TRAN TTEXT and TSTC PGMNA; ENHO/ENHS SHORTTEXT; SXCI TEXT; DDLS
DDTEXT; generic fallback list DESCRIPT, DDTEXT, CTEXT, STEXT, TTEXT, SHORTTEXT, AREAT, TEXT, DESCRIPTION).
`refs` collects these xml tags upper-cased: SPOT_NAME, BADI_DEF, EXIT_NAME, ORIGINAL_OBJECT, PROGRAM,
PGMNA, CLSNAME, IMPL_CLASS, ROLLNAME, DOMNAME, CHECKTABLE, SELMETHOD, TABNAME, ROWTYPE, LDBNAME, SUPERCLASS,
REFCLSNAME, FUNCNAME, INCLUDE, TRANSACTION, TCODE, FORMNAME. For SSFO, SFPF, SFPI, DDLS, DCLS, WDYN, W3MI,
IWPR, SRVD, SRVB, ENHO, SXCI, VIEW also store `extra.xml_tokens` = up to 400 upper-case tokens of the xml.
Source files = `.abap`, `.asddls`, `.asdcls`, `.asbdef`, `.js`, `.xslt`. `loc` = comment-free line count;
`source_hash` over all source files. FM source mapping: `<fg>.fugr.<fm>.abap` where `<fm>` is in the
FUNCTIONS list. Summary `INVENTORY_OK objects= systems= file=`.

## 8. Stage 2: evidence, batches, LLM, merge, overlaps

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
- `tools/status.py`: roots OK/MISSING (+ unchunk state for chunk systems), inventory counts, evidence
  auto/needs_llm, batches prepared/with results/pending, classification stats, overlaps summary, review patch
  presence, output files with sizes, and a final `NEXT: <command>` line.

## 11. OpenCode files

`opencode.json`: `$schema https://opencode.ai/config.json`, `model "azure/az-gpt-5.6-terra"`,
`small_model "azure/az-gpt-5.6-luna"`, `instructions ["AGENTS.md"]`, `permission.edit {"*": deny,
"work/**": allow, "output/**": allow, "migration.config.json": ask, "tools/taxonomy/rules_custom.json": ask}`,
`permission.shell {"*": ask, "py tools/*": allow, "py -I tools/*": allow, dir/ls/type/cat/findstr/grep/wc/
head/tail *: allow}`, `webfetch deny`, `task {"*": deny, "abap-*": allow}`.

Agents (`.opencode/agents/<name>.md`, frontmatter `description`, `mode`, `model`, `temperature`, `steps`,
`permission` with the same edit/shell/task keys):
- `sap-migration` (primary, terra, 0.2): orchestrator. Body: roots are read-only; run the Python tools and
  read their `*_OK` line; LLM work only via subagents on prepared files; never classify inline; everything
  resumable; process at most `batches_per_run` batches per /classify and report the remainder; taxonomy ids
  are the contract; answer data questions with status.py or a one-liner, never by loading big files; the
  stage list 0-7; report style short with a small table and the next command.
- `abap-splitter` (subagent, terra, 0.1, edit only work/unchunk_resolution.json): names unresolved
  segments; rules for PROG/CLAS/INTF/FUGR/FUNC/SKIP as in section 6; never invent a name.
- `abap-classifier` (subagent, terra, 0.1, steps 12, edit only work/llm/**): reads one batch file; decides
  by evidence strength in this order: enhancement targets, standard tables, standard FMs/classes, logical
  DB/infotypes/macros, transactions/message classes/auth objects, dependency hints, names and comments
  (package names are often WRONG, weak hint, flag mislabeled-package). Rules: HR approval workflows ->
  HCM-WF not BC-WF; technical helpers -> BC-ABA/BC-SRV-*/BC-UI, but a helper used by one module -> that
  module with flag utility; IDoc/OData/RFC for one module's documents -> that module with flag interface,
  generic plumbing -> BC-ALE/BC-ESI; prefer the heuristic pick when the excerpt agrees; most specific
  defensible level, null rather than guess; UNKNOWN only with no evidence and confidence <= 0.3;
  confidence calibration 0.9+ / 0.7-0.9 / 0.5-0.7 / < 0.5; purpose is one business sentence a manager
  understands. Output exactly `work/llm/<batch_id>.json` per 8.3, every object exactly once.
- `abap-reviewer` (subagent, sol, 0.1, steps 20, edit only work/review_patch.json and work/review.md):
  consistency rules (same name same purpose -> same class in all systems; one FUGR -> one module unless
  genuinely mixed; package outliers need positive evidence; helpers per usage; HR workflows -> HCM-WF;
  UNKNOWN only with empty evidence, flag needs-human); writes patch (corrections only) and a report with
  systematic problems and up to 20 objects for a human.
- `abap-architect` (subagent, sol, 0.2, steps 20, edit only output/target_packages.md): writes the target
  design with sections executive summary (table), naming convention (prefix, depth, where utilities,
  interfaces and company-specific variants live, `_<COMPANY>` suffix packages), hierarchy with counts (merge
  areas < 5 objects into the submodule), overlap resolution rules (identical keep one; diverged top 30 with
  rename-and-keep vs merge-behind-switch; similar review list), triage backlog by package, migration
  sequence from uses/used_by, numbered open decisions. Cite real names and counts, under ~4 pages.

Commands (`.opencode/commands/<name>.md`, frontmatter `description`, `agent: sap-migration`, optional
`model`): shell output is injected with `` !`py tools/<script>.py --config migration.config.json $ARGUMENTS` ``,
then instructions.
- `inspect-chunks` (luna): unchunk.py --inspect $ARGUMENTS; relay; propose an object_marker regex if none.
- `unchunk`: unchunk.py; if unresolved > 0 invoke abap-splitter via Task, then `--apply-resolution`; next /inventory.
- `inventory` (luna): inventory.py; table of counts; next /classify.
- `classify`: evidence.py; prep_batches.py $ARGUMENTS; pending.py; then invoke abap-classifier once per id
  on the THIS_RUN line, in parallel Task calls, prompt "Classify batch work/batches/<id>.json and write
  work/llm/<id>.json."; then merge.py and overlaps.py; report counts, merge errors, overlaps, remaining
  batches ("run /classify again or loop it"); if nothing pending, just merge and overlaps.
- `review`: review_candidates.py; invoke abap-reviewer once; merge.py --apply-review; overlaps.py; report.
- `explorer` (luna): render_html.py $ARGUMENTS; report path/size.  `tree` (luna): render_tree.py.
- `target-packages`: target_skeleton.py $ARGUMENTS; invoke abap-architect once; report.
- `status` (luna): status.py; repeat NEXT.

Skills (`.opencode/skills/<name>/SKILL.md`, frontmatter `name`, `description`): `sap-module-taxonomy`
(table of modules and signals, placement rules for ambiguous code, how to add rules_custom.json),
`abapgit-layout` (file naming table, xml description fields, chunked layout and what unchunk does),
`classification-rules` (pipeline, scoring, thresholds, LLM record contract, re-run and tuning tips).

`AGENTS.md`: hard rules (read-only roots; write only work/ and output/; `py` not python3; stdlib only; run
scripts, do not re-implement; LLM only in subagents on prepared files; taxonomy ids are the contract;
batches_per_run; do not load big files into context), the "where things are" table, the models table, and
how to resume. `README.md`: setup, command table, suggested order, memory/time notes, chunked exports,
models (provider prefix note), how classification works, layout.

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
