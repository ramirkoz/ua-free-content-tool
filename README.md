# UA FREE Content Tool

**A privacy-first Windows desktop application for collecting, manually grouping, rewriting, scheduling, and cross-posting news.**

UA FREE Content Tool gives a human editor one local workflow for the full news-production cycle: collect materials from configured sources, manually combine reports about the same event, create one concise publication with a local Ollama model, attach media from Google Drive, schedule the package, and publish it sequentially to Facebook Pages, Threads, LinkedIn, and Telegram.

> **Public release:** `v1.1.1`
> **Platform:** Windows 10/11, portable
> **Interface and output languages:** Ukrainian and English
> **License:** GPL-2.0-or-later

## Why this application exists

A normal editorial workflow is usually scattered across an RSS reader, browser tabs, messengers, a text editor, a local LLM, a scheduling sheet, and separate social-platform dashboards. UA FREE Content Tool brings those steps into one local Windows application while keeping factual and editorial decisions under human control.

The application does not decide on its own that different materials describe the same event. It keeps incoming items separate, helps the editor find likely matches, and merges them only after explicit confirmation.

The main editorial output is **one canonical publication of up to 900 characters** for all selected platforms. The language selected in Settings controls both the interface and Ollama output. Threads may technically split a longer approved payload into a main post and replies when platform limits require it, but the editorial content remains one canonical publication.

## What is new in v1.1.1

- Ukrainian and English interface modes.
- The selected language controls Ollama rewrite, repair, compression, fact-card, and final output language.
- Publication History with rewritten headlines, Kyiv date/time, destination networks, statuses, links, and available engagement metrics.
- Manageable permanent exclusions: inspect, deactivate selected rules, or clear all active rules.
- Approved stories older than 24 hours leave the working Inbox while remaining in Publication History.
- Safe recovery from truncated model JSON so raw structured output never becomes the publication text.
- A dedicated topic-candidate window replaces candidate marking across the full Inbox.
- Local learning records approved edits, generated rewrites, manual merges, rejected candidate pairs, permanent exclusions, and restored exclusions.
- Learning statistics, configurable prompt-example limits, export, import, and history clearing.
- Separate Ukrainian and English editorial memories and topic-feedback signatures.
- Visible Inbox scrollbar, keyboard paging, position preservation, and approved-row highlighting.
- Separate Facebook and Threads App IDs and App Secrets.
- Automatic database migration from schema 7 to schema 8 while preserving sources, content, settings, learning data, and the publication queue.

See [RELEASE_NOTES_v1.1.1.md](RELEASE_NOTES_v1.1.1.md) and [CHANGELOG.md](CHANGELOG.md).

## Core workflow

1. **Collect materials.** Enabled sources are checked and separate incoming blocks are created.
2. **Select manually.** The editor uses `Shift`, `Ctrl`, or `Ctrl+A`.
3. **Find candidates.** **Find everything on this topic** opens a focused list of likely related materials without merging them.
4. **Group manually.** Reports about the same event are merged only after explicit editor confirmation.
5. **Rewrite locally.** Ollama receives all source materials in the block and produces a concise draft in the selected language.
6. **Edit and approve.** A human verifies facts, wording, and length.
7. **Attach media.** One private Google Drive image or video can be attached.
8. **Schedule.** The package is added to the queue with selected platforms and publication time.
9. **Publish sequentially.** Targets are processed one by one and each platform keeps its own status.
10. **Retry safely.** Only failed targets are retried; successful publications are not duplicated.

## Main capabilities

### Collection and editorial work

- Collect current news from configured sources.
- Check enabled sources automatically after startup and every five minutes.
- Keep incoming items separate until a human decides to merge them.
- Support range and multi-selection through `Shift`, `Ctrl`, and `Ctrl+A`.
- Navigate lists with Page Up, Page Down, Home, and End.
- Preserve list position after refreshes and actions.
- Review topic candidates in a dedicated dialog.
- Merge related reports manually.
- Delete irrelevant materials without teaching a permanent rule.
- Use **Remember and exclude** to suppress highly similar future content.
- Restore an exclusion when a previously rejected block is accepted again.
- Highlight approved rows without showing the confusing former “in work” status.

### Local rewrite and learning

