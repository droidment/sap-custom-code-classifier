---
description: Stage 4b - Markdown tree (output/tree.md), flat CSV for Excel (output/objects.csv) and a copy of classification.json in output/. Optional --systems S1D for a per-system tree_S1D.md / objects_S1D.csv.
---
Render the tree and CSV. Output:
!`py tools/render_tree.py --config migration.config.json $ARGUMENTS`

Tell the user the three file paths and what each is for (tree.md to read, objects.csv to filter in Excel,
classification.json for other tools). If classification.json is missing, point them to `/classify`.
Report short: numbers in a small table, then the next command to run.
