# Staged rebuild prompts

Run these in order, one per OpenCode session (or one after another in the same session). Each prompt is self-contained apart from `00-context.md`, which carries the conventions every step must follow: give it to the model together with each step, or place it as `AGENTS.md` in the build folder.

| Step | Builds | Acceptance |
|---|---|---|
| [00](00-context.md) | Project context and conventions (read with every step) | Nothing to run. Confirm you have read the layout, the config shape, and the pitfalls, then... |
| [01](01-scaffold-common-nodes.md) | Scaffold, config, common.py and the taxonomy nodes | `py -c "import sys;sys.path.insert(0,'tools');from common import load_taxonomy;t=load_taxo... |
| [02](02-taxonomy-rules.md) | Taxonomy evidence rules | Load the taxonomy (`load_taxonomy('tools/taxonomy')`) with no error. Then write a 20-line ... |
| [03](03-process-catalog.md) | Business-process catalog and module crosswalk | `py -c "import sys;sys.path.insert(0,'tools');from common import load_processes,load_taxon... |
| [04](04-fixtures-and-test-harness.md) | Synthetic fixtures and the test harness | `py -I tools/tests/make_fixtures.py` creates SYS_A (6 objects in 2 packages), SYS_B (5 obj... |
| [05](05-inventory.md) | Stage 1: inventory | `py -I tools/inventory.py --config tools/tests/fixtures/migration.config.json` fails clean... |
| [06](06-unchunk.md) | Stage 0: rebuild chunked exports | `py -I tools/unchunk.py --config tools/tests/fixtures/migration.config.json --inspect SYSC... |
| [07](07-evidence-and-batches.md) | Stage 2a/2b: evidence scoring, propagation, batches | `py -I tools/evidence.py --config tools/tests/fixtures/migration.config.json` prints `EVID... |
| [08](08-merge-overlaps-review.md) | Stage 2c/2d/3a: merge, overlaps, review candidates | On the fixtures: merge reports `llm_invalid=1`; the classification carries secondary, proc... |
| [09](09-outputs.md) | Stage 4/5: explorer, tree, CSV, target packages, status | All four tests pass. Open `tools/tests/_tmp/output/explorer.html` in a browser: no console... |
| [10](10-opencode-files.md) | OpenCode agents, commands, skills and project docs | Start `opencode` in the folder in the default agent: `/inventory`, `/classify`, `/review`,... |
| [11](11-verification-and-handover.md) | End-to-end verification and handover checklist | 1. `py -I tools/tests/test_pipeline.py`: 4 tests, all OK.... |

The master specification these were cut from is `../REBUILD_PROMPT.md`; it stays the reference if a step prompt and the master ever disagree.
