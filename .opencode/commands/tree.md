---
description: Stage 4b - Markdown tree (output/tree.md), flat CSV for Excel (output/objects.csv) and a copy of classification.json in output/. Optional --systems S1D for a per-system tree_S1D.md / objects_S1D.csv.
agent: sap-migration
subtask: true
model: azure/az-gpt-5.6-luna
---
Render the tree and CSV. Output:
!`py tools/render_tree.py --config migration.config.json $ARGUMENTS`

Tell the user the three file paths and what each is for (tree.md to read, objects.csv to filter in Excel,
classification.json for other tools). If classification.json is missing, point them to `/classify`.
You run as a subagent: the user sees only your final message, so put the whole report there (short, numbers in a small table, then the next command to run).
