# Step 06: Stage 0: rebuild chunked exports

> This is step 06 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `tools/unchunk.py` as specified in section 6 and un-skip `test_00_unchunk`. Pay attention to the pitfalls: raw concatenation, optional marker name, union of unresolved segments on re-runs.

## Specification

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

## Acceptance check

`py -I tools/unchunk.py --config tools/tests/fixtures/migration.config.json --inspect SYSC` names the detected marker; the rebuild reports `objects=5 fms=1 unresolved=1`; a second run reports `unchanged_packages=1` and still 1 unresolved; `--apply-resolution` with a mocked answer writes the file. test_00 and test_01 (including the SYSC hash equality) pass.
