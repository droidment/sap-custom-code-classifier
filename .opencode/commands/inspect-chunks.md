---
description: Look at a chunked export before rebuilding it - chunk files per package, numbering gaps, the detected object-marker pattern and the first markers. Args - optional system id and package name, e.g. "SYSC ZDEV".
agent: sap-migration
model: azure/az-gpt-5.6-luna
---
Chunk inspection:
!`py tools/unchunk.py --config migration.config.json --inspect $ARGUMENTS`

Relay the result. For each package say which marker pattern was detected and show the sample marker lines.
If a package says NONE DETECTED, quote the first lines and ask the user what separates objects in this
export, then propose a regex with named groups `type` (optional) and `name` for `object_marker` in
migration.config.json. Do not run the rebuild from here; the user runs `/unchunk` when satisfied.
