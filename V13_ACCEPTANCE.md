# UA FREE Content Tool 1.3 acceptance

Status: **RC1 / not stable**

Baseline: live-accepted `v1.2.2`.

## RC1 scope

- deterministic Evidence Pack before rewrite;
- deterministic Fact Guard after rewrite;
- adaptive second provider only when first candidate is blocked or weak;
- bounded task-aware rewrite budgets;
- editorial memory isolated from factual evidence;
- persistent Source Health diagnostics without a database schema bump;
- production entrypoint moved to `ui.v1_3_window` while retaining the accepted v1.2.2 behavior underneath.

## Protected mechanisms

The RC1 work must not change the accepted global duplicate engine, manual merge confirmation, Media Engine, multi-image workflow, platform publishers, publication queue semantics, scheduling, AES-GCM provider secret format, or existing Data contents.

## Promotion gate

Stable `1.3.0` is allowed only after:

- full Windows CI PASS on Python 3.11 / 3.12 / 3.13;
- deterministic v1.3 logic gate PASS;
- signed Windows portable build PASS;
- GUI startup smoke PASS;
- Microsoft Defender runtime + ZIP scans PASS;
- ZIP integrity/version/safety gate PASS;
- live test using a COPY of the current working v1.2.2 `Data`;
- live rewrite PASS and no reported regression in duplicate grouping, media, queue or publication.
