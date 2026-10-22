---
description: Stage 5 - propose the S/4HANA target package hierarchy and per-object move list (output/target_packages.md, output/object_moves.csv). Optional argument: --prefix Z_ (package prefix).
agent: sap-migration
---
Run stage 5 (target package design).

Draft hierarchy and move list (already computed):
!`py tools/target_skeleton.py --config migration.config.json $ARGUMENTS`

1. Invoke the `abap-architect` subagent once with the Task tool. Prompt:
   "Write output/target_packages.md from work/target_draft.json, output/target_packages_draft.md,
   work/overlaps.json and work/classification.json."
2. When it returns, report: number of target packages, counts of move / dedupe / resolve / triage actions,
   and the file paths output/target_packages.md and output/object_moves.csv. Quote the executive summary
   section of target_packages.md.
