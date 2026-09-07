# UA FREE Content Tool v1.4.0-rc25

RC25 replaces the sequential recovery wrapper with a health-aware provider pool after live RC24 runs still exhausted every AI route on ordinary rewrites.

## AI Router

- Builds a route plan from configured providers, active circuit breakers, recent success, latency, and failure history before each task.
- Prefers recently successful low-latency routes instead of blindly restarting from static priority on every click.
- Preserves provider diversity: the second NVIDIA/Groq/Cloudflare model is not tried before other healthy providers receive a chance.
- A quota response is treated as a provider-wide condition for the current task and cooldown. The same provider's second model is not burned immediately afterward.
- Authentication and configuration failures are provider-wide hard circuit breakers.
- Model errors, temporary transport failures, and bad output remain model-local.
- Expired cooldowns naturally enter half-open state on the next task; RC25 no longer force-clears quota/auth/config/model failures during automatic recovery.
- One model is attempted at most once per task.

## Transport

- OpenAI-compatible providers no longer fail solely because a successful HTTP response omitted or mislabelled the Content-Type header.
- The Router now checks HTTP status and parses the body as JSON directly. A 2xx non-JSON body is reported as a bad response instead of the misleading `Unexpected content type: <missing>` failure.

## Time budgets

- The 80-second absolute task budget from RC24 remains.
- Cloud route slices are compact so one unhealthy provider cannot consume the whole rewrite.
- Local Ollama/llama.cpp is a true final emergency route and is capped to a 12-second slice; it is skipped when less than 8 seconds remain.
- A failed local runtime receives a short circuit-breaker instead of eating 30+ seconds on every rewrite.

## Preserved fixes

- RC24 explicit live Codex model selection remains active; no implicit retired `gpt-5.5` default.
- RC23 background-task deadline protection remains active.
- RC22 provider diagnostics and encrypted AI-provider settings remain compatible.
- RC21 full-current-calendar-day Inbox coverage remains unchanged.

## Compatibility

- No database schema migration.
- Existing Data, sources, groups, queue, publication history, AI keys, Rowboat memory, media references, and settings are preserved.
