# Step 10: OpenCode agents, commands, skills and project docs

> This is step 10 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `opencode.json`, the five agent files, the nine command files, the three skills, `AGENTS.md` and `README.md` as specified in section 11. Use the Azure model ids `azure/az-gpt-5.6-terra|sol|luna` and say in the README where to change the provider prefix. Agent prompts must match the JSON contracts of step 08 exactly (field names, allowed values).

## Specification

## 11. OpenCode files

`opencode.json`: `$schema https://opencode.ai/config.json`, `model "azure/az-gpt-5.6-terra"`,
`small_model "azure/az-gpt-5.6-luna"`, `instructions ["AGENTS.md"]`, `permission.edit {"*": deny,
"work/**": allow, "output/**": allow, "migration.config.json": ask, "tools/taxonomy/rules_custom.json": ask}`,
`permission.shell {"*": ask, "py tools/*": allow, "py -I tools/*": allow, dir/ls/type/cat/findstr/grep/wc/
head/tail *: allow}`, `webfetch deny`, `task {"*": deny, "abap-*": allow}`.

Agents (`.opencode/agents/<name>.md`, frontmatter `description`, `mode`, `model`, `temperature`, `steps`,
`permission` with the same edit/shell/task keys):
- `sap-migration` (subagent orchestrator, terra, 0.2): orchestrator. Body: roots are read-only; run the Python tools and
  read their `*_OK` line; LLM work only via subagents on prepared files; never classify inline; everything
  resumable; process at most `batches_per_run` batches per /classify and report the remainder; taxonomy ids
  are the contract; answer data questions with status.py or a one-liner, never by loading big files; the
  stage list 0-7; report style short with a small table and the next command.
- `abap-splitter` (subagent, terra, 0.1, edit only work/unchunk_resolution.json): names unresolved
  segments; rules for PROG/CLAS/INTF/FUGR/FUNC/SKIP as in section 6; never invent a name.
- `abap-classifier` (subagent, terra, 0.1, steps 12, edit only work/llm/**): reads one batch file; decides
  by evidence strength in this order: enhancement targets, standard tables, standard FMs/classes, logical
  DB/infotypes/macros, transactions/message classes/auth objects, dependency hints, names and comments
  (package names are often WRONG, weak hint, flag mislabeled-package). Rules: HR approval workflows ->
  HCM-WF not BC-WF; technical helpers -> BC-ABA/BC-SRV-*/BC-UI, but a helper used by one module -> that
  module with flag utility; IDoc/OData/RFC for one module's documents -> that module with flag interface,
  generic plumbing -> BC-ALE/BC-ESI; prefer the heuristic pick when the excerpt agrees; most specific
  defensible level, null rather than guess; UNKNOWN only with no evidence and confidence <= 0.3;
  confidence calibration 0.9+ / 0.7-0.9 / 0.5-0.7 / < 0.5; purpose is one business sentence a manager
  understands. Output exactly `work/llm/<batch_id>.json` per 8.3, every object exactly once.
- `abap-reviewer` (subagent, sol, 0.1, steps 20, edit only work/review_patch.json and work/review.md):
  consistency rules (same name same purpose -> same class in all systems; one FUGR -> one module unless
  genuinely mixed; package outliers need positive evidence; helpers per usage; HR workflows -> HCM-WF;
  UNKNOWN only with empty evidence, flag needs-human); writes patch (corrections only) and a report with
  systematic problems and up to 20 objects for a human.
- `abap-architect` (subagent, sol, 0.2, steps 20, edit only output/target_packages.md): writes the target
  design with sections executive summary (table), naming convention (prefix, depth, where utilities,
  interfaces and company-specific variants live, `_<COMPANY>` suffix packages), hierarchy with counts (merge
  areas < 5 objects into the submodule), overlap resolution rules (identical keep one; diverged top 30 with
  rename-and-keep vs merge-behind-switch; similar review list), triage backlog by package, migration
  sequence from uses/used_by, numbered open decisions. Cite real names and counts, under ~4 pages.

Commands (`.opencode/commands/<name>.md`, frontmatter `description`, `agent`, `subtask: true`, optional
`model`): every command runs as a subagent, so the user sees only its final report. Shell output is injected
with `` !`py tools/<script>.py --config migration.config.json $ARGUMENTS` ``, then instructions. `agent` is
`sap-migration` (a `mode: subagent` orchestrator, terra) unless stated; single-shot LLM stages run directly as
their subagent. `opencode.json` sets top-level `"subagent_depth": 2` so the `/classify` orchestrator may
launch classifier subagents, and `permission.task` allows `abap-*` and `sap-migration`.
- `inspect-chunks` (luna): unchunk.py --inspect $ARGUMENTS; relay; propose an object_marker regex if none.
- `unchunk` (agent abap-splitter): unchunk.py; if unresolved > 0 resolve the segments itself, then run
  `--apply-resolution`; next /inventory.
- `inventory` (luna): inventory.py; table of counts; next /classify.
- `classify`: evidence.py; prep_batches.py $ARGUMENTS; pending.py; then invoke abap-classifier once per id
  on the THIS_RUN line, in parallel Task calls, prompt "Classify batch work/batches/<id>.json and write
  work/llm/<id>.json." (on "Subagent depth limit reached" tell the user to set subagent_depth 2); then
  merge.py and overlaps.py; report counts, merge errors, overlaps, remaining batches ("run /classify again or
  loop it"); if nothing pending, just merge and overlaps.
- `review` (agent abap-reviewer): review_candidates.py; do the review itself; merge.py --apply-review;
  overlaps.py; report.
- `explorer` (luna): render_html.py $ARGUMENTS; report path/size.  `tree` (luna): render_tree.py.
- `target-packages` (agent abap-architect): target_skeleton.py $ARGUMENTS; write the design itself; report.
- `status` (luna): status.py; repeat NEXT.

Skills (`.opencode/skills/<name>/SKILL.md`, frontmatter `name`, `description`): `sap-module-taxonomy`
(table of modules and signals, placement rules for ambiguous code, how to add rules_custom.json),
`abapgit-layout` (file naming table, xml description fields, chunked layout and what unchunk does),
`classification-rules` (pipeline, scoring, thresholds, LLM record contract, re-run and tuning tips).

`AGENTS.md`: hard rules (read-only roots; write only work/ and output/; `py` not python3; stdlib only; run
scripts, do not re-implement; LLM only in subagents on prepared files; taxonomy ids are the contract;
batches_per_run; do not load big files into context), the "where things are" table, the models table, and
how to resume. `README.md`: setup, command table, suggested order, memory/time notes, chunked exports,
models (provider prefix note), how classification works, layout.

## Acceptance check

Start `opencode` in the folder: the `sap-migration` agent is the primary agent, `/inventory`, `/classify`, `/review`, `/explorer`, `/tree`, `/target-packages`, `/status`, `/unchunk`, `/inspect-chunks` appear, and `@abap-classifier` is listed. `grep -r "openai/" .opencode opencode.json` finds nothing. Then run `/status` against the fixture config copied to `migration.config.json` and confirm it prints a NEXT line.
