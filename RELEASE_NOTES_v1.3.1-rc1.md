# UA FREE Content Tool v1.3.1-rc1

Emergency publication-queue safety hotfix based on live v1.3.0.

- Google Drive/media preflight failures now use bounded retry/backoff and pause after 3 automatic attempts.
- Preflight Drive reads are cancellable and hard-bounded; a stalled Drive read cannot keep the queue in an endless publish loop.
- Active package cancellation is cooperative: before a platform write it stops immediately; during a platform write it waits for the current outcome and prevents the next target.
- Packages abandoned as `in_progress`, and pending packages already beyond the retry cap, are paused on startup instead of being blindly reclaimed.
- Drive cleanup retries are bounded by the same automatic-attempt cap.
- Sent targets remain immutable; unknown platform outcomes still fail closed to prevent duplicate posts.
- No AI/rewrite/dedup/media-selection/publisher behavior changes.
