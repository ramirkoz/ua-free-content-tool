# UA FREE Content Tool v1.4.0-rc2

Hotfix for Instagram Professional account discovery in Meta Graph API v26.0.

- Removed the unsupported `account_type` field from Instagram Business Account queries.
- Instagram discovery now requests only `id` and `username` and treats discovered accounts as Professional.
- Legacy single-profile verification uses the same compatible field set.
- Added regression tests so `account_type` cannot silently return to Graph queries.
- Keeps all v1.4.0-rc1 independent destination queues, per-destination schedules, terminal error history and multi-account Instagram behavior.
