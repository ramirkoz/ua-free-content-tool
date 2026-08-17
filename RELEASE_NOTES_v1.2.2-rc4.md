# UA FREE Content Tool v1.2.2 RC4

RC4 fixes the live Windows failure where `qwen3:4b / Ollama` passes the health check but a real rewrite or duplicate search stalls for four minutes and times out.

## Root cause

RC3 routed production work to Ollama correctly, but it still sent the small CPU model cloud-sized prompts and cloud-sized output budgets. A 4B local model was being asked to process editorial memory / large candidate batches and was allowed up to 900–1200 output tokens. The local model was alive; the task profile was wrong.

## RC4 local emergency profile

- Cloud providers keep the full rich prompt and existing output budgets.
- Ollama receives a separate compact prompt designed for the already installed local model.
- Rewrite fallback: compact facts from every source, no URL/Rowboat/example dump, simple `ЗАГОЛОВОК` + `ТЕКСТ` protocol, 320-token ceiling, 120-second task timeout.
- Topic-search fallback: compact candidate prompt, 260-token ceiling, 90-second task timeout.
- Global duplicate fallback: candidate-only batches, maximum 12 groups, compact local prompt <= 3600 characters, 220-token ceiling, 90-second task timeout.
- Global duplicate search no longer sends unrelated small inboxes to AI when the deterministic prefilter found no candidate edge.
- Ollama timeout messages now describe the actual local AI task instead of incorrectly calling every timeout a topic search.
- Existing Ollama installation and models are reused. Nothing is installed or downloaded automatically.

## Validation

- 394 tests passed locally before Windows packaging.
- Added regression coverage for compact rewrite/duplicate local profiles and task-specific Ollama timeouts.
- `main` remains untouched until the live RC4 Windows test succeeds.
