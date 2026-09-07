# UA FREE Content Tool v1.4.0-rc26

RC26 fixes the live rewrite-format failure that remained after the RC25 health-aware Router.

## Rewrite protocol

- Cloud rewrites now request the same simple `HEADLINE:/TEXT:` marker protocol as the local emergency model instead of requiring a JSON envelope.
- JSON remains accepted for backward/provider compatibility.
- The parser now recovers one-object JSON arrays, common field aliases, one-level provider wrappers, balanced embedded objects, mildly truncated JSON fields, markdown-decorated markers, and plain publishable prose.
- Plain-text recovery is still passed through the normal editorial validator and deterministic Fact Guard. It is not a safety bypass.

## Format recovery

- A structurally malformed but otherwise successful cloud response may receive one short same-provider format repair regardless of whether the provider is Codex, Gemini, NVIDIA, Groq, or Cloudflare.
- The repair remains one-shot for the whole rewrite attempt, so a bad envelope cannot create recursive provider burn-through.
- Fresh providers remain available after a failed repair.

## Preserved

- RC25 health-aware provider pool, provider-wide quota circuits and resilient OpenAI-compatible transport remain active.
- RC24 explicit live Codex model selection remains active.
- RC23 deadline/cancellation protection, RC17 Fact Guard and RC21 current-day Inbox coverage remain active.
- No database migration. Existing Data, sources, groups, queue, publication history, keys, settings and Rowboat memory remain compatible.
