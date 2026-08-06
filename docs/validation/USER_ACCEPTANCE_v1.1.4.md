# User Acceptance and Final Synchronization — v1.1.4

Date: 2026-08-06

## Acceptance status

The operator confirmed that the installed UA FREE Content Tool v1.1.4 works and requested final project synchronization.

This confirmation establishes operational acceptance of the v1.1.4 installation and the changes delivered in this release. It is not represented as a separate logged end-to-end proof for every external social-platform API.

## Fixed release identity

- Release: `v1.1.4`
- Release commit: `d31429e8e2faa663add45f124205b7719cb45027`
- Windows Portable SHA-256: `3c88c7afe53a36dd16ef25a26c633160b769d5a4f5cbb54a0bad7cf2042dae87`
- Source ZIP SHA-256: `f567bf729cd444015bb67b35d6e0334864116e1847c00daccd28c26294345fad`

The release tag and release assets remain immutable. This documentation commit does not modify the published v1.1.4 bytes.

## Release validation

- Windows CI on Python 3.11, 3.12 and 3.13: PASS
- Complete test suite: 258 tests PASS
- Entrypoint and package import checks: PASS
- Signed Python Software Foundation runtime: PASS
- Portable startup and Tkinter smoke: PASS
- Microsoft Defender scan of extracted runtime: no threats found
- Microsoft Defender scan of final Windows ZIP: no threats found
- ZIP CRC, path-safety, duplicate-entry and executable-set validation: PASS
- Runtime data, databases, logs and secrets excluded from the release ZIP: PASS

## Google Drive synchronization

Project Vault: `UA FREE Content Tool — Project Vault`

Final public release mirror:

- `08_PUBLIC_RELEASES/v1.1.4 — 2026-08-06/UA_FREE_Content_Tool_v1.1.4_Windows_Portable.zip`
- `08_PUBLIC_RELEASES/v1.1.4 — 2026-08-06/UA_FREE_Content_Tool_v1.1.4_Source.zip`
- `08_PUBLIC_RELEASES/v1.1.4 — 2026-08-06/SHA256SUMS.txt`

The Project Index was updated to `PUBLIC RELEASE v1.1.4 / WINDOWS RELEASE GATE PASS / USER ACCEPTANCE PASS / GITHUB AND GOOGLE DRIVE SYNCHRONIZED`.

## Baseline decision

v1.1.4 is the stable public baseline for subsequent development. New functionality should be developed in feature branches. A new emergency stabilization cycle should start only for a reproducible blocker, security issue, data loss, or duplicate publication.
