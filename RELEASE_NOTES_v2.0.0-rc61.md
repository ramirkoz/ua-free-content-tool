# UA FREE Content Tool 2.0.0-rc61

Targeted safe-stability update on **operator-accepted RC60**, without changing its media/UI/publication workflows.

## Focused corrections
- Cloudflare legacy AI Router slot `@cf/nvidia/nemotron-3-120b-a12b` replaced with Cloudflare-documented `@cf/google/gemma-4-26b-a4b-it`; keep `@cf/zai-org/glm-4.7-flash` and direct NVIDIA providers unchanged. The new slot is not claimed to be LIVE account-tested; operator's current selected backend is OpenRouter.
- Exclude specialized `scaledown/extract` and `scaledown/summarize` from generic OpenRouter chat selection. The exclusion also applies when a model catalog persisted by RC60 is loaded. This addresses observed HTTP 400 schema/response-format incompatibility.
- On an OpenRouter DNS lookup failure, do not waste further model attempts against the same unreachable hostname. Other transient OpenRouter failures retain model fallback and bounded attempts.
- Added focused regression tests for model selection, Cloudflare transport contract, preserved provider slots, DNS failure handling and non-DNS fallback.

## Explicitly unchanged from RC60
- Inbox manual sorting, viewport restoration and search; source collection behavior.
- Media title-based filenames, explicit-only discovery, progress during download/upload, Telegram exact-post scoping, videos and native albums.
- Fact Guard, sanitize, Anti-Slop, QA, publisher receipts / UNKNOWN fail-closed behavior.
- OpenRouter backend selection stays exclusive; no silent activation of direct Gemini/NVIDIA/Groq/Cloudflare while OpenRouter is selected.
- Data, provider keys, Google Drive accounts, Telegram/social destinations and operator settings.

## Evidence and acceptance
- Basis: Google Drive Supervisor last mirrored 2026-11-06 18:59 Kyiv (RC60 healthy after a transient network/DNS incident); this is not a November 8 live run.
- Automated CI, Windows signed Portable build, Defender scan, official GitHub Release and operator runtime acceptance must be verified separately before declaring complete.
- For rollback, keep the accepted RC60 portable and its Data/backup. Never include user Data in published release assets.
