UA FREE Content Tool v2.0.0-rc39 — MANUAL TEST

Cumulative recovery release on top of RC38.

RC39:
- hardens the full “Пошук схожих за темою матеріалів” route against malformed legacy group IDs imported from older databases;
- both UI paths use one safe candidate indexer instead of direct int(group_id) conversion;
- malformed legacy IDs such as “19…” are skipped, recorded as a local learning/diagnostic event, and no longer crash the whole topic search;
- valid candidates continue through local ranking and AI duplicate/topic analysis.

RC34-RC38 Fact Guard and RC37 scheduling/topic-search recovery fixes are retained.
