# Step 11: End-to-end verification and handover checklist

> This is step 11 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

No new code. Verify the whole build and hand it over.

## Acceptance check

1. `py -I tools/tests/test_pipeline.py`: 4 tests, all OK.
2. Point `migration.config.json` at one real system and run `/inventory`; the object and package counts must match the export.
3. `/classify --limit 1`: inspect `work/llm/<id>.json` (valid ids, business-sentence purposes) and `work/merge_report.md` (no validation errors).
4. `/explorer` and open the file: the module split looks plausible; fix taxonomy misses in `tools/taxonomy/rules_custom.json` before the full run.
5. Record in the README which steps were rebuilt by which model and date, and which acceptance checks were run.
