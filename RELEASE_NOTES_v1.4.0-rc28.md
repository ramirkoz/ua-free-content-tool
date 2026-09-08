# UA FREE Content Tool v1.4.0-rc28

RC28 is an AI-runtime recovery release based on the live RC27 failures.

- Codex / ChatGPT no longer gets killed by the RC27 24-second provider slice; the first Codex route now has up to 45 seconds inside one bounded AI-task deadline.
- Cloud first-attempt slices are raised to realistic values instead of 8–9 seconds.
- Local AI budgeting now matches the runtime's real 30-second minimum instead of asking for 12 seconds and silently consuming 30.
- Local fallback is tried after one route from each cloud provider, before secondary models can consume the remaining task budget.
- On the first RC28 runtime install in a process, stale short transient/bad-response cooldowns from RC27 are cleared once; quota, authentication, configuration, and model failures remain protected.
- Codex installation is now side-by-side. The updater never deletes or overwrites DLL/PYD files loaded by the running app, eliminating the Windows `WinError 5` failure on `pydantic_core`.
- A freshly installed Codex runtime is selected through a portable relative pointer and activates on restart when the old SDK is already loaded.
- RC27 stable rewrite parsing and multi-source synthesis remain unchanged.
