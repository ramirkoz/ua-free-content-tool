# UA FREE Content Tool

**A privacy-first Windows desktop application for collecting, manually grouping, rewriting, scheduling, and cross-posting Ukrainian news.**

UA FREE Content Tool gives a human editor one local workflow for the full news-production cycle: collect materials from configured sources, manually combine reports about the same event, create one concise Ukrainian-language publication with a local Ollama model, attach media from Google Drive, schedule the package, and publish it sequentially to Facebook Pages, Threads, LinkedIn, and Telegram.

> **Public release:** `v1.0.0`  
> **Internally validated build:** `R8 FIX30`  
> **Platform:** Windows 10/11, portable  
> **Interface language:** Ukrainian  
> **License:** GPL-2.0-or-later

## Why this application exists

A normal editorial workflow is usually scattered across an RSS reader, browser tabs, messengers, a text editor, a local LLM, a scheduling sheet, and separate social-platform dashboards. UA FREE Content Tool brings those steps into one local Windows application while keeping factual and editorial decisions under human control.

The application does not decide on its own that different materials describe the same event. It keeps incoming items separate, helps the editor find likely matches, and merges them only after explicit confirmation.

The main editorial output is **one canonical Ukrainian-language publication of up to 900 characters** for all selected platforms. Threads may technically split a longer approved text into a main post and replies, but the content remains one canonical publication.

## Core workflow

1. **Collect materials.** Enabled sources are checked and separate incoming blocks are created.
2. **Select manually.** The editor uses `Shift`, `Ctrl`, or `Ctrl+A`.
3. **Find candidates.** **Find everything on this topic** highlights likely related materials without merging them.
4. **Group manually.** Reports about the same event are merged into one working block.
5. **Rewrite locally.** Ollama receives all source materials in the block and produces a concise Ukrainian-language draft.
6. **Edit and approve.** A human verifies facts, wording, and length.
7. **Attach media.** One private Google Drive image or video can be attached.
8. **Schedule.** The package is added to the queue with selected platforms and publication time.
9. **Publish sequentially.** Targets are processed one by one and each platform keeps its own status.
10. **Retry safely.** Only failed targets are retried; successful publications are not duplicated.

## Main capabilities

### Collection and editorial work

- Collect current news from configured sources.
- Keep incoming items separate until a human decides to merge them.
- Support range and multi-selection through `Shift`, `Ctrl`, and `Ctrl+A`.
- Merge related reports manually.
- Highlight topic candidates without automatic grouping.
- Delete irrelevant materials.
- Use **Remember and exclude** to suppress highly similar future content.
- Build local editorial memory from approved human edits.

### Local rewrite

- Use local Ollama without requiring a paid LLM API.
- Include all sources from a merged block.
- Produce one final Ukrainian-language publication.
- Target a maximum length of 900 characters.
- Maximize factual density and minimize filler.
- Reject English, Russian, speculative, or non-news output.
- Re-run the rewrite after the source composition changes.
- Keep the manually approved final text as the canonical publication text.

### Queue and reliability

- Schedule publications for later delivery.
- Store a separate status for every target platform.
- Preserve attempts, errors, and remote IDs.
- Recover overdue or paused packages.
- Reschedule without repeating targets that already succeeded.
- Process targets sequentially with controlled pauses.
- Prevent a second simultaneous application process.
- Use SQLite with WAL, foreign keys, and `synchronous=FULL`.
- Test migrations for preservation of pending items, target statuses, attempts, and remote IDs.

### Platforms and media

- Facebook Pages.
- Threads.
- LinkedIn.
- Telegram.
- Private Google Drive files.
- Automatic token and permission diagnostics after startup and every six hours.
- Distinct states for valid credentials, expired tokens, missing permissions, temporary network failures, and unconfigured integrations.
- Temporary `anyone/reader` access only for the specific Drive file required by Threads.
- Revocation of only the permission created by the application.
- Drive-file deletion only after all selected publications succeed.

## Platform behavior

| Platform | Publication | Media | Notes |
|---|---|---|---|
| Facebook Pages | One post | Image or video | Pages and Page Access Tokens are loaded through `/me/accounts`; API pagination is supported without an artificial two-page limit. |
| Threads | Main post and replies when required | Image or video | Longer canonical text is split without dropping content; the application temporarily exposes only the selected Drive file. |
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
2. Download the Windows portable ZIP.
3. Verify its SHA-256 against `SHA256SUMS.txt`.
4. Extract the complete archive. Do not run the EXE from inside the ZIP.
5. Install Ollama and the selected model.
6. Run `UA_FREE_Content_Tool.exe` without administrator rights.
7. Open **Settings** and configure sources and platform credentials.
8. Verify every required connection.
9. Back up the complete application folder before the first live publication and before every update.

## Portable data, backups, and updates

The `Data` folder next to the EXE contains the working state:

- SQLite database;
- encrypted portable configuration;
- encrypted platform tokens and Google refresh token;
- sources and incoming blocks;
- manual merges;
- editorial memory and exclusion rules;
- queue, target statuses, attempts, and remote IDs;
- operational logs.

