# UA FREE Content Tool v1.3.0

UA FREE Content Tool 1.3.0 is the stable promotion of the live-accepted 1.3 RC3 code. No new functional feature was added between RC3 live acceptance and the stable promotion.

## Evidence-first rewrite

- Deterministic Evidence Pack selection preserves important late facts, numbers, entities and source-specific details under bounded prompt budgets.
- Fact Guard validates years, numbers, named entities/models and unsupported high-risk claims after generation.
- Source metadata such as collection timestamps is not treated as factual evidence for the article body.
- Editorial examples and Rowboat/local memory are explicitly style-only and cannot supply facts to a new story.
- Adaptive retry is used only when the first candidate is blocked or weak.

## AI Router / editorial QA separation

- Provider diagnostics test endpoint/auth/model responsiveness and accept any non-empty model response. Providers are not marked unhealthy for failing to echo a literal control phrase.
- Local Ollama diagnostics use the same liveness rule.
- Production rewrite calls AI Router in transport-only mode. Structural parsing, editorial validation and Fact Guard run after a provider response is returned.
- Candidate rejection by post-AI QA never creates or restores provider/model cooldown.
- Post-AI retry can skip only the rejected model so another model from the same provider remains usable.
- qwen-style `<think>...</think>` wrappers are stripped before parsing.
- One bounded local format-repair attempt is available after a local response fails post-AI QA.
- Real auth, quota, network, model and runtime failures retain the existing Router cooldown behavior.

## Source health and protected production behavior

- Persistent Source Health diagnostics are available without a database schema bump.
- The accepted global duplicate engine and explicit human merge confirmation are preserved.
- Media Engine, multi-image workflows, platform publishers, queue/scheduling, outcome-unknown safety, AES-GCM provider secrets and Data schema 8 are preserved.
- Existing portable `Data` remains the migration boundary. Update by copying the complete `Data` folder into a clean v1.3.0 portable folder.

## Validation and live acceptance

- v1.3 RC gates passed deterministic regression tests, compile/import checks, SQLite quick checks and ZIP integrity validation.
- The signed Windows portable launcher/runtime remained unchanged from the accepted signed-runtime line.
- Live Windows/Data testing confirmed that Content Creator 1.3 RC3 works in the user's real installation.
- Provider diagnostics correctly reported NVIDIA/Groq/Ollama liveness while exhausted providers remained limited.
- A real production rewrite completed successfully after the Router/QA separation fix.
- No regression was reported in the protected duplicate, media, queue or publication mechanisms before stable promotion.

## Release policy

The GitHub release workflow must pass the complete Windows release gate before publishing or refreshing v1.3.0: full pytest, Python 3.12 source validation, signed runtime check, GUI startup smoke, Microsoft Defender scans of the extracted runtime and final ZIP, ZIP safety/integrity checks, source archive creation and SHA-256 generation.

The exact Windows Portable ZIP, Source ZIP and `SHA256SUMS.txt` produced by that final release gate are also archived by the same workflow for byte-identical synchronization to the Google Drive Project Vault. The workflow publishes a `release-sync` commit status containing its run ID so the exact artifact can be retrieved without rebuilding or repackaging it.
