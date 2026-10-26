---
description: Stage 3 - consistency review of the classification; this command runs as the abap-reviewer subagent (Sol), then applies its patch. Optional but recommended before management sees the explorer.
agent: abap-reviewer
subtask: true
---
Stage 3 (review).

Review candidates (already computed):
!`py tools/review_candidates.py --config migration.config.json`

1. Do your job: review `work/review_candidates.json`, write `work/review_patch.json` and `work/review.md`.
   If the REVIEW_CANDIDATES_OK line shows no candidates at all, write an empty patch (`[]`) and a one-line report.
2. Then run `py tools/merge.py --config migration.config.json --apply-review`
   and `py tools/overlaps.py --config migration.config.json`.
3. Report: number of candidates per group, number of corrections applied (review_applied in MERGE_OK),
   and the systematic findings from work/review.md (quote its summary section).
4. Suggest `/explorer` to regenerate the management deliverable.
You run as a subagent: the user sees only your final message, so put the whole report there (short, numbers in a small table, then the next command to run).
