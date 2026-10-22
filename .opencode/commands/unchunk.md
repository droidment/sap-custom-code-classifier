---
description: Stage 0 (chunked exports only) - rebuild abapGit-style object files from .abapchunk chains into work/unchunked, then let abap-splitter name any leftover segments. Run before /inventory for systems with format "chunks".
agent: sap-migration
---
Run stage 0 (unchunk). The deterministic rebuild has already been executed; its output follows.

Unchunk output:
!`py tools/unchunk.py --config migration.config.json $ARGUMENTS`

The detected marker pattern per package is in `work/unchunk_format.json` (read it only if a package
looks wrong; a `marker: null` entry means nothing was detected).

1. If the UNCHUNK_OK line shows `unresolved=0`, report systems / packages / objects / function modules and
   say the next step is `/inventory`.
2. If `unresolved` > 0: invoke the `abap-splitter` subagent once with the Task tool. Prompt:
   "Resolve the segments in work/unchunk_unresolved.json and write work/unchunk_resolution.json."
   When it returns, run `py tools/unchunk.py --config migration.config.json --apply-resolution` and report
   the UNCHUNK_APPLY_OK counts (applied / skipped / invalid). Any `invalid` entries stay unresolved; list their
   ids so the user can look at the files under work/unchunk_unresolved/.
3. If a package shows marker `None`, tell the user to run `/inspect-chunks <SYS> <PKG>` and set
   `object_marker` for that system in migration.config.json.
4. End with: next step is `/inventory`.
