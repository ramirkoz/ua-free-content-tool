# UA FREE Content Tool 2.0.0-rc42

Focused Instagram multi-account UX candidate.

## Changes

- Keeps the existing v1.4 multi-account Instagram destination catalog and per-profile publishing routes.
- Makes the Instagram settings block compact by default so it no longer permanently consumes the Settings tab height.
- Adds an explicit expand/collapse control for the discovered Instagram account table.
- Keeps `Знайти / оновити всі акаунти` discovery through the connected Facebook Pages.
- Makes the UI state explicit that each discovered Instagram profile is a separate publication destination and that one or several profiles can be selected before publishing.
- Preserves legacy encrypted Instagram ID/token fields for old Data compatibility without exposing the old one-account form as the primary workflow.
- Retains the RC41 Google Drive authorization recovery fix unchanged.

## Verification target

RC42 is a focused manual-test candidate. The targeted gate must compile the application, run the Instagram multi-account regressions plus existing v1.4 destination tests and RC41 Drive-auth regressions, and build the Windows portable artifact.

The repository-level full-suite debt recorded for RC41 remains a separate gate and must not be presented as fixed by this Instagram-only change.
