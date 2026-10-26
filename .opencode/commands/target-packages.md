---
description: Stage 5 - propose the S/4HANA target package hierarchy and per-object move list (output/target_packages.md, output/object_moves.csv); this command runs as the abap-architect subagent (Sol). Optional argument: --prefix Z_ (package prefix).
agent: abap-architect
subtask: true
---
Stage 5 (target package design).

Draft hierarchy and move list (already computed):
!`py tools/target_skeleton.py --config migration.config.json $ARGUMENTS`

1. Do your job: write `output/target_packages.md` from `work/target_draft.json`, `output/target_packages_draft.md`,
   `work/overlaps.json` and `work/classification.json`. If the TARGET_OK line is missing (classification not
   run yet), report that and stop.
2. Report: number of target packages, counts of move / dedupe / resolve / triage actions, and the file paths
   output/target_packages.md and output/object_moves.csv. Quote the executive summary section.
You run as a subagent: the user sees only your final message, so put the whole report there (short, numbers in a small table, then the next command to run).
