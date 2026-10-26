# Step 03: Business-process catalog and module crosswalk

> This is step 03 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/taxonomy/processes.json` and `tools/taxonomy/crosswalk.json` as specified in section 5.3. The catalog is a LOCAL alias set in the style of SAP's Reference Business Architecture; mark it `source: local` with a version string. The `ProcessCatalog` loader from step 01 must load both and validate ids and roles.

## Specification

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
Group OTH "Other / revisit later" with the single module OTH.UNMAPPED (11 groups, 51 modules): merge falls
back to it (basis `default`) only for a classified object (source not `missing`, module not UNKNOWN) whose
node has no crosswalk entry; pending and UNKNOWN objects get an empty process list (explorer: "no process
assigned"). The classifier sets it explicitly, with a rationale naming the real process, when the object's
process is not in the catalog; review_candidates lists those objects as group `process_unmapped`.
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

## Acceptance check

`py -c "import sys;sys.path.insert(0,'tools');from common import load_processes,load_taxonomy;c=load_processes('tools/taxonomy');t=load_taxonomy('tools/taxonomy');print(len(c.groups),len(c.modules),c.defaults_for(t,'HCM-PT-TS'),c.defaults_for(t,'FI-AP'))"` prints 11 groups, 51 modules, `[{'process': 'H2R.TIME', 'role': 'direct'}]` and the two FI-AP entries. Every top-level taxonomy node except UNKNOWN must have a crosswalk entry (check with a loop).
