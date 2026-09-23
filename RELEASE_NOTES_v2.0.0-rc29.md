# UA FREE Content Tool v2.0.0-rc29

Recovery release for the non-starting RC28 chat-distributed portable.

- Builds from the canonical RC28 runtime already stored in Drive/GitHub, not from the stale local RC28 ZIP.
- Adds one canonical root portable bootstrap and aligns the runtime sitecustomize with it.
- Clicking UA_FREE_Content_Tool.exe reaches content_agent.main instead of exiting silently.
- Early bootstrap failures are written to Data/logs/bootstrap_error.log and shown in a dialog when possible.
- Preserves the canonical RC28 V2 window and clean first-run importer.
- Manual-test marker keeps auto-update disabled until Windows startup is confirmed.
