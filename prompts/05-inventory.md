# Step 05: Stage 1: inventory

> This is step 05 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/inventory.py` as specified in section 7 and un-skip `test_01_inventory` (keep the SYSC assertions skipped until step 06 if you prefer, or build 06 first).

## Specification

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

## Acceptance check

`py -I tools/inventory.py --config tools/tests/fixtures/migration.config.json` fails cleanly for SYSC (chunks not rebuilt yet) when SYSC is in the config; with SYSC removed or step 06 done, it prints `INVENTORY_OK objects=11` for SYSA+SYSB and the test_01 assertions pass (descriptions from xml, LDB PNP, FUGR children, package descriptions).
