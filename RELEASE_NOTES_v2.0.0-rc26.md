# UA FREE Content Tool v2.0.0-rc26 — MANUAL TEST

RC26 adds multi-channel Telegram publishing without changing the stabilized RC25 collection/supervisor runtime.

## Telegram destinations
- One bot can now own a persistent catalog of multiple Telegram channels.
- Every channel is a separate destination key (`telegram:<chat_id>`), with its own checkbox, queue tab, history tab and schedule.
- The publication editor never selects all Telegram channels implicitly from a generic recommendation; only the configured default channel is preselected unless the user explicitly chooses others.
- Existing legacy `telegram` queue items remain publishable through the old single-target compatibility path.
- Existing target presets containing the legacy `telegram` key migrate to the configured/default Telegram channel rather than all channels.

## Channel discovery
- `Знайти / оновити канали` reads recent Bot API `channel_post`, `edited_channel_post` and `my_chat_member` updates, combines them with the persistent catalog, then verifies administrator status and `can_post_messages` through `getChatMember`.
- `Додати / перевірити` lets the operator add a quiet/old channel once using `@username` or `chat_id`.
- Telegram Bot API has no endpoint that enumerates every channel a bot administers; therefore channels older than Telegram's update retention or hidden behind another webhook/updates consumer require one manual verification or a fresh channel event.
- Catalog stores only channel metadata. Bot token remains only in the encrypted app configuration.

## Publishing compatibility
- Concrete Telegram destinations are resolved by the v1.4 publisher factory and use the same bot token with the selected channel's chat id.
- Telegram caption/text validation is applied to `telegram:<chat_id>` targets in scheduled and publish-now flows.
- Donation settings fall back to the existing generic Telegram preference until configured per concrete channel.
- Telegram history metric/permalink handling understands concrete targets, including public `t.me/<username>/<message>` and private `t.me/c/...` links.

## Stability
- RC25 handle-leak fix, network/SQLite lifecycle telemetry, independent heartbeat and manual-test update policy are unchanged.
