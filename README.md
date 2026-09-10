# UA FREE Content Tool

> **Поточний кандидат: v2.0.0-rc3.** Це обережний V2 compatibility release поверх перевіреного v1.4.0-rc30. Перед оновленням повністю закрийте RC30, розпакуйте V2 у нову папку і скопіюйте туди всю робочу папку `Data`. Деталі: [RELEASE_NOTES_v2.0.0-rc3.md](RELEASE_NOTES_v2.0.0-rc3.md).

**Privacy-first portable Windows application for collecting, grouping, rewriting, scheduling, and cross-posting news.**

> **Current release:** `v2.0.0-rc3`  
> **Current version:** `v2.0.0-rc3`  
> **Platform:** Windows 10/11, portable  
> **Interface and output languages:** Ukrainian and English  
> **License:** GPL-2.0-or-later

UA FREE Content Tool gives a human editor one local workflow for the news-production cycle: collect materials, find reports about the same event, merge only after explicit confirmation, create one canonical publication, attach media, schedule it, and publish to selected social networks.

## What is new in v2.0.0-rc3

- RC30 remains the functional compatibility baseline while V2 introduces isolated modules for AI, publishing recovery, storage compatibility, Supervisor and V2 UI.
- A hard backend switch selects exactly one content AI backend: OpenRouter, the existing AI Router, or Agent/Codex.
- OpenRouter selects task class, complexity tier and suitable model automatically, with QA escalation and a maximum of three fallback models per OpenRouter request.
- OpenRouter token usage, cost, latency and failures are recorded locally; a local monthly budget can be enforced.
- Multi-instance Supervisor keeps separate identities for two Content Tool installations and exports diagnostic summaries to Google Drive without becoming a dependency of the editorial pipeline.
- Inbox shows independent `Джерел` and current-day `Час` columns.
- Failed publication history can safely retry only unfinished destinations without re-running AI; Google Drive remains an upstream media prerequisite.
- No database reset is required and the working `Data` folder remains local.

See [RELEASE_NOTES_v2.0.0-rc3.md](RELEASE_NOTES_v2.0.0-rc3.md).

## Core workflow

1. **Collect materials.** Enabled sources create separate incoming blocks.
2. **Select manually.** Use `Shift`, `Ctrl`, or `Ctrl+A` where supported.
3. **Find candidates.** Global topic search proposes likely related blocks without merging them.
4. **Confirm grouping.** Only the editor decides which blocks are combined.
5. **Rewrite.** The active V2 AI backend performs the requested AI task; only one backend is active at a time.
6. **Edit and approve.** A human verifies facts, wording, and length.
7. **Attach media.** Media is prepared through the Google Drive-backed publication flow where required.
8. **Schedule.** The package is added to the publication queue.
9. **Publish sequentially.** Every platform keeps its own target status.
10. **Retry safely.** Failed targets can be retried without repeating successful publications or AI work.

## V2 AI backends

The **Нейронки** tab contains three isolated content backends:

- **OpenRouter**: automatic task routing, complexity tiers and model selection inside OpenRouter;
- **AI Router**: the existing direct NVIDIA, Gemini, Groq, Cloudflare, local and Codex-capable routing pool;
- **Agent**: the locally authenticated Codex/ChatGPT-account runtime.

The active backend is a hard switch. If OpenRouter is selected, content work cannot silently fall back to AI Router or Agent. OpenRouter chooses models automatically; the operator does not maintain a per-task model table.

The local emergency path inside AI Router is designed to reuse what is already installed on the Windows machine. Ollama and model files are not bundled into the portable archive.

## Duplicate grouping

Global duplicate search is intentionally human-in-the-loop.

- A deterministic title-first prefilter creates a bounded candidate graph.
- Candidate-pair materialization and neighbours per group are capped.
- AI receives only a compact bounded review set.
- AI may answer with the simple `MERGE ...` protocol or supported JSON.
- If AI fails, strong deterministic candidates can still be shown for review.
- Search runs outside the GUI thread and supports cancellation.
- Global deadlines prevent provider failover from turning one scan into a multi-minute hang.
- A late callback after cancellation or timeout is ignored.
- The editor must explicitly approve every merge.

## Publishing and media

Supported publication targets include Facebook Pages, Threads, LinkedIn, Telegram and optional Instagram workflows present in the current application branch. Google Drive is private upstream media storage, not a publication destination.

The queue stores platform targets independently, preserves attempts and remote IDs, and retries only safe failed targets. If Drive/media preparation fails, external publication does not start. A manual history retry reuses the saved payload and does not re-run AI. Unknown or possibly partial external writes fail closed to avoid duplicates.

