# UA FREE Content Tool v2.0.0-rc13

RC13 fixes the version-label regression discovered in the RC12 Windows Portable package.

## Version source

- The startup window and main application title no longer contain a hardcoded RC11 version string.
- Runtime UI version labels now read from the same root `VERSION.txt` used by the release workflow.
- `PUBLIC_VERSION.txt` and `VERSION.txt` are both `2.0.0-rc13`.
- Added regression tests that fail if the active startup/main-window code reintroduces the RC11 literal or diverges from `VERSION.txt`.

## Scope

RC13 contains the full RC12 runtime and diagnostics behavior unchanged. This release only corrects version identity in the UI and removes the source of future UI/release version drift.
