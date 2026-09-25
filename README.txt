UA FREE Content Tool v2.0.0-rc36 — MANUAL TEST

Cumulative Fact Guard hotfix. Import from RC33 Data on first launch.
Supervisor keeps a stable instance identity and publishes a CURRENT pointer in Google Drive.
Old logs/cache/Tools/runtime state are not imported.

RC34 fixes retained:
- apostrophe-grouped thousands normalize correctly;
- short units m/м no longer consume the first character of ordinary words.

RC35 retained:
- valid Roman numerals normalize to numeric facts;
- Roman numerals are not treated as Latin names/models.

RC36:
- ordinary English words and sentence-initial Title Case words are no longer treated as model/entity facts;
- Fact Guard checks only high-confidence structured Latin identifiers such as OpenAI, GPT-5.4, RTX-5090 and short acronyms;
- Unicode numeric forms such as 💯 and keycap digits normalize before numeric comparison;
- genuinely new structured identifiers remain blocked.

Fact Guard remains strict for numbers, structured identifiers, high-risk strengthening and unsupported uncertainty.
