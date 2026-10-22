---
name: sap-module-taxonomy
description: The SAP module / submodule / area taxonomy used by this project (ids, meaning, where ambiguous code belongs) and how to extend it via tools/taxonomy/rules_custom.json. Load when deciding a classification or when the user asks what a node means.
---
# SAP module taxonomy (ECC 6.0)

The ids live in `tools/taxonomy/nodes.json`; the evidence rules in `tools/taxonomy/rules_*.json`.
Level 0 = module, level 1 = submodule, level 2 = area. A classification is a valid chain, e.g.
`HCM` > `HCM-PT` > `HCM-PT-TS`.

| Module | Meaning | Typical signals |
|---|---|---|
| HCM | Human Capital Management | PA*/PB*/HRP* tables, PNP/PNPCE/PCH, HR_*/RP_* FMs, INFOTYPES |
| HCM-PA / PT / PY / OM / PD / PE / BN / RC / CM / ESS / WF | Personnel admin, time, payroll, org mgmt, development, training, benefits, recruiting, compensation, self-service, HR workflows | HCM-PT-TS = CATS timesheet (CATSDB, CATS_*); HCM-PY-POST = posting to FI (PPOIX) |
| FI | Financial accounting | BKPF/BSEG, BAPI_ACC_*; FI-GL, FI-AP (+FI-AP-PAY payment run), FI-AR (+FI-AR-DUN), FI-AA, FI-BL bank, FI-TV travel, FI-SL, FI-TX, FI-CLS closing |
| CO | Controlling | CSKS/COEP/AUFK; CO-OM, CO-PC (KEKO, material ledger), CO-PA (CE1*), CO-PCA |
| MM | Materials management | MM-PUR (EKKO/EBAN, ME_*; areas PO, PR, CON), MM-IM (MKPF/MSEG; MM-IM-PI), MM-IV (RBKP), MM-SRV (ESLL) |
| LO | Logistics master data | LO-MD material master, LO-BM batches, LO-VC variant config, LO-HU handling units |
| SD | Sales | SD-SLS (VBAK), SD-BIL (VBRK), SD-BF (pricing SD-BF-PR, output SD-BF-OUT), SD-MD, SD-EDI |
| LE | Logistics execution | LE-SHP deliveries (LIKP), LE-WM warehouse (LTAK/LQUA), LE-TRA shipments (VTTK) |
| PP / PM / QM / PS | Production, maintenance, quality, projects | AFKO shared by PP/PS/PM; QMEL shared by QM/PM: decide by tcodes, BAPIs, BAdIs |
| FSCM | Credit (UKM*), collections/dispute (UDM*/FDM*) | |
| BC | Technical | BC-WF workflow tech, BC-ALE IDoc, BC-ESI interfaces/OData/RFC, BC-SEC authorizations, BC-SRV output (FORM/MAIL/FILE), BC-ABA utilities (+JOB), BC-CTS dev tools, BC-BW extractors, BC-UI ALV/Dynpro-only code |
| CA | Cross-application business | CA-BP business partner, CA-ADR addresses, CA-DMS documents, CA-CL classification, CA-GEN change docs / number ranges / texts / units / currencies |
| UNKNOWN | No usable evidence | confidence must be <= 0.3 |

## Placement rules for ambiguous code
- HR approval workflows (leave, time, PCR) -> HCM-WF, not BC-WF. Generic workflow tooling -> BC-WF.
- An interface (IDoc, OData, RFC wrapper) that moves one module's business documents belongs to that
  module with flag `interface`; generic plumbing -> BC-ALE / BC-ESI.
- A form (SmartForm/Adobe/SAPscript) printing a PO, invoice, payslip belongs to the business module
  (MM-PUR, SD-BIL, HCM-PY); a generic print/PDF utility -> BC-SRV-FORM.
- A Z-table or helper used by one module -> that module (flag `utility` for helpers); used by many -> BC-ABA
  or CA-GEN with flag `cross-module`.
- ALV/Dynpro/screen code is never evidence of a module; look at the data it shows.
- Payroll posting to FI (PPOIX, RPCIPE) is HCM-PY-POST, not FI.
- Vendor master = FI-AP (LFA1) unless it is purchasing views (LFM1 -> MM-PUR). Customer master = FI-AR
  (KNA1) unless sales views (KNVV -> SD-MD). Business partner (BUT000) = CA-BP.

## Extending the taxonomy
Add `tools/taxonomy/rules_custom.json` with `{"rules": [{"node": "<id>", "table": [...], "name_prefix": [...]}]}`.
Supported keys: table, table_prefix, type_ref, function, function_prefix, class, class_prefix, include,
include_prefix, ldb, infotype, infotype_range ([["2000","2999"]]), badi, badi_prefix, tcode, tcode_prefix,
msgclass, msgclass_prefix, authobj, authobj_prefix, keyword (lower-case text in descriptions/comments),
name_prefix (object name), package_keyword, object_type, weight (multiplier for the whole rule).
Typical use: your company's own Z-tables (`"table": ["ZHR_TS_LOG"]` -> HCM-PT-TS) and naming conventions
(`"name_prefix": ["ZXHR"]`). Re-run `/classify` after changing rules; auto-classified objects are recomputed,
LLM results are kept unless you delete `work/llm/`.
