# UA FREE Content Tool v1.2.1

Production update focused on publication reliability, reusable social targeting and resilient AI execution.

## Publishing and media
- Telegram galleries with 2–10 images are published as one media group with the text caption on the first item.
- Threads carousel root text respects the 500-character limit and continues overflow as chained replies.
- Threads ambiguous donation-reply states can reconcile already published replies.
- Media selection shows the exact number of selected items before confirmation.

## Social targets
- Named social-network target sets can be saved, applied, renamed and deleted.
- The last used target selection becomes the default for the next new material.
- Existing queued materials preserve their already assigned targets.

## AI Router
- All active AI workflows use one automatic quality-priority failover chain.
- Production providers: Codex / ChatGPT, Google Gemini, NVIDIA NIM, Groq, Cloudflare Workers AI and optional local llama.cpp fallback.
- Providers or models on quota, 429, timeout, temporary failure or invalid output are skipped automatically with cooldown handling.
- One `Тест AI Router` action checks every configured production provider and then the real priority chain.
- Provider health is shown directly in settings with green, red, amber and gray status marks plus detailed reasons.
- SambaNova, Cerebras and OpenRouter were removed from the production UI and runtime chain after live validation showed billing/access friction that did not fit the free-reserve goal.

## Validation
- Windows portable build is validated by the full automated test suite.
- Entrypoint/import checks, GUI startup smoke test, Microsoft Defender scan and ZIP integrity checks are release gates.
