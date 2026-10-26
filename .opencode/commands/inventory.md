---
description: Stage 1 - inventory all abapGit objects from the configured system roots -> work/inventory.jsonl
---
Stage 1 (inventory). The script has already been executed; its output follows.

Inventory output:
!`py tools/inventory.py --config migration.config.json`

Summarise in a short table: objects per system, objects per type (top 10), number of packages, function
modules found, and any `warn` lines. If the output contains `ERROR root does not exist`, stop and tell the
user to fix the `root` paths in `migration.config.json`. If it says "run unchunk first", the next step is
`/unchunk`. Otherwise end with: next step is `/classify`.
Report short: numbers in a small table, then the next command to run.
