# UA FREE Content Tool 1.3 acceptance

Status: **LIVE ACCEPTED / STABLE PROMOTION AUTHORIZED**

Baseline: live-accepted `v1.2.2`.
Accepted candidate: `v1.3.0-rc3`.
Stable target: `v1.3.0`.
Live acceptance date: 2026-08-19.

## Accepted 1.3 scope

- deterministic Evidence Pack before rewrite;
- deterministic Fact Guard after rewrite;
- bounded task-aware rewrite budgets;
- provider-health diagnostics separated from editorial candidate QA;
- Router transport/provider availability separated from structural parsing, Fact Guard and readability/editorial validation;
- rejected candidate does not poison provider/model health or create a validation cooldown;
- model-level retry can use another model from the same provider;
- qwen `<think>` cleanup and one bounded local format-repair attempt;
- editorial/Rowboat memory isolated from factual evidence;
- persistent Source Health diagnostics without a database schema bump;
- production entrypoint `ui.v1_3_window` while retaining accepted v1.2.2 behavior underneath.

## Protected mechanisms

The 1.3 work does not intentionally change the accepted global duplicate engine, manual merge confirmation, Media Engine, multi-image workflow, platform publishers, publication queue semantics, scheduling, outcome-unknown safety, AES-GCM provider secret format, or existing Data schema 8.

## Acceptance evidence

- automated v1.3 logic/regression gates: PASS;
- Windows CI on Python 3.11 / 3.12 / 3.13 during the RC cycle: PASS;
- signed Windows portable build and GUI smoke during the RC cycle: PASS;
- Microsoft Defender runtime + ZIP scans during the RC cycle: PASS;
- ZIP integrity/version/safety gates: PASS;
- live test used a COPY of the current working Data;
- live AI Router diagnostics: PASS, including real NVIDIA response handling without literal-echo false failure;
- live production rewrite after Router/QA separation: PASS;
- user reported Content Creator working correctly and explicitly authorized full GitHub, Google Drive and release synchronization on 2026-08-19.

## Stable promotion rule

No functional changes are permitted between the accepted RC3 code and stable 1.3.0. Stable promotion changes release metadata/version only and is completed only if the repository CI/release workflow remains green.
