# UA FREE Content Tool v1.4.0-rc27

RC27 stabilizes the rewrite path after the remaining live RC26 failure and makes merged multi-source groups genuinely multi-source.

## Stable public-copy recovery

- Public `HEADLINE:/TEXT:` output is separated deterministically from trailing model service sections such as `ANALYSIS:`, `FACTS:`, `EXPLANATION:`, notes, metadata and reasoning.
- When a model drafts more than one labelled answer, the last complete public headline/text pair is used.
- JSON, truncated JSON, marker output, markdown-decorated labels and plain publishable prose remain supported.
- Complete or dangling model reasoning wrappers are removed before editorial QA.
- A recoverable formatting mistake no longer triggers a second paid AI call. Format-only repair loops were removed from the production candidate path; an unusable response moves to a fresh route instead.
- Deterministic Editorial QA and Fact Guard still run after recovery. No factual safety check is bypassed.

## Multi-source synthesis

- Groups with more than one source explicitly instruct every cloud/local rewrite route to synthesize the merged event instead of paraphrasing one source.
- Normal groups keep the existing equal per-source evidence budget.
- Large groups now retain source-support membership while collapsing duplicates and select evidence by new-source coverage before filling spare prompt space by factual value.
- Repeated facts are represented once, conflicting numeric variants remain separate, and one verbose source can no longer monopolize a large-group Evidence Pack.

## Preserved

- RC25 health-aware AI provider pool and circuit breakers remain active.
- RC24 live Codex model selection remains active.
- RC23 deadline/cancellation protection remains active.
- RC17 Fact Guard remains active.
- RC21 current-calendar-day Inbox coverage remains active.
- No database migration. Existing Data, sources, groups, queue, publication history, keys, settings and Rowboat memory remain compatible.
