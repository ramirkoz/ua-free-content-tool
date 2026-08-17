# UA FREE Content Tool v1.2.2 RC1

Release candidate focused on AI Router resilience for the global duplicate search.

## Fixed

- Global duplicate search no longer sends the entire inbox in one giant AI prompt.
- A local TF-IDF-style prefilter selects only plausible duplicate candidates before AI is called.
- Candidate groups are processed in bounded, overlapping batches of at most 20 news groups.
- Each duplicate-search prompt is capped at approximately 8,000 characters and requests at most 900 output tokens.
- Large editor-feedback and graph-memory blocks are compacted before being included in duplicate prompts.
- OpenAI-compatible providers accept `application/problem+json` error responses so NVIDIA/API errors remain readable.
- HTTP 413 / explicit request-too-large responses are classified as task-size failures, not provider failures.
- A request-too-large failure does not put an otherwise healthy provider on cooldown.
- Groq TPM errors that explicitly report a single oversized request are treated as request-size failures rather than exhausted account quota.

## Compatibility

- Existing `Data` from v1.2.1 is compatible and should be copied as a whole.
- Provider secrets, AI Router key, publication history, queue, sources and social credentials are unchanged.
- Stable v1.2.1 remains untouched while RC1 is tested.
