# Step 10: OpenCode agents, commands, skills and project docs

> This is step 10 of 11 of a staged rebuild. The project conventions in `00-context.md` apply to
> every step: standard-library Python invoked as `py`, read-only source roots, all state under `work/` and
> `output/`, one `*_OK` summary line per script, and the pitfalls list. Steps already completed are present in
> the working folder; do not rewrite them unless this step says so. Finish by running the acceptance check
> and reporting its output.

## Task

Write `opencode.json`, the four agent files, the nine command files, the three skills, `AGENTS.md` and `README.md` as specified in section 11. Pin no model anywhere (no `model` keys or `model:` lines): the TUI-selected model is used by the commands and inherited by the subagents. Agent prompts must match the JSON contracts of step 08 exactly (field names, allowed values).

## Specification

## 11. OpenCode files

`opencode.json`: `$schema https://opencode.ai/config.json`, NO `model`/`small_model` keys (the TUI-selected
model is used everywhere; older OpenCode versions reject unknown keys, so add nothing else), `instructions ["AGENTS.md"]`, `permission.edit {"*": ask,
"work/**": allow, "output/**": allow, "migration.config.json": ask, "tools/taxonomy/rules_custom.json": ask}` (the
catch-all must be `ask`, never `deny`: OpenCode forwards a parent agent's edit DENY rules into every subagent
session and evaluates them last, which would override the subagents' own allow rules and remove their
file-writing tool),
`permission.shell {"*": ask, "py tools/*": allow, "py -I tools/*": allow, dir/ls/type/cat/findstr/grep/wc/
head/tail *: allow}`, `webfetch deny`, `task {"*": deny, "abap-*": allow}`.

Agents (`.opencode/agents/<name>.md`, frontmatter `description`, `mode: subagent`, `temperature`, `steps`,
`permission` with the same edit/shell/task keys; NO `model` line, the subagent inherits the caller's model).
There is no orchestrator agent: the commands run in the user's default agent and AGENTS.md carries the rules.
- `abap-splitter` (0.1, steps 40, edit only work/unchunk_resolution.json): names unresolved
  segments; rules for PROG/CLAS/INTF/FUGR/FUNC/SKIP as in section 6; never invent a name.
- `abap-classifier` (0.1, steps 40, edit only work/llm/**; reads the batch once and creates the result in one call with its file-writing tool, Write or apply_patch on GPT models, never via shell/Python): reads one batch file; decides
  by evidence strength in this order: enhancement targets, standard tables, standard FMs/classes, logical
  DB/infotypes/macros, transactions/message classes/auth objects, dependency hints, names and comments
  (package names are often WRONG, weak hint, flag mislabeled-package). Rules: HR approval workflows ->
  HCM-WF not BC-WF; technical helpers -> BC-ABA/BC-SRV-*/BC-UI, but a helper used by one module -> that
  module with flag utility; IDoc/OData/RFC for one module's documents -> that module with flag interface,
  generic plumbing -> BC-ALE/BC-ESI; prefer the heuristic pick when the excerpt agrees; most specific
  defensible level, null rather than guess; UNKNOWN only with no evidence and confidence <= 0.3;
  confidence calibration 0.9+ / 0.7-0.9 / 0.5-0.7 / < 0.5; purpose is one business sentence a manager
  understands. Output exactly `work/llm/<batch_id>.json` per 8.3, every object exactly once.
- `abap-reviewer` (0.1, steps 60, edit only work/review_patch.json and work/review.md):
  consistency rules (same name same purpose -> same class in all systems; one FUGR -> one module unless
  genuinely mixed; package outliers need positive evidence; helpers per usage; HR workflows -> HCM-WF;
  UNKNOWN only with empty evidence, flag needs-human); writes patch (corrections only) and a report with
  systematic problems and up to 20 objects for a human.
- `abap-architect` (0.2, steps 60, edit only output/target_packages.md): writes the target
  design with sections executive summary (table), naming convention (prefix, depth, where utilities,
  interfaces and company-specific variants live, `_<COMPANY>` suffix packages), hierarchy with counts (merge
  areas < 5 objects into the submodule), overlap resolution rules (identical keep one; diverged top 30 with
  rename-and-keep vs merge-behind-switch; similar review list), triage backlog by package, migration
  sequence from uses/used_by, numbered open decisions. Cite real names and counts, under ~4 pages.

Commands (`.opencode/commands/<name>.md`, frontmatter `description` only: no `agent`, `model` or `subtask`,
so every command runs in the user's current agent with the TUI-selected model): shell output is injected with
`` !`py tools/<script>.py --config migration.config.json $ARGUMENTS` ``, then instructions; LLM stages are
delegated with the Task tool to the `abap-*` subagents, which `permission.task` in opencode.json allows.
- `inspect-chunks`: unchunk.py --inspect $ARGUMENTS; relay; propose an object_marker regex if none.
- `unchunk`: unchunk.py; if unresolved > 0 invoke abap-splitter via Task, then `--apply-resolution`; next /inventory.
- `inventory`: inventory.py; table of counts; next /classify.
- `classify`: evidence.py; prep_batches.py $ARGUMENTS; pending.py; then invoke abap-classifier once per id
  on the THIS_RUN line, in parallel Task calls, prompt "Classify batch work/batches/<id>.json and write
  work/llm/<id>.json."; then merge.py and overlaps.py; report counts, merge errors, overlaps, remaining
  batches ("run /classify again or loop it"); if nothing pending, just merge and overlaps.
- `review`: review_candidates.py; invoke abap-reviewer once; merge.py --apply-review; overlaps.py; report.
- `explorer`: render_html.py $ARGUMENTS; report path/size.  `tree`: render_tree.py.
- `target-packages`: target_skeleton.py $ARGUMENTS; invoke abap-architect once; report.
- `status`: status.py; repeat NEXT.
Every command ends with a short report: numbers in a small table, then the next command to run.

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

Start `opencode` in the folder in the default agent: `/inventory`, `/classify`, `/review`, `/explorer`, `/tree`, `/target-packages`, `/status`, `/unchunk`, `/inspect-chunks` appear, and `@abap-classifier` is listed. `grep -r "openai/" .opencode opencode.json` finds nothing. Then run `/status` against the fixture config copied to `migration.config.json` and confirm it prints a NEXT line.
