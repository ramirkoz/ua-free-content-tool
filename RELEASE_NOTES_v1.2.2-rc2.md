# UA FREE Content Tool v1.2.2 RC2

RC2 keeps the bounded global duplicate search from RC1 and fixes the local emergency AI path exposed by a real cloud-quota outage.

## Local emergency AI

- The local fallback now checks the already running Ollama API on `127.0.0.1:11434` first.
- If Ollama is installed but not running, the app starts the existing `ollama.exe serve` process hidden in the background and waits for the local API.
- Existing Ollama models are reused. The app does **not** reinstall Ollama and does **not** pull/download another model.
- An explicitly selected installed model is preferred. Otherwise the app selects a capable non-embedding model from the models already present in Ollama.
- The old OpenAI-compatible `llama.cpp` endpoint remains a secondary manual fallback when Ollama is unavailable.
- The local-provider test now reports the actual engine and model used.
- Windows process launch uses `CREATE_NO_WINDOW`/hidden startup flags so local recovery does not open a console window.

## Router resilience

- A quota/429 on one model now cools down that model, not every model of the same provider. Authentication/configuration failures still disable the provider as a whole.
- Provider diagnostics continue through sibling models after a model-specific quota response.
- Bounded duplicate-search calls keep temperature at zero for the local engine.

## Duplicate JSON tolerance

- Duplicate search accepts a valid JSON object even when a model wraps it in a code fence or adds a short explanation before/after it.
- Invalid structures are still rejected fail-closed; the parser does not invent cluster IDs or repair missing factual content.

## Compatibility

- Existing `Data`, encrypted AI provider secrets, queue, history and editorial memory remain compatible with v1.2.1 / v1.2.2 RC1.
- `PUBLIC_VERSION.txt` and `VERSION.txt` remain `1.2.2`; the Python package/versioned window identifies this build as `1.2.2-rc2` / RC2.
