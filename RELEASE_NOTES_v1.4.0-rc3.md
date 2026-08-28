# UA FREE Content Tool v1.4.0-rc3

RC3 fixes two live regressions found during the first multi-destination acceptance run.

## Fixed

- Discovered Instagram Professional accounts no longer remain disabled in the editor when RC2 has a stale legacy `instagram_enabled` flag. A discovered Facebook-backed Instagram catalog with a matching encrypted Page Access Token is reconciled before target controls are built.
- Removed the inherited RC4 five-minute catch-up throttle from the v1.4 publication worker. Independent destination batches can now proceed immediately after the previous batch finishes instead of waiting five minutes between overdue jobs.
- Removed the old inter-target pacing from the RC3 v1.4 worker. v1.4 batches contain one concrete destination, so the legacy cross-target delay is unnecessary.

## Preserved

- Each Facebook Page, Instagram account, Threads profile, LinkedIn profile and Telegram channel keeps its own queue and schedule.
- A publication attempt remains terminal after success or error; automatic re-publication stays disabled to prevent duplicates.
- Meta/Google tokens remain stored only in the encrypted portable configuration.
