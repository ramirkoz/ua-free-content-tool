# UA FREE Content Tool v2.0.0-rc28

Architecture-cleanup manual-test build based on RC27 behavior.

- First launch now offers a clean read-only import from an older Content Tool folder/Data instead of copying the old Data directory wholesale.
- Only durable editorial/user state is migrated: sources, groups, articles, publication queue/status, editorial examples, feedback/exclusions/learning and settings. Logs, cache, old backups, runtime diagnostics and obsolete migration scratch state are left behind.
- Codex runtime moved from `Data/ai_runtime` to portable-root `Tools/Codex` and updated to `openai-codex==0.156.1`.
- Codex versions are bounded: active runtime plus one rollback copy. Old side-by-side versions no longer grow Data indefinitely.
- Active V2 window no longer uses the V2 `window_rc7 -> rc8 -> rc11` inheritance chain; media naming, resilient supervisor and auto-collect watchdog are consolidated into the canonical V2 window.
- Legacy window construction is hidden during startup so old RC5/RC6/RCxx titles cannot flash on screen; the visible title is always the current application version.
- Explicit clipboard buttons for API/access/page tokens were removed. Facebook Page tokens are treated as internal encrypted service data and are no longer exposed for copying.
- Facebook settings were simplified around connection status and page discovery; the user token remains only as a setup/recovery field.
- OpenRouter/AI provider sections no longer expose "copy secret" buttons or RC-number explanations.
- Updater preserves both `Data` and `Tools`.
