# UA FREE Content Tool 2.0.0-rc62

Targeted Fact Guard repair-enablement on top of RC61, after operator LIVE telemetry 08.11.2026 ~15:40 Kyiv.

## Root cause confirmed
- RC61 is LIVE on `CONTENT-tonykoz-1-7f9736` from 15:32 Kyiv (independent of another desktop still using RC60).
- One article rewrite failed post-AI factual QA: generated text added unsupported uncertainty/speculation. Other articles rewrote successfully afterward on the same active OpenRouter backend, so this is not a global service outage.
- V2's existing RC27 rewrite loop only permits the **single** fact-safe correction when the backend appears in `rewrite_pipeline_v1_4_rc17._FACT_REPAIR_PROVIDERS`. This legacy allowlist omitted `openrouter`, so OpenRouter candidates were discarded without the existing bounded correction opportunity.
- A separate `openai/gpt-5.2-chat` OpenRouter HTTP 404 is a BYOK-only endpoint and is already quarantined by existing RC61 code; it was not the primary cause of the failed article.

## Minimal changes
- Add `openrouter` to `_KNOWN_PROVIDERS` and `_FACT_REPAIR_PROVIDERS`. One repair attempt only, within the existing shared rewrite deadline. Do not change guard scoring, acceptance, text sanitization, Anti-Slop, routing tier, limits or skip-model quarantine.
- Add regression tests proving a wrong factual claim is corrected by a second OpenRouter completion and **validated** before acceptance; and a second unsupported claim still fails closed.
- Keep all RC61 source/Windows/Drive/update/media/Inbox/publishing/Data behavior unchanged.

## Acceptance
- Windows CI full suite 3.11/3.12/3.13, Windows release full suite, signed portable runtime, Defender and ZIP digest required before release is accepted.
- Operator must confirm the previously failed *specific* article is rewritten safely in RC62 with the existing Data folder; RC62 LIVE is not proven by mocked tests. Preserve RC61/RC60 rollback snapshots.