- Use local Ollama without requiring a paid LLM API.
- Include all sources from a merged block.
- Produce one final Ukrainian or English publication according to Settings.
- Target a maximum length of 900 characters.
- Maximize factual density and minimize filler.
- Reject empty, speculative, wrong-language, or non-news output.
- Re-run the rewrite after the source composition changes.
- Keep the manually approved final text as the canonical publication text.
- Store Ukrainian and English editorial examples separately.
- Record local learning events for generated rewrites, approved publications, manual merges, rejected candidates, and exclusions.
- Export, import, inspect, and clear local learning history.
- Keep learning data on the operator’s computer; it is not uploaded to a cloud training service.

### Queue and reliability

- Keep a separate publication history outside the working Inbox.
- Show rewritten headlines, actual publication time, networks, statuses, stored links, and available engagement metrics.
- Schedule publications for later delivery.
- Store a separate status for every target platform.
- Preserve attempts, errors, and remote IDs.
- Recover overdue or paused packages.
- Reschedule without repeating targets that already succeeded.
- Process targets sequentially with controlled pauses.
- Prevent a second simultaneous application process.
- Use SQLite with WAL, foreign keys, and `synchronous=FULL`.
- Preserve pending items, target statuses, attempts, remote IDs, learning data, and exclusion rules during migration.
- Create and import complete backups from the interface.

### Platforms and media

- Facebook Pages.
- Threads.
- LinkedIn.
- Telegram.
- Private Google Drive files.
- Automatic token and permission diagnostics after startup and every six hours.
- Distinct states for valid credentials, expired tokens, missing permissions, temporary network failures, and unconfigured integrations.
- Separate Facebook and Threads application credentials.
- Temporary `anyone/reader` access only for the specific Drive file required by Threads.
- Revocation of only the permission created by the application.
- Drive-file deletion only after all selected publications succeed.

## Platform behavior

| Platform | Publication | Media | Notes |
|---|---|---|---|
| Facebook Pages | One post | Image or video | Pages and Page Access Tokens are loaded through `/me/accounts`; API pagination is supported. |
| Threads | Main post and replies when required | Image or video | The application temporarily exposes only the selected Drive file. Topic search requires a separate permission. |
| LinkedIn | One professional post | Image or video | Uses the personal profile and the `w_member_social` permission. |
| Telegram | One post or media with caption | Image or video | The bot must be a channel administrator and have `can_post_messages`. |

## Requirements

### Ready Windows portable build

- Windows 10 or Windows 11.
- Ollama installed separately.
- A compatible local model configured in the application.
- Internet access for collection, Google Drive, and social platforms.
- Credentials only for the platforms you intend to use.
- A Google Cloud OAuth client of type `Desktop app` for Google Drive.

Ollama and model files are **not included** in the portable archive and must be installed separately on every computer.

### Development from source

- Python 3.11–3.13.
- `requirements.txt` for runtime dependencies.
- `requirements-test.txt` for validation.
- `requirements-build.txt` for the Windows build.

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
2. Download `UA_FREE_Content_Tool_v1.1.1_Windows_Portable.zip`.
3. Verify its SHA-256 against `SHA256SUMS.txt`.
4. Extract the complete archive. Do not run the EXE from inside the ZIP.
5. Install Ollama and the selected model.
6. Run `UA_FREE_Content_Tool.exe` without administrator rights.
7. Open **Settings** and choose Ukrainian or English.
8. Configure sources and only the platform credentials you intend to use.
9. Verify every required connection.
10. Back up the complete application folder before the first live publication and before every update.

## Updating from v1.0.0

1. Close the application completely.
2. Confirm in Task Manager that `UA_FREE_Content_Tool.exe` is no longer running.
3. Copy the complete existing application folder to a backup location.
4. Extract v1.1.1 into a separate folder.
5. Copy the complete existing `Data` folder into the new portable application folder.
6. Start v1.1.1 and confirm that sources, settings, learning data, and the queue are present.
7. Keep the v1.0.0 backup until the first successful live publication from v1.1.1.

Do not replace only the EXE. The portable build also contains the version-specific `_internal` directory.

## Portable data, backups, and updates

The `Data` folder next to the EXE contains the working state:

