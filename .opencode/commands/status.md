---
description: Show pipeline state (what exists in work/ and output/) and the next command to run.
agent: sap-migration
model: azure/az-gpt-5.6-luna
---
Pipeline status:
!`py tools/status.py --config migration.config.json`

Relay this to the user as a short list and repeat the NEXT line as the recommended next command.
