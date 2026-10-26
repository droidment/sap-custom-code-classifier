---
name: abapgit-layout
description: How the abapGit export on disk is organised (file naming, object types, which xml fields carry descriptions, nested packages) and which stage reads what. Load when something in an export looks unexpected or an object seems missing from the inventory.
---
# abapGit export layout

One folder per package; `package.devc.xml` holds the package description (`<CTEXT>`). Subpackages are
subfolders. With `FOLDER_LOGIC` = FULL (the default we assume) the folder name is the package name; with
PREFIX the package name is the folder chain joined by `_`. `.abapgit.xml` at the root says which.

File name = `<object>.<type>.<rest>`; names are lower-case, namespaces `/NS/` are written `#ns#`.

| Type | Files | Where the description is |
|---|---|---|
| CLAS | `.clas.abap` (+ `.clas.locals_imp.abap`, `.clas.testclasses.abap`, `.clas.xml`) | VSEOCLASS/DESCRIPT |
| INTF | `.intf.abap`, `.intf.xml` | VSEOINTERF/DESCRIPT |
| PROG | `.prog.abap`, `.prog.xml` | TPOOL item with ID `R`; PROGDIR/LDBNAME = logical database |
| FUGR | `.fugr.xml` (AREAT, FUNCTIONS/FUNCNAME/SHORT_TEXT, INCLUDES), `.fugr.sapl<fg>.abap`, `.fugr.l<fg>top.abap`, one `.fugr.<fm_name>.abap` per function module | AREAT; FM texts in FUNCTIONS |
| TABL / VIEW / DTEL / DOMA / TTYP / SHLP | `.xml` only | DD02V/DD25V/DD04V/DD01V/DD40V/DD30V DDTEXT |
| ENHO / ENHS / SXCI | `.xml` (+ `.abap` for source plug-ins) | SHORTTEXT / TEXT; SPOT_NAME, BADI_DEF, EXIT_NAME, IMPL_CLASS = enhancement target |
| TRAN | `.tran.xml` | TSTCT/TTEXT; TSTC/PGMNA = program |
| MSAG | `.msag.xml` | T100A/STEXT |
| SSFO / SFPF / SFPI | `.xml` (form definitions incl. embedded code) | tokens scanned as evidence |
| DDLS / DCLS | `.ddls.asddls` / `.dcls.asdcls` + `.xml` | DDTEXT |
| WDYN / W3MI / SMIM / SICF | `.xml` (+ files) | DESCRIPT / TEXT / DESCRIPTION |

`tools/inventory.py` turns this into one record per object (`key = SYSTEM|TYPE|NAME`), lists FMs as children
of their FUGR, computes a comment-free source hash (for overlap detection) and keeps the first header
comment lines (often the most honest description of what a program does).

If an object type is not recognised, the file still appears in `files` of a record whose type is the
4-letter code from the file name, and the inventory log prints `warn unparsed_filename` for files that do
not match the pattern at all.

# Chunked export layout (`"format": "chunks"`)

Some systems are exported as plain-text chains: one folder per package (`ZDEV/`) containing
`z1_0001.abapchunk`, `z1_0002.abapchunk`, ... Chunks are size-based, so an object can be cut across two
files; objects are separated by marker lines; there is no metadata.

`tools/unchunk.py` (command `/unchunk`) concatenates the chunks of each package in numeric order, detects the
marker pattern (config `object_marker`, else built-ins: `###OBJECT SYS:TYPE:NAME` lines (SAP-side export; its
`###END_OBJECT` lines are dropped and `* ###END_PROGRAM SAPLxxx` names the function group of a FUNC),
`*** OBJECT <TYPE> <NAME>` comments, `*& Report X` header boxes, or plain `REPORT` / `CLASS x DEFINITION` / `INTERFACE x PUBLIC` / `FUNCTION-POOL` statements),
splits into segments, assembles objects (DEFINITION + IMPLEMENTATION of one class merge; `FUNCTION ...
ENDFUNCTION` blocks attach to the preceding `FUNCTION-POOL`, or to a synthetic group named from the FM prefix
with flag `synthetic_fugr`) and writes the abapGit-style files above into `work/unchunked/<SYS>/<package>/`.
Descriptions come from the first meaningful header comment. `_manifest.jsonl` lists every rebuilt object with
its segment range and flags. Segments it cannot name go to `work/unchunk_unresolved.json`; the
`abap-splitter` subagent names them and `unchunk.py --apply-resolution` writes them.

Use `/inspect-chunks SYS PKG` to see the chunk files, numbering gaps and the detected marker before the
rebuild. The pipeline then treats `work/unchunked/<SYS>` as that system's root; nothing downstream changes.
