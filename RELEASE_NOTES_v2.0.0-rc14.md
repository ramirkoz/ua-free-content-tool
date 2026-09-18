# UA FREE Content Tool v2.0.0-rc14

RC14 adds two production layers: autonomous safe updates and deterministic Ukrainian anti-slop QA.

## Autonomous updater
- Checks official GitHub Releases every 15 minutes independently of Google Drive.
- Accepts only a newer `2.0.0-rcN` release with the exact Windows Portable asset and a GitHub SHA-256 digest.
- Starts only when the Content Tool UI is idle and no collection operation or remote update is active.
- Reuses the existing RC8+ detached updater: download, SHA verification, staging, preserve `Data`, restart, startup health proof and rollback on failure.
- Google Drive remote `CONTROL/update` remains supported; autonomous update is an additional path, not a replacement.
- Supervisor status reports whether auto-update is enabled, current, available, preparing or unable to check.

## UA Anti-Slop v1
- Architecture adapted from `misbahsy/anti-ai-slop` (MIT) for Ukrainian newsroom output.
- Local deterministic gate only: no new SDK, API key or network dependency.
- Removes invisible Unicode controls and scores high-signal Ukrainian machine-writing patterns, repetition, canned conclusions, vague authority claims and mechanical rhythm.
- Runs only after Fact Guard succeeds.
- A failing fact-safe draft gets at most one same-provider human-copy repair, then the normal provider fallback continues.
- Repair is fact-locked: no new facts, numbers, names, attribution, uncertainty or causal links.

The active RC13 runtime behavior, Drive circuit breaker, publication receipts and diagnostics remain intact.
