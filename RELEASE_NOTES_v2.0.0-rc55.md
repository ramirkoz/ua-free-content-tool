# UA FREE Content Tool 2.0.0-rc55

RC55 is the final consolidation, security, and repository-wide acceptance milestone for the 2.0.0 RC50–RC55 roadmap.

## Operator UI

- Canonical Inbox remains exactly `Подія | Тема | Джерел | Час`.
- Removed the obsolete upper `Пошук у Вхідних` / `Знайти` controls; the SQL FilterBar search is authoritative.
- Removed the `Колонки` / reset-columns action and legacy auto-column restore path that could resurrect hidden ID/status/score columns.
- Manual column resizing and persistence remain.
- `Склад блоку...` remains available for operator correction/removal of incorrectly grouped source items.

## Architecture and security

- `AppServices` owns collection and publication services through the composition root.
- No new version-numbered MainWindow layer and no resurrection of direct router monkey-patching.
- Updater requires a verified Ed25519 signed manifest, SHA-256 payload integrity, minimum updater version, and rollback metadata; invalid/missing signatures fail closed.
- Codex runtime installation is side-by-side and hash-locked before activation.

## Fact Guard and acceptance

- Numeric equivalence handles RU/UA currency abbreviations consistently.
- Unknown product/model tokens remain fail-closed without treating ordinary sentence-start English words as entities.
- The full repository test suite is a blocking RC55 release gate. The portable artifact is built only after that suite passes.
