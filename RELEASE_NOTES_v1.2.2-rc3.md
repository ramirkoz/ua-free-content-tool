# UA FREE Content Tool v1.2.2 RC3

RC3 fixes the live Windows case where the local Ollama health test succeeds but a real rewrite can still fail after cloud quotas are exhausted.

## Local emergency AI in real rewrite workflows

- Production rewrite and topic-search paths now use the bounded v1.2.2 router instead of the legacy unbounded call.
- Rewrite output is capped to 1200 tokens and topic analysis to 900 tokens.
- The local slot is always tried as the final provider even if an older local timeout left a stale router cooldown.
- A successful Ollama call is reported with the actual model name, for example `qwen3:4b / Ollama`, instead of the placeholder `local-model`.
- If the local response fails structural validation, the same local model gets one format-repair attempt before the task is considered failed.
- Ollama continues to reuse already installed models only. RC3 does not reinstall Ollama and does not pull/download any model.

## Rewrite JSON tolerance

- Rewrites accept valid JSON wrapped in a markdown fence or short model commentary.
- Slightly truncated/malformed JSON can recover existing `headline`, `fact_card` and `rewrite` string fields without inventing facts.
- Editorial validation still runs after recovery; invalid output remains rejected.

## Regression coverage

- Added tests for wrapped JSON, truncated JSON recovery, bounded production rewrites, actual Ollama model reporting and one-shot local format repair.
- Full local suite before Windows packaging: 391 tests passed.

`main` remains untouched until the live RC3 Windows test succeeds.