- SQLite database;
- encrypted portable configuration;
- encrypted platform tokens and Google refresh token;
- sources and incoming blocks;
- manual merges;
- language-separated editorial memory and topic feedback;
- local learning events and exclusion rules;
- queue, target statuses, attempts, and remote IDs;
- operational logs.

To create a manual backup:

1. Close the application.
2. Confirm in Task Manager that the process has stopped.
3. Copy the **entire `UA_FREE_Content_Tool` folder**, not only the EXE.
4. Keep the previous working copy until the first successful live publication with the new version.

`Data\config.portable` and `Data\portable.key` form one pair. Do not delete, rename, or move them separately. Physical access to the complete portable folder may permit access to stored credentials.

See [PORTABLE_MODE.md](PORTABLE_MODE.md) for details.

## Platform setup

### Facebook Pages

Provide the Facebook App ID, Facebook App Secret, and a valid Facebook User Access Token. The application calls `/me/accounts` to retrieve available pages and their Page Access Tokens, including pagination pages. An expired token must be replaced before it can be exchanged.

### Threads

Provide the Threads App ID, Threads App Secret, and Threads access token separately from Facebook credentials.

Required publication permissions:

```text
threads_basic
threads_content_publish
```

`threads_keyword_search` is additionally required for topic and trend comparison. Its absence does not block normal publishing.

### LinkedIn

Required permissions:

```text
openid
profile
w_member_social
```

The application resolves the personal profile through the API.

### Telegram

Provide the Bot Token and channel username or ID. The bot must be a channel administrator with `can_post_messages`.

### Google Drive

Create a Google Cloud project, enable Google Drive API, configure the OAuth consent screen, and create an OAuth Client ID of type `Desktop app`. Files remain private except for the short technical interval when Threads requires a public media URL.

See [PLATFORM_SETUP.md](PLATFORM_SETUP.md) for complete setup instructions.

## Privacy and security

UA FREE Content Tool is a local application with no built-in telemetry about editorial work.

- Portable configuration is encrypted with AES-GCM.
- Tokens are not stored in SQLite.
- Secrets are masked in the interface and normal errors.
- External URLs pass through network safeguards.
- Private and non-global destinations are rejected for external fetches.
- Google Drive uses OAuth.
- Temporary public access is created only for the selected file when Threads requires it.
- Local learning data remains on the operator’s computer unless explicitly exported.

Never publish:

- a real `Data` folder;
- `config.portable` and `portable.key`;
- SQLite database, WAL, or SHM files;
- access tokens, app secrets, client secrets, or refresh tokens;
- private Drive links;
- logs or screenshots containing secrets or personal data.

See [SECURITY_NOTES.md](SECURITY_NOTES.md).

## Repository structure

```text
.github/                       issue templates, CI, and release workflow
content_agent/
  data/                        bundled static data
  ui/                          Tkinter interface
  main.py                      application entry point
  database.py                  SQLite schema and migrations
  collectors.py                source collection
  rewriter.py                  bilingual Ollama rewrite and validation
  editorial_memory.py          local editorial memory and ranking
  i18n.py                      localization layer
  i18n_extra.py                secondary dialog and status catalog
  publishers.py                Facebook, Threads, LinkedIn, Telegram
  google_drive.py              OAuth and media workflow
  scheduling.py                scheduling
  worker.py                    queue execution
  security.py                  network and secret boundaries
tests/                         automated tests
tools/                         smoke, localization, and artifact validation tools
docs/history/                  stabilization history
docs/validation/               validation reports
app.py                         launcher
Build_Portable_Windows.bat     version-aware Windows portable build
requirements*.txt              runtime, test, and build dependencies
FILE_MANIFEST.sha256           SHA-256 repository manifest
VERSION.txt                    internal version
PUBLIC_VERSION.txt             public version
```

## Build the Windows portable package

```bat
Build_Portable_Windows.bat
```

The script reads `PUBLIC_VERSION.txt`, creates an isolated build environment, installs pinned dependencies, runs validation, and writes the portable package under:

```text
Release\UA_FREE_Content_Tool_v<version>\UA_FREE_Content_Tool
```

## Validation of v1.1.1

Completed release-preparation checks:

