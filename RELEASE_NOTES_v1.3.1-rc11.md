# UA FREE Content Tool v1.3.1-rc11

RC11 is a focused stability candidate over RC10.

## Rewrite reliability
- Prevents a second rewrite from starting while the previous timed-out worker is still shutting down.
- Codex gets a realistic bounded window for rewrite-sized prompts instead of being killed too early.
- Cloud fallbacks are exhausted before local inference.
- A stalled local runtime now receives a short cooldown instead of consuming the timeout on every click.
- Local rewrite fallback timeout is reduced; the total rewrite budget stays bounded.
- Full Rowboat memory export is no longer performed on every rewrite click; DB examples remain live and Rowboat can be synchronized explicitly.
- Rowboat synchronization writes only changed memory files.

## UI freeze mitigation
- Automatic 5-minute collection no longer rebuilds the full Inbox when zero new materials were collected.
- Successful rewrite no longer rebuilds the entire Inbox unnecessarily.
- Added a lightweight UI heartbeat watchdog. If Tk stops pumping events for 8+ seconds, `Data/ui_freeze_trace.log` receives all Python thread stacks for exact diagnosis.

## Compatibility
- No database schema change.
- Existing `Data` from RC10 is compatible.
- RC10 Inbox column layout is preserved.
