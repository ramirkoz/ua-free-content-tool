# UA FREE Content Tool v1.4.0-rc20

RC20 fixes same-day source recovery after application downtime, restart or upgrade.

## What changed

- The working Inbox still represents the current calendar day in the configured RC19 working timezone.
- Telegram collection is no longer limited to the latest preview page when a same-day gap must be recovered.
- On the first RC20 run, every enabled Telegram/RSS source is re-read from 00:00 of the current working day so same-day stories missed by RC19's fixed latest-30 Telegram window can be restored.
- Telegram recovery walks public preview history backwards page by page using the oldest message id as the cursor and stops after crossing the working-day boundary. Recovery is bounded by a safety page cap.
- RSS recovery evaluates all entries currently exposed by the feed instead of taking only the first 30. It cannot recover entries already removed by the upstream feed.
- After the one-time RC19→RC20 repair succeeds for every enabled source, a small marker in `Data` prevents an expensive full-day replay on every restart.
- Normal five-minute polling remains lightweight. If the previous successful source check is more than 12 minutes old, RC20 performs a bounded gap recovery with a 10-minute overlap; if the last check belongs to a previous day, recovery starts at the current working-day midnight.
- Database deduplication remains authoritative, so recovery can safely encounter stories already stored.
- Persistent source diagnostics are preserved. The UI label now says `Помилок (всього)` / `Errors (total)` to make clear that the number is cumulative history, while `Стан джерела` reflects whether the latest check is currently healthy.

## Timezone behavior

- Stored timestamps remain UTC.
- Current-day boundaries and recovery use the same RC19 working timezone selected in Settings: system timezone by default, or an explicit IANA timezone override.
- No city is hard-coded by RC20.

## Compatibility

- No database schema migration.
- Existing RC19 `Data`, sources, queue, publication history, tokens and settings are preserved.
- RC18 daily Inbox rollover and RC19 timezone architecture remain unchanged.
