# UA FREE Content Tool v1.2.2 RC2

RC2 keeps the bounded global duplicate search from RC1 and fixes the local emergency AI path exposed by a real cloud-quota outage.

## Local emergency AI

- The local fallback checks the already running Ollama API on `127.0.0.1:11434` first.
- If Ollama is installed but not running, the app starts the existing `ollama.exe serve` process hidden in the background and waits for the local API.
- Existing Ollama models are reused. The app does **not** reinstall Ollama and does **not** pull/download another model.
- An explicitly selected installed model is preferred. Otherwise the app selects a capable non-embedding model from the models already present in Ollama.
- The old OpenAI-compatible `llama.cpp` endpoint remains a secondary manual fallback when Ollama is unavailable.
- The local-provider test reports the actual engine and model used.
- Windows process launch uses hidden startup flags so local recovery does not open a console window.

## Router resilience

- Authentication and configuration failures remain provider-wide failures.
- A quota/429 tied to one model can fall through to the next model of the same provider before abandoning that provider.
- Provider diagnostics follow the same model-fallback behavior.
- Bounded duplicate-search calls keep temperature at zero for the local engine.
- HTTP 413 remains a task-size error and does not poison a healthy provider.

## Duplicate JSON tolerance

- Duplicate search accepts a valid JSON object even when a model wraps it in a code fence or adds a short explanation before/after it.
- Invalid structures are still rejected fail-closed; the parser does not invent cluster IDs or repair missing factual content.

## Compatibility

- Existing `Data`, encrypted AI provider secrets, queue, history and editorial memory remain compatible with v1.2.1 / v1.2.2 RC1.
- `PUBLIC_VERSION.txt` and `VERSION.txt` remain `1.2.2`; the versioned window identifies this test build as RC2.

## Automated validation

Validated code commit: `08415f74388f6aac10e88da9b26c0bb4cfd52d18`.

- Windows CI: PASS on Python 3.11, 3.12 and 3.13.
- Full Windows RC2 gate: PASS.
- Source/regression tests: PASS.
- Portable runtime build: PASS.
- GUI startup smoke: PASS.
- Microsoft Defender scan: PASS.
- ZIP integrity/package validation: PASS.
- Artifact upload: PASS.

Windows build run: `32003726580`.
Windows CI run: `32003729469`.

Portable ZIP SHA-256:

`5100df1c21798050cb2c3247899adf004d4e52cb51f5a2a5526a8381e6581559`

Source ZIP SHA-256:

`67916b907a3d7b4c8f225bec4a1e774dc1b191a23358e3855c1928b6818afa4c`

## Manual live gate still required

The remaining check is the user's actual local Ollama installation and models. Before merging RC2 into `main`, run one real local fallback task on the Windows machine and confirm that the application reports an existing Ollama model and completes the task locally.
