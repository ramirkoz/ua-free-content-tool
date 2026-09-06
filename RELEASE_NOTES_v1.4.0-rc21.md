# UA FREE Content Tool v1.4.0-rc21

RC21 fixes the live failure where the Inbox could show only roughly the newest two hours even though the working-day requirement is all available news from 00:00 to now.

## What changed

- Restores the full current-day Inbox read. RC18 accidentally reintroduced a 200-row default after RC11 had removed the historical pre-truncation; RC21 again loads the full working-day set before visual sorting and filtering.
- Replaces RC20's one-time upgrade marker with date-scoped, per-source daily coverage state.
- Telegram daily coverage is marked complete only after pagination actually crosses the configured working-day midnight boundary. A stalled cursor, empty preview, or safety cap is not treated as success.
- Until midnight coverage is proven for an enabled Telegram source, automatic collection keeps retrying the full-day recovery instead of falling back permanently to the latest preview tail.
- RSS/Atom recovery parses every entry currently exposed by the feed. It is not capped at 30 entries; exhausting the current feed is the strongest coverage guarantee RSS can provide.
- Normal five-minute lightweight polling remains available after daily baseline coverage is confirmed. Gap recovery is still used after downtime.
- A new Inbox indicator shows the raw number of news items collected today and the daily coverage status of enabled Telegram/RSS sources, for example `Новин сьогодні: 1 284 · покриття джерел: 36/40`.
- Coverage automatically resets on the next working calendar date. Stored timestamps remain UTC and the RC19 working timezone remains authoritative.

## Compatibility

- No database schema migration.
- Existing Data, sources, groups, queue, publication history, tokens, media references and settings are preserved.
- RC14 keyword merge/unmerge, RC15 source filtering, RC17 Fact Guard fixes, RC18 daily rollover and RC19 timezone behavior remain inherited.
