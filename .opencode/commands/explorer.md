---
description: Stage 4a - build the self-contained HTML explorer (output/explorer.html) for management. Args - optional --systems S1D (one or more ids, comma-separated; writes explorer_S1D.html) and --title "...".
agent: sap-migration
subtask: true
model: azure/az-gpt-5.6-luna
---
Build the HTML explorer. Output of the renderer:
!`py tools/render_html.py --config migration.config.json $ARGUMENTS`

Tell the user the file path and size, that it is a single offline file they can email or put on a share,
and how many objects / modules it contains. If the renderer failed because work/classification.json is
missing, tell them to run `/classify` first.
You run as a subagent: the user sees only your final message, so put the whole report there (short, numbers in a small table, then the next command to run).
