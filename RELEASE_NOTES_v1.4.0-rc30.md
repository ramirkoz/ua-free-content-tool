# UA FREE Content Tool v1.4.0-rc30

RC30 removes the split-brain AI runtime that let historical router layers overwrite newer timeout and failover rules.

- One canonical `content_agent.ai_router` owns provider ordering, timeout budgets, cooldowns, health, probes and UI tests.
- One canonical `content_agent.codex_runtime` owns Codex install, account status, explicit model selection and live requests.
- Active UI, rewrite, dedupe, provider diagnostics and queue migration consumers no longer import historical `ai_router_v*` or `codex_engine_v*` modules.
- Historical window classes now call a compatibility no-op `install_runtime()` and cannot downgrade the active router while the inheritance chain is built.
- Historical RC modules are no longer monkey-patched at runtime, so import/test order cannot mutate the live canonical router.
- Codex normal task slice is 45 seconds; manual Codex probe gets up to 75 seconds, and the UI watchdog is 90 seconds. The old 10/12-second live Codex path is gone from active code.
- Local fallback is attempted after the best cloud route, before the rest of the cloud pool, and its minimum budget is consistently 30 seconds.
- Rewrite profile now advertises the same 30-second local minimum the runtime actually uses.
- RC29 side-by-side Codex installation and automatic restart remain intact.