To create a backup:

1. Close the application.
2. Confirm in Task Manager that the process has stopped.
3. Copy the **entire `UA_FREE_Content_Tool` folder**, not only the EXE.
4. Keep the previous working copy until the first successful live publication with the new version.

`Data\config.portable` and `Data\portable.key` form one pair. Do not delete, rename, or move them separately. Physical access to the complete portable folder may permit access to stored credentials.

See [PORTABLE_MODE.md](PORTABLE_MODE.md) for details.

## Platform setup

### Facebook Pages

Provide a Meta App ID, Meta App Secret, and a valid Facebook User Access Token. The application calls `/me/accounts` to retrieve all available pages and their Page Access Tokens, including additional pagination pages. An expired token must be replaced before it can be exchanged.

### Threads

Required permissions:

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
  rewriter.py                  Ollama rewrite and validation
  editorial_memory.py          local editorial memory
  publishers.py                Facebook, Threads, LinkedIn, Telegram
  google_drive.py              OAuth and media workflow
  scheduling.py                scheduling
  worker.py                    queue execution
  security.py                  network and secret boundaries
tests/                         automated tests
tools/                         smoke and artifact validation tools
docs/history/                  stabilization history
docs/validation/               validation reports
app.py                         launcher
Build_Portable_Windows.bat     Windows portable build
requirements*.txt              runtime, test, and build dependencies
FILE_MANIFEST.sha256           SHA-256 manifest
VERSION.txt                    internal build version
PUBLIC_VERSION.txt             public version
```

## Build the Windows portable package

```bat
Build_Portable_Windows.bat
```

The script creates an isolated build environment, installs pinned dependencies, runs validation, and writes the portable package under `Release`.

## Validation of v1.0.0

Public version `v1.0.0` corresponds to internal build `R8 FIX30`.

Validated checks include:

- `223 passed` in pytest;
- successful `compileall`;
- entry-point import checks;
- successful `import content_agent.main`;
- local smoke test;
- Windows portable build and startup;
- preservation of schema, settings, and queue state;
- Shift multi-selection in Incoming and Queue views;
- rejection of English, Russian, and non-grounded rewrite output;
- manifest, CRC, canonical root, duplicate-name, path-traversal, absolute-path, backslash, and symlink checks.

The raw Windows Gate evidence is stored in [docs/validation/WINDOWS_GATE_REPORT_R8_FIX30.txt](docs/validation/WINDOWS_GATE_REPORT_R8_FIX30.txt). It preserves literal console output, including original Ukrainian UI strings and test paths. The English summary is [docs/validation/WINDOWS_GATE_SUMMARY_R8_FIX30.md](docs/validation/WINDOWS_GATE_SUMMARY_R8_FIX30.md).

Automated Windows Gate validation does not replace live testing with real platform accounts. Live behavior depends on current tokens, roles, permissions, API policies, and network conditions.

## Documentation

- [README.md](README.md) — complete project overview.
- [PLATFORM_SETUP.md](PLATFORM_SETUP.md) — platform credentials and Google Drive.
- [PORTABLE_MODE.md](PORTABLE_MODE.md) — portable data, migration, and backups.
- [SECURITY_NOTES.md](SECURITY_NOTES.md) — security boundaries.
- [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md) — release notes.
- [CHANGELOG.md](CHANGELOG.md) — version history.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution rules.
- [docs/MAINTAINER_RELEASE_GUIDE.md](docs/MAINTAINER_RELEASE_GUIDE.md) — release procedure.
- [docs/history/DEVELOPMENT_HISTORY_R8_FIX30.md](docs/history/DEVELOPMENT_HISTORY_R8_FIX30.md) — stabilization history.
- [docs/history/STABILIZATION_DECISION_R8_FIX30.md](docs/history/STABILIZATION_DECISION_R8_FIX30.md) — final stabilization decision.
- [docs/history/UPDATE_FIX29_TO_FIX30.md](docs/history/UPDATE_FIX29_TO_FIX30.md) — program-only update procedure.
- [docs/validation/LOCAL_REVALIDATION_REPORT_R8_FIX30.md](docs/validation/LOCAL_REVALIDATION_REPORT_R8_FIX30.md) — local revalidation.
- [docs/validation/WINDOWS_GATE_SUMMARY_R8_FIX30.md](docs/validation/WINDOWS_GATE_SUMMARY_R8_FIX30.md) — English Windows Gate summary.

## Bug and vulnerability reports

A GitHub Issue should include the application version, Windows version, Ollama model, reproduction steps, expected result, actual result, and a sanitized log excerpt.

Do not publish secrets. Vulnerability reports may be sent to `kozyriev@uafree.org` with the affected version, reproduction steps, and impact. Remove all real credentials and personal data.

## Contributing

Before opening a pull request, run:

```bat
python -m compileall -q .
python -m pytest -q
python tools\check_entrypoint_imports.py
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
