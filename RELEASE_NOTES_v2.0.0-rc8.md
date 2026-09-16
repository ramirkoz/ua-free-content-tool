# UA FREE Content Tool v2.0.0-rc8

RC8 ports the provider-recovery work proven in Telegram Autopilot into Content Tool and adds a narrow remote operations channel through the already-authorized Google Drive Supervisor.

## AI Router recovery

- Direct Gemini, Groq, NVIDIA and Cloudflare traffic now uses fixed-host provider transport isolated from crawler networking.
- Adds conservative per-provider pacing so background work cannot self-trigger RPM limits as easily.
- Retries short HTTP 429 and 5xx/503 failures with bounded backoff and respects `Retry-After` / Google-style retry delay hints.
- Treats a bare HTTP 429 as a transient rate limit unless the provider explicitly reports hard daily/account/billing quota exhaustion.
- Gemini can fall back from `gemini-3.5-flash` to reviewed Flash-Lite lanes.
- Groq updates Qwen from 3.6 to 3.8 and can fall back from the requested model to `openai/gpt-oss-20b`.
- NVIDIA capacity/503 failures are retried before normal router failover to the second reviewed NVIDIA model.
- Existing direct-router secrets, route scoring, local Ollama/llama.cpp fallback, Codex integration and QA contracts remain compatible.
- OpenRouter / direct Router / Agent remain explicit selectable backends; RC8 does not silently consume credentials from another backend.

## Remote Supervisor operations

- Existing Supervisor reporting remains active and continues exporting status, incidents, reports and diagnostics to Google Drive.
- Each installation now owns an `INSTANCES/<instance>/CONTROL` folder inside the configured Supervisor Drive root.
- The remote protocol accepts only three fixed commands: `report`, `restart`, and `update`.
- Requests are instance-scoped, time-bounded and deduplicated by request ID. Arbitrary shell commands, paths, executable URLs and scripts are not supported.
- Remote restart uses the existing detached signed-runtime relaunch path.

## Fail-safe remote update

- `update` accepts only a newer `2.0.0-rcN` version.
- The application resolves the exact portable ZIP from the fixed `ramirkoz/ua-free-content-tool` GitHub Release; the remote request cannot inject another download URL.
- Before shutdown the updater downloads and stages the package, verifies the GitHub-published SHA-256 digest, validates archive paths, validates version metadata and checks the signed launcher with Authenticode.
- The detached updater replaces the runtime while preserving the entire existing `Data` directory.
- The new version must publish a startup-health marker. If it cannot prove healthy startup, the updater restores the previous runtime and restarts it.
- Final update/rollback results are returned through the same per-instance Supervisor control channel.

Existing RC7 `Data` remains compatible. No destructive database migration is introduced.
