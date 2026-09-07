# UA FREE Content Tool v1.4.0-rc22

RC22 fixes the AI Router lockout exposed in RC21: saved API keys and an authorized Codex session could still end in the generic `Немає доступного AI-провайдера` error when every configured route happened to be hidden behind persisted cooldown state.

## What changed

- Adds one RC22 routing layer and installs it before the legacy UI/runtime modules are imported, so current and compatibility AI workflows use the same recovery behavior instead of silently diverging between the old v1.2.1 and newer v1.2.2 routers.
- Prevents the 4096-token default path from falling back into the old legacy router. RC22 keeps the bounded/fair provider chain active for normal large-output calls as well.
- Replaces multi-hour accidental lockouts with bounded cooldown caps: temporary failures 90 seconds, malformed/validation responses 60 seconds, model errors 5 minutes, quota/rate-limit failures up to 10 minutes, configuration failures 10 minutes, and authentication failures 30 minutes.
- When all otherwise configured routes are hidden by non-authentication cooldowns, RC22 automatically re-probes cooled routes one at a time instead of immediately claiming that no AI provider exists.
- Authentication/configuration failures are not force-cleared by the automatic recovery pass. Saving corrected provider settings still resets cooldown state explicitly.
- Final router errors now include the actual provider state instead of the misleading generic `no provider` message.
- Adds a detailed `Живий стан AI-провайдерів` block in Settings. It distinguishes `not configured`, `available but not yet live-tested`, `last live check OK`, and `cooldown` states for Codex, Gemini, NVIDIA, Groq, Cloudflare and the local fallback.
- `Перевірити Codex` now checks both the ChatGPT session and a real minimal Codex AI request. An authorized account is therefore no longer presented as proof that Codex can actually answer the current workload.
- Keeps the current official `openai-codex==0.144.4` package pin. As of the RC22 build this is the latest release published on PyPI, so RC22 fixes runtime health semantics rather than inventing a nonexistent SDK upgrade.
- Adds regression coverage for bounded cooldown policy, persisted-reason classification, automatic recovery from a false all-cooldown lockout, and the single-router runtime patch.

## Compatibility

- No database schema migration.
- Existing Data, AI provider secrets, sources, groups, queue, publication history, media references, Rowboat memory and settings are preserved.
- RC21 full-day Inbox coverage remains inherited unchanged.
