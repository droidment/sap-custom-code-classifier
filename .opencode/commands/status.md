---
description: Show pipeline state (what exists in work/ and output/) and the next command to run.
agent: sap-migration
subtask: true
model: azure/az-gpt-5.6-luna
---
Pipeline status:
!`py tools/status.py --config migration.config.json`

Relay this to the user as a short list and repeat the NEXT line as the recommended next command.
You run as a subagent: the user sees only your final message, so put the whole report there (short, numbers in a small table, then the next command to run).