- `238 passed` in pytest on Windows with Python 3.12;
- successful `compileall`;
- entry-point import checks;
- successful `import content_agent.main`;
- zero untranslated visible Ukrainian literals in the audited interface windows;
- migration coverage for schema 7 to schema 8;
- language separation for editorial memory and topic feedback;
- learning export/import coverage for permanent exclusions;
- compatibility coverage for previous queue, timeout, token, selection, and rewrite regressions.

The public release gate also runs the Windows CI matrix on Python 3.11, 3.12, and 3.13 and builds the portable PyInstaller package. Automated validation does not replace live testing with real platform accounts. Live behavior depends on current tokens, roles, permissions, API policies, account state, and network conditions.

## Documentation

- [README.md](README.md) — complete project overview.
- [PLATFORM_SETUP.md](PLATFORM_SETUP.md) — platform credentials and Google Drive.
- [PORTABLE_MODE.md](PORTABLE_MODE.md) — portable data, migration, and backups.
- [SECURITY_NOTES.md](SECURITY_NOTES.md) — security boundaries.
- [RELEASE_NOTES_v1.1.1.md](RELEASE_NOTES_v1.1.1.md) — current release notes.
- [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md) — previous release notes.
- [CHANGELOG.md](CHANGELOG.md) — version history.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution rules.
- [docs/MAINTAINER_RELEASE_GUIDE.md](docs/MAINTAINER_RELEASE_GUIDE.md) — release procedure.
- [docs/history/DEVELOPMENT_HISTORY_R8_FIX30.md](docs/history/DEVELOPMENT_HISTORY_R8_FIX30.md) — v1.0.0 stabilization history.
- [docs/validation/WINDOWS_GATE_SUMMARY_R8_FIX30.md](docs/validation/WINDOWS_GATE_SUMMARY_R8_FIX30.md) — v1.0.0 Windows Gate summary.

<!-- SETUP_MANUALS_START -->
## Complete setup manuals

- [English: complete installation and configuration manual (PDF)](docs/manuals/UA_FREE_Content_Tool_Complete_Setup_Manual_EN.pdf)
- [Українською: повний посібник зі встановлення та налаштування (PDF)](docs/manuals/UA_FREE_Content_Tool_Complete_Setup_Manual_UA.pdf)

The manuals cover installation, checksum verification, Ollama, every supported platform, Google Drive media, source collection, editorial workflow, scheduling, queue recovery, backups, migration, security, live-publication checklists, and troubleshooting. Some screenshots and labels may reflect v1.0.0 until the manuals are regenerated for v1.1.1.
<!-- SETUP_MANUALS_END -->

## Bug and vulnerability reports

A GitHub Issue should include the application version, Windows version, Ollama model, reproduction steps, expected result, actual result, and a sanitized log excerpt.

Do not publish secrets. Vulnerability reports may be sent to `kozyriev@uafree.org` with the affected version, reproduction steps, and impact. Remove all real credentials and personal data.

## Contributing

Before opening a pull request, run:

```bat
python -m compileall -q .
python -m pytest -q
python tools\check_entrypoint_imports.py
python tools\audit_v1_1_i18n.py
python -c "import content_agent.main"
```

A contribution must not add real tokens or working `Data`, weaken URL or secret checks, merge news automatically without editor approval, duplicate successful publications during retry, or modify the database without a migration and tests.

## Support

### UA FREE charitable foundation

- [Donate to UA FREE](https://uafree.org/donate/)
- [UA FREE website](https://uafree.org/)

### Application development

- **PayPal:** `kozyriev@uafree.org`
- [Donate through PayPal](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=kozyriev%40uafree.org&item_name=Support+UA+FREE+Content+Tool+development&currency_code=USD)
- **BTC:** `bc1q4dn8e7sz2866g7qp1qtshh98j54tvuau5ghuuk`
- **ETH / USDC ERC-20:** `0x3aE3b23A7BD94b8a65A7E8Ca205A4e29BEF7c229`
- **USDT TRC-20:** `TYsGyK7K3XB4NPHprf5w8ZodFafxFfDdbP`

Application-development donations are separate from donations to the charitable foundation. Use only the network shown next to each cryptocurrency address.

## Project background

UA FREE Content Tool grew from real content operations rather than from a generic social-media demonstration. Development, review, and part of the test preparation used OpenAI ChatGPT. Final product decisions, editorial responsibility, credential handling, and live publication validation remain under human control.

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
