# UA FREE Content Tool

**Privacy-first portable Windows application for collecting, grouping, rewriting, scheduling, and cross-posting news.**

> **Public release:** `v1.3.0`  
> **Current version:** `v1.3.1-rc13`
> **Platform:** Windows 10/11, portable
> **Interface and output languages:** Ukrainian and English
> **License:** GPL-2.0-or-later

UA FREE Content Tool gives a human editor one local workflow for the news-production cycle: collect materials, find reports about the same event, merge only after explicit confirmation, create one canonical publication, attach media, schedule it, and publish to selected social networks.

## What is new in v1.3.1-rc13

- RC10 keeps the RC9 Tk target/donation-control crash fix and additionally fixes Inbox column geometry: widths no longer stretch with the window, a horizontal scrollbar is available, and Shift+click adds secondary/tertiary sort keys.
- The RC8 changes remain: persisted Inbox column widths, one-word central topic, bounded visible rewrite attempts, Threads ambiguous-publication reconciliation, local/history potential scoring, and editable per-target donation policy.

- Codex has a visible runtime status: installation, authorization, Router availability/cooldown, last attempt and latency.
- Codex watchdog now terminates the active Codex child app-server when a request exceeds its bounded slice, preventing timed-out requests from continuing invisibly in the background.
- Rewrite keeps one shared deadline and performs one bounded same-provider format repair for Codex/Gemini before falling through to weaker providers.
- Recoverable rewrite/search failures are reported in the operation/status area instead of repeatedly blocking the editor with modal dialogs.
- Global **Find and merge** is staged: a lightweight one-article preview scans the full `new` inbox, then only candidate groups are fully hydrated from SQLite.
- The duplicate prefilter now obeys its deadline instead of discarding it; AI verification stops when the remaining budget is too small while deterministic candidates remain usable.
- The global-search emergency UI guard is separate from the internal search deadline and cancellation is propagated to the worker.
- Large merged blocks retain the evidence condenser and <=900-character post-AI safety introduced earlier.
- Visible application naming is consistently `UA FREE Content Tool v1.3.1-rc13`; historical `dev`/internal build labels are not shown.

See [RELEASE_NOTES_v1.3.1-rc13.md](RELEASE_NOTES_v1.3.1-rc13.md).

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
2. For this candidate, use `UA_FREE_Content_Tool_v1.3.1-rc13_Windows_Portable.zip`.
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

The public v1.3.0 release remains the stable baseline. v1.3.1-rc13 is the current live candidate built on the same signed portable runtime; its global-search and Router changes are covered by targeted deterministic tests, while final Windows/Data acceptance is performed on the operator workstation.

## Documentation

- [RELEASE_NOTES_v1.3.1-rc13.md](RELEASE_NOTES_v1.3.1-rc13.md) — current candidate notes.
- [CHANGELOG.md](CHANGELOG.md) — version history.
- [PLATFORM_SETUP.md](PLATFORM_SETUP.md) — platform and Google Drive setup.
- [PORTABLE_MODE.md](PORTABLE_MODE.md) — portable data, migration, and backups.
- [SECURITY_NOTES.md](SECURITY_NOTES.md) — security boundaries.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution rules.
- [docs/MAINTAINER_RELEASE_GUIDE.md](docs/MAINTAINER_RELEASE_GUIDE.md) — release procedure.

## Bug and vulnerability reports

A GitHub Issue should include the application version, Windows version, the exact action performed, the visible error, and sanitized logs or screenshots. Never attach real tokens, secrets, `Data`, databases, or portable keys.
