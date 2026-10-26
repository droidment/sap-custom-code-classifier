---
description: Stage 2 - score evidence, build LLM batches, classify the pending batches in parallel (one abap-classifier subagent per batch), merge, detect overlaps. Resumable; re-run until no batches remain. Args are passed to prep_batches (--limit 2 smoke test, --only-system S1D one system at a time, --min-confidence 0.6 re-run weak ones).
subtask: false
---
Stage 2 (classification). Deterministic parts have already been executed; their output follows.

Evidence scoring:
!`py tools/evidence.py --config migration.config.json`

Batch preparation (arguments: $ARGUMENTS):
!`py tools/prep_batches.py --config migration.config.json $ARGUMENTS`

Pending batches and the ones to process in this run:
!`py tools/pending.py --config migration.config.json`

Now do the LLM part:
1. Take exactly the batch ids listed on the THIS_RUN line above (none -> skip to step 3).
2. For each of those batch ids, invoke the `abap-classifier` subagent with the Task tool, in parallel
   (several Task calls in one message). The task prompt is exactly:
   "Classify batch work/batches/<batch_id>.json and write work/llm/<batch_id>.json."
   This command deliberately runs in your own (primary) agent, not as a subtask, so that these Task calls
   are first-level subagents and work on every OpenCode version. Never classify the objects yourself.
3. When they have all returned, run `py tools/merge.py --config migration.config.json` and then
   `py tools/overlaps.py --config migration.config.json`.
4. Report: auto vs LLM counts, objects per module (from the MERGE_OK / status output), validation errors
   from work/merge_report.md if any, the overlap summary, and how many batches are still pending.
   If batches remain, tell the user to run `/classify` again (it continues where it stopped) or to loop it.
   If none remain, say the classification is complete and suggest `/review` (optional) and `/explorer`.
If there were no pending batches at all, skip steps 1-2 and just run steps 3-4.
Report short: numbers in a small table, then the next command to run.
