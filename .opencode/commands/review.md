---
description: Stage 3 - consistency review of the classification by the abap-reviewer (Sol), then apply its patch. Optional but recommended before management sees the explorer.
agent: sap-migration
---
Run stage 3 (review).

Review candidates (already computed):
!`py tools/review_candidates.py --config migration.config.json`

1. Invoke the `abap-reviewer` subagent once with the Task tool. Prompt:
   "Review work/review_candidates.json, write work/review_patch.json and work/review.md."
2. When it returns, run `py tools/merge.py --config migration.config.json --apply-review`
   and then `py tools/overlaps.py --config migration.config.json`.
3. Report: number of candidates per group, number of corrections applied (review_applied in MERGE_OK),
   and the systematic findings from work/review.md (quote its summary section).
4. Suggest `/explorer` to regenerate the management deliverable.
