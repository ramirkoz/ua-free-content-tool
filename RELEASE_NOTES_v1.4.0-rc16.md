# UA FREE Content Tool v1.4.0-rc16

RC16 is a targeted reliability fix for AI rewrite Fact Guard false positives.

## Fixed

- Fact Guard now compares common numeric facts semantically across Russian, Ukrainian and English forms instead of comparing raw suffix strings.
- Equivalent values such as `500 тыс.`, `500 тис.`, `500 thousand`, `500k`, `500,000` and `0.5 million` normalize to the same numeric fact.
- Common million/billion forms are normalized across RU/UA/EN.
- Common units and currencies are normalized so translated forms such as `$0.5 million` and `500 тис. доларів` can pass when they are factually equivalent.
- Unit safety is preserved: `12 km` and `12 кг` are not treated as the same fact.
- Genuine new numbers remain blocked by Fact Guard.

## Regression coverage

Added RC16 regression tests for the exact failure class observed in live use, including Russian-source to Ukrainian-rewrite cases and English-source to Ukrainian-rewrite cases.

## Compatibility

- No database schema change.
- Existing portable `Data` is preserved.
- RC15 Inbox, Sources, schedules, publication flow and profile settings remain unchanged.
