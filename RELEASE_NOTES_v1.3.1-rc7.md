# UA FREE Content Tool v1.3.1-rc7

## Changes

### Codex / AI Router

- Codex remains the primary AI route when authorized and not on cooldown.
- Settings show Codex installation/auth state, Router cooldown and reason, last attempt, result and latency.
- A new **Перевірити Codex** action refreshes the live account state.
- Timed-out Codex SDK app-server processes are terminated by the watchdog instead of remaining as invisible background work.
- Concurrent overlapping Codex calls are prevented.
- Codex quota cooldown is capped at five minutes so a restored ChatGPT allowance returns to service quickly.
- Router state stores per-model health metadata without prompts, publication text or secrets.

### Rewrite

- Rewrite continues to use one shared deadline.
- Codex/Gemini receive one short same-provider format repair when the response contains usable material but misses the required output envelope.
- Post-AI QA and Fact Guard remain separate from provider health.
- Recoverable AI failures and the rewrite emergency timeout no longer create blocking modal dialogs; the current editor text is left unchanged.
- Existing large-group evidence condensation and the <=900-character deterministic compaction/revalidation path remain active.

### Find and merge

- The full inbox is scanned with one representative article preview per group instead of hydrating every source article up front.
- Only candidate groups are then fully hydrated and re-scored using all source articles.
- The prefilter actually respects the shared deadline; the previous RC6 implementation accepted a deadline argument and discarded it.
- AI verification runs only while useful budget remains. Deterministic candidates are not discarded if AI is unavailable.
- The emergency UI guard is 90 seconds and is non-modal; cancellation is propagated to the worker.

### Naming

- Visible name: **UA FREE Content Tool v1.3.1-rc7**.
- No `dev`, internal build nickname, or secondary release numbering is shown in the current application title.

### Preserved

- Database schema and existing `Data` remain compatible.
- Publication queue, platform integrations, tokens, media workflow and the Windows launcher are not redesigned in this release.
- RC4 Tkinter thread-safety and RC5/RC6 factual rewrite safeguards remain in place.
