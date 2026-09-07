# UA FREE Content Tool v1.4.0-rc24

RC24 fixes the live failure where even a short six-source news block could not be rewritten because the Router exhausted providers/cooldowns and Codex still let its app-server choose a retired implicit `gpt-5.5` model.

## What changed

- Codex no longer trusts an implicit model default. It calls the SDK `models()` catalogue for the signed-in ChatGPT account and passes an available model explicitly to `thread_start` and `thread.run`.
- If the server-reported default model is retired between catalogue lookup and execution, Codex can try the next visible model in the same call only for a model-not-found error.
- The supported Codex install/update target is now `openai-codex==0.147.0`. Existing 0.144.4 Data remains usable because that SDK already supports `models()` and explicit `model=`.
- The stale RC23 cooldown created specifically by the retired implicit `gpt-5.5` failure is cleared on the first RC24 Router task.
- One rewrite now has a real 80-second Router budget below the UI watchdog, so background work cannot quietly outlive the visible operation again.
- Within one click, a model that already failed or returned invalid output is not retried during recovery.
- After a fresh provider failure, RC24 may recover a different route only from a short transient/bad-response cooldown. Quota, authentication, configuration and persistent model errors are never force-retried.
- RC21 full-current-day Inbox coverage and existing Data/queue/history/settings remain unchanged.

## Compatibility

- No database schema migration.
- Existing Data, sources, groups, queue, publication history, AI keys, Rowboat memory, media references and settings are preserved.
