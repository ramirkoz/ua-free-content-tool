# UA FREE Content Tool v1.3.1-rc8

## Stabilization and editorial workflow

### Inbox

- Added one compact **Тема** column with a deterministic central topic such as `Політика`, `Міжнародка`, `Україна`, `Київ`, `Війна`, `Економіка`, `Технології`, `Наука`, `Бізнес`, `Суспільство`, `Культура` or `Спорт`.
- Inbox defaults to the compact working layout requested from the production screenshot: the event column receives the space, service columns stay narrow.
- Manually resized Inbox column widths are stored locally in `Data` and restored on the next launch.
- Topic classification is local and deterministic: refreshing the Inbox does not trigger AI or network requests and does not require a database migration.

### Donation block

- Donation text is no longer a mandatory hard-coded publication policy.
- Added a separate donation-text editor in the Publication tab.
- Every configured publication profile/target has its own persistent **Донатний блок** checkbox.
- RC8 starts with donation targets opt-in: a new RC8 donation settings file has no enabled targets until the user selects them.
- Facebook and Threads keep the donation block as a separate comment/reply when enabled.
- LinkedIn, Telegram and Instagram keep it inline when enabled.
- Existing RC7 queued payloads containing the legacy UA FREE footer are normalized at publication time, so disabling the donation checkbox really removes the old mandatory footer.
- A failed/ambiguous donation reply after a confirmed Facebook or Threads main post no longer turns the whole platform result into a publication failure. The main post remains `опубліковано`; donation outcome is stored separately in target progress and shown in History details.

### Threads

- Added conservative reconciliation for an ambiguous one-part Threads publication response: RC8 checks recent posts and accepts only an exact normalized text match. If no safe match exists, publication remains fail-closed and no blind duplicate is created.
- The unreliable live Threads keyword counter is removed from the editorial score path. Missing Threads search data is no longer presented as a meaningful zero.
- `Поточний потенціал` now uses the story/source structure while `Прогноз за історією` continues to use actual metrics from the user's publication history.

### Rewrite

- Manual rewrite attempts now receive a visible attempt number.
- Rewrite start, success, failure and timeout are logged.
- Rewrite failures and timeouts are visible again instead of silently leaving the user to click a second time without an explanation.
- The existing AI Router, evidence pipeline, Fact Guard, source condensation and cancellation safeguards remain intact.

### Preserved

- Existing database schema and `Data` remain compatible.
- Existing media gallery, Google Drive cleanup, queue pacing, global duplicate logic, Fact Guard and platform integrations are preserved.
- RC8 is an additive stabilization layer over RC7 rather than a rewrite of the application core.
