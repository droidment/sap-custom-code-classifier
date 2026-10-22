---
description: Stage 4a - build the self-contained HTML explorer (output/explorer.html) for management. Optional argument: a page title in quotes.
agent: sap-migration
model: azure/az-gpt-5.6-luna
---
Build the HTML explorer. Output of the renderer:
!`py tools/render_html.py --config migration.config.json $ARGUMENTS`

Tell the user the file path and size, that it is a single offline file they can email or put on a share,
and how many objects / modules it contains. If the renderer failed because work/classification.json is
missing, tell them to run `/classify` first.
