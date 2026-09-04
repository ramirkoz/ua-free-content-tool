# UA FREE Content Tool

**Privacy-first portable Windows application for collecting, grouping, rewriting, scheduling, and cross-posting news.**

> **Current release:** `v1.4.0-rc15`  
> **Current version:** `v1.4.0-rc15`
> **Platform:** Windows 10/11, portable
> **Interface and output languages:** Ukrainian and English
> **License:** GPL-2.0-or-later

UA FREE Content Tool gives a human editor one local workflow for the news-production cycle: collect materials, find reports about the same event, merge only after explicit confirmation, create one canonical publication, attach media, schedule it, and publish to selected social networks.

## What is new in v1.4.0-rc15

- Keyword-search results in Inbox now open as a near-fullscreen editorial workspace.
- The merged-block composition editor uses the same near-fullscreen workspace for full-text comparison.
- Inbox has a source filter populated from sources actually present in the currently visible working set.
- A merged block remains visible when any article inside it belongs to the selected source.
- Source filtering composes with the existing Inbox status filter and RC11 stable multi-sort instead of replacing them.
- RC14 keyword merge search and safe detach behavior are preserved unchanged.
- No database schema migration and no Data reset are required.

See [RELEASE_NOTES_v1.4.0-rc15.md](RELEASE_NOTES_v1.4.0-rc15.md).

## Core workflow

1. **Collect materials.** Enabled sources create separate incoming blocks.
2. **Select manually.** Use `Shift`, `Ctrl`, or `Ctrl+A` where supported.
3. **Find candidates.** Global topic search proposes likely related blocks without merging them.
4. **Confirm grouping.** Only the editor decides which blocks are combined.
5. **Rewrite.** The AI Router uses the highest-priority available model and can fall back to local Ollama.
6. **Edit and approve.** A human verifies facts, wording, and length.
7. **Attach media.** Media can be selected from Google Drive according to the selected publication targets.
8. **Schedule.** The package is added to the publication queue.
9. **Publish sequentially.** Every platform keeps its own target status.
10. **Retry safely.** Failed targets can be retried without repeating successful publications.

## AI Router and local fallback

Production AI tasks use one priority chain. Provider or model failures such as quota, HTTP 429, timeout, temporary errors, or invalid output are handled automatically according to router policy.

The local emergency path is designed to reuse what is already installed on the Windows machine:

- running Ollama at `127.0.0.1:11434` is preferred;
- installed but stopped Ollama can be started hidden;
- already installed generative models are enumerated and reused;
- embedding-only models are skipped for generation;
- no Ollama reinstall is performed;
- no model pull/download is performed automatically;
- a manually configured OpenAI-compatible llama.cpp endpoint remains a secondary local fallback.

Small local models receive compact prompts and smaller output budgets instead of the heavier cloud prompt format.

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

Supported publication targets include:

- Facebook Pages;
- Threads;
- LinkedIn;
- Telegram;
- optional Instagram workflows present in the current application branch;
- private Google Drive media.

The queue stores platform targets independently, preserves attempts and remote IDs, and retries only failed targets. Existing queued materials keep their assigned targets when settings change.

## Editorial memory

The application keeps editorial learning and working data locally. Approved examples can guide style and structure, while new facts must come from the current source material. Rowboat/local memory is used as editorial context, not as a factual source for a new story.

## Portable data

The `Data` folder next to the executable contains the working installation state, including the database, portable configuration, platform tokens, queue state, editorial memory, exclusions, and operational data.

For every update:

1. Close the application completely.
2. Confirm the process is no longer running.
3. Back up the complete current application folder.
4. Extract the new version into a **new folder**.
5. Copy the complete existing `Data` folder into the new portable folder.
6. Start the new version and verify AI and platform connections.
7. Keep the old working copy until the first successful live cycle.

Do not replace only the EXE. The portable package depends on the accompanying signed Python runtime and application directories.

`Data\config.portable` and `Data\portable.key` form one pair. Do not delete, rename, or move them separately.

See [PORTABLE_MODE.md](PORTABLE_MODE.md) for details.

## Requirements

### Ready Windows portable build

- Windows 10 or Windows 11;
- internet access for collection and configured cloud/platform integrations;
- credentials only for the services you use;
- Google Cloud OAuth Desktop client when Google Drive is enabled;
- Ollama is optional but recommended as the local emergency AI reserve.

Ollama and model files are **not bundled** into the portable archive.

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
2. For this candidate, use `UA_FREE_Content_Tool_v1.4.0-rc15_Windows_Portable.zip`.
3. Verify SHA-256 against `SHA256SUMS.txt`.
4. Extract the full ZIP into a new folder.
5. Copy your existing `Data` folder if updating.
6. Run `UA_FREE_Content_Tool.exe` without administrator rights.
7. Open **Settings** and verify the AI Router, local AI, Google Drive, and publication targets you use.

## Security

UA FREE Content Tool is a local application with no built-in telemetry about editorial work.

- Portable configuration is encrypted.
- Secrets are masked in the interface and normal errors.
- Google Drive uses OAuth.
- Temporary public media access is limited to the technical publication workflow that requires it.
- Local editorial learning stays on the operator’s machine unless explicitly exported.

Never publish a real `Data` folder, portable keys, SQLite databases, tokens, secrets, private Drive links, or logs/screenshots containing credentials.

See [SECURITY_NOTES.md](SECURITY_NOTES.md).

## Build and validation

Build the portable package with:

```bat
Build_Portable_Windows.bat
```

The release workflow validates source, tests the application, builds the signed portable runtime, performs GUI startup checks, runs Microsoft Defender, validates ZIP integrity and paths, calculates SHA-256 checksums, and publishes the GitHub Release.

v1.4.0-rc15 is the current release candidate built on the live-accepted RC14 baseline. It preserves the existing signed portable runtime, publication behavior and Data compatibility while adding the RC15 Inbox workspace and source-filter changes covered by deterministic regression tests and Windows CI.

## Documentation

- [RELEASE_NOTES_v1.4.0-rc15.md](RELEASE_NOTES_v1.4.0-rc15.md) — current candidate notes.
- [CHANGELOG.md](CHANGELOG.md) — version history.
- [PLATFORM_SETUP.md](PLATFORM_SETUP.md) — platform and Google Drive setup.
- [PORTABLE_MODE.md](PORTABLE_MODE.md) — portable data, migration, and backups.
- [SECURITY_NOTES.md](SECURITY_NOTES.md) — security boundaries.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution rules.
- [docs/MAINTAINER_RELEASE_GUIDE.md](docs/MAINTAINER_RELEASE_GUIDE.md) — release procedure.

## Bug and vulnerability reports

A GitHub Issue should include the application version, Windows version, the exact action performed, the visible error, and sanitized logs or screenshots. Never attach real tokens, secrets, `Data`, databases, or portable keys.
