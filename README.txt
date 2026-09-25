UA FREE Content Tool v2.0.0-rc35 — MANUAL TEST

Cumulative Fact Guard hotfix. Import from RC33 Data on first launch.
Supervisor keeps a stable instance identity and publishes a CURRENT pointer in Google Drive.
Old logs/cache/Tools/runtime state are not imported.

RC34 fixes retained:
- apostrophe-grouped thousands (1’279, 609’278, 1'279, 1ʼ279) normalize to 1279/609278;
- short units m/м and similar tokens require a word boundary, so “25 моделей” is not misread as “25 m”.

RC35:
- valid Roman numerals such as XXI are normalized as numeric facts (XXI = 21);
- Roman numerals are no longer treated as Latin names/models;
- mismatched Roman values remain blocked (XXII does not match source 21).

Fact Guard strictness remains enabled.
