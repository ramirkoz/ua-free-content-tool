# UA FREE Content Tool v1.1.2

Patch release for publication analytics and evidence-based editorial scoring.

## Refresh all publication metrics

Publication History now includes **Refresh all metrics**. The operation:

- processes every sent network target in the local history;
- runs in the background and keeps the interface responsive;
- shows processed/total progress, successful metric responses, errors, and skipped calls;
- isolates failures by platform;
- stops repeating calls to the same configured platform after two matching global DNS, timeout, token, or permission errors;
- preserves previously collected metrics when a later refresh fails;
- never republishes or changes the original publication timestamp.

The existing selected-publication refresh remains available for targeted checks.

## Historical performance forecast

The former **Evaluate virality** action is now **Evaluate potential**. It calculates two separate signals:

1. current Threads topic activity;
2. an evidence-based forecast from this installation's own publication history.

The historical forecast:

- compares the current material with previous rewritten headlines and publication texts;
- uses only targets for which real metrics were collected;
- ignores unavailable metrics instead of treating them as zero;
- normalizes results separately by platform so Facebook, Threads, and LinkedIn are not compared by raw counts;
- adjusts cumulative metrics for the observation window;
- gives recent and topically similar publications more weight;
- returns a relative score from 0 to 100, confidence, the number of measured publications, comparable publications, and per-network scores where available.

A score of 50 means a typical result relative to the user's own measured history. The application refuses to present a forecast until at least five historical publications contain usable metrics.

## Validation

- 251 automated tests in the complete suite.
- Python compilation and application import checks.
- Interface localization audit with zero untranslated audited literals.
- Windows CI and portable build remain release gates.

## Updating

v1.1.2 uses database schema 8, the same as v1.1.0 and v1.1.1. Close the old application, extract the new portable release into a separate folder, and copy the complete existing `Data` folder. Do not replace only the EXE.
