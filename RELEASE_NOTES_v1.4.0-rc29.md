# UA FREE Content Tool v1.4.0-rc29

RC29 fixes the contradictory Codex install/check flow seen live in RC28.

- After a successful side-by-side Codex install, the app now automatically relaunches the signed portable executable after the current process releases its single-instance lock.
- The UI no longer reports a generic completed install and then lets the same stale process immediately claim that the SDK is missing.
- The install operation now says that the runtime is prepared for restart, which is the actual state at that moment.
- Fixed the RC28 installer failure path typo so failed pip staging raises `CodexEngineError` instead of a `NameError`.
- RC28 AI timeout, fallback ordering, cooldown, and safe side-by-side runtime changes remain intact.
