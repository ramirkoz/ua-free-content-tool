UA FREE Content Tool v2.0.0-rc34 — MANUAL TEST

Fact Guard numeric-normalization hotfix. Import from RC33 Data on first launch.
Supervisor keeps a stable instance identity and publishes a CURRENT pointer in Google Drive.
Old logs/cache/Tools/runtime state are not imported.

RC34 hotfix:
- apostrophe-grouped thousands (1’279, 609’278, 1'279, 1ʼ279) normalize to the same quantity as 1279/609278;
- short units m/м and similar tokens require a word boundary, so “25 моделей” is no longer misread as “25 m”;
- Fact Guard strictness is unchanged: genuinely unsupported numbers remain blocked.
