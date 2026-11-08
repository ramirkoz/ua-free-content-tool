UA FREE Content Tool v2.0.0-rc62 — Windows Portable

Focused live rewrite recovery fix on RC61.
- When OpenRouter returns an otherwise usable article that Fact Guard rejects, allow ONE existing bounded FACT-SAFE REPAIR attempt.
- Repair rechecks the exact evidence with Fact Guard; every result still passes sanitization and Anti-Slop before publication.
- Never bypass factual QA, never auto-publish a rejected or speculative rewrite.
- OpenRouter backend, monthly budget, existing RC61 endpoint blacklist, media, Inbox, Data, publication and source schedules remain unchanged.
- Keep RC61 (or accepted RC60) and a Data backup for rollback before first launch.

OpenRouter model HTTP 404 BYOK-only endpoints remain quarantined by the existing model selector.