## Supervisor

V2 Supervisor is operational monitoring, not a content AI backend. Each installation gets a stable instance identity, so two PCs do not overwrite one another. It collects local health, incident and diagnostic information, can summarize incidents through OpenRouter independently of the content backend, and exports reports to the dedicated `CONTENT_TOOL_SUPERVISOR` Drive area. A Supervisor, OpenRouter-analyzer or Drive-export failure must not stop Content Tool.

## Editorial memory

The application keeps editorial learning and working data locally. Approved examples can guide style and structure, while new facts must come from the current source material. Rowboat/local memory is used as editorial context, not as a factual source for a new story.

## Portable data

The `Data` folder next to the executable contains the working installation state, including the database, portable configuration, platform tokens, queue state, editorial memory, exclusions and operational data.

For every update:

1. Close the application completely.
2. Confirm the process is no longer running.
3. Back up the complete current application folder.
4. Extract the new version into a **new folder**.
5. Copy the complete existing `Data` folder into the new portable folder.
6. Start the new version and verify AI and platform connections.
7. Keep the old working copy until the first successful live cycle.

Do not replace only the EXE. The portable package depends on the accompanying signed Python runtime and application directories.

`Data\config.portable` and `Data\portable.key` form one pair. Do not delete, rename, or move them separately. Do not copy one PC's `Data` over another PC's live installation; each Supervisor instance and operational database must remain distinct.

See [PORTABLE_MODE.md](PORTABLE_MODE.md) for details.

## Requirements

### Ready Windows portable build

- Windows 10 or Windows 11;
- internet access for collection and configured cloud/platform integrations;
- credentials only for the services you use;
- Google Cloud OAuth Desktop client when Google Drive is enabled;
- Ollama is optional as an AI Router local reserve.

### Development from source

- Python 3.11–3.13;
- `requirements.txt` for runtime dependencies;
- `requirements-test.txt` for tests;
- `requirements-build.txt` for Windows packaging.

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-test.txt
python app.py
```

Alternative entry point:

```bat
python -m content_agent.main
```

## Windows quick start

1. Open the latest GitHub Release.
2. Use `UA_FREE_Content_Tool_v2.0.0-rc3_Windows_Portable.zip`.
3. Verify SHA-256 against `SHA256SUMS.txt`.
4. Extract the full ZIP into a new folder.
5. Copy that PC's complete existing `Data` folder if updating.
6. Run `UA_FREE_Content_Tool.exe` without administrator rights.
7. Open **Нейронки**, test the intended backend, then explicitly select it.
8. Verify Google Drive and publication targets before live publishing.

## Security

UA FREE Content Tool is a local application with no built-in cloud telemetry about editorial work except the explicitly configured operational Supervisor reports.

- Portable configuration is encrypted.
- Secrets are masked in the interface and normal errors.
- Google Drive uses OAuth.
- Temporary public media access is limited to the technical publication workflow that requires it.
- Local editorial learning stays on the operator’s machine unless explicitly exported.
- OpenRouter keys and platform credentials are not stored in GitHub or release archives.

Never publish a real `Data` folder, portable keys, SQLite databases, tokens, secrets, private Drive links, or logs/screenshots containing credentials.

See [SECURITY_NOTES.md](SECURITY_NOTES.md).

## Build and validation

Build the portable package with:

```bat
Build_Portable_Windows.bat
```

The release workflow validates source, installs test dependencies, compiles and tests the application, builds the Windows portable runtime, performs startup and Microsoft Defender checks, validates ZIP integrity and paths, calculates SHA-256 checksums, and publishes the GitHub Release.

## Documentation

- [RELEASE_NOTES_v2.0.0-rc3.md](RELEASE_NOTES_v2.0.0-rc3.md) — current candidate notes.
- [RELEASE_NOTES_v2.0.0-rc1.md](RELEASE_NOTES_v2.0.0-rc1.md) — V2 transition notes.
- [CHANGELOG.md](CHANGELOG.md) — version history.
- [PLATFORM_SETUP.md](PLATFORM_SETUP.md) — platform and Google Drive setup.
- [PORTABLE_MODE.md](PORTABLE_MODE.md) — portable data, migration and backups.
- [SECURITY_NOTES.md](SECURITY_NOTES.md) — security boundaries.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution rules.
- [docs/MAINTAINER_RELEASE_GUIDE.md](docs/MAINTAINER_RELEASE_GUIDE.md) — release procedure.

## Bug and vulnerability reports

A GitHub Issue should include the application version, Windows version, the exact action performed, the visible error, and sanitized logs or screenshots. Never attach real tokens, secrets, `Data`, databases, or portable keys.
