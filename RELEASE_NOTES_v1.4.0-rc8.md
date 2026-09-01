# UA FREE Content Tool v1.4.0-rc8

## Fixed

- Restored the missing per-destination **Донатний блок** switch in the v1.4 Publication UI.
- Donation switches are now rebuilt for every concrete publishing destination: each Facebook Page, each Instagram Professional account, Threads, LinkedIn, and Telegram.
- v1.4 destination readiness is used for donation controls, so concrete `instagram:<account_id>` destinations are no longer incorrectly treated as unavailable.
- The donation status counter now reflects the visible per-destination switches instead of only raw legacy target keys.
- A legacy generic Instagram donation preference remains visible on concrete Instagram accounts until the user changes the new per-account switches.

## Preserved

- Existing donation text and saved donation policy remain in `Data/donation_settings_v1_3_1_rc8.json`; no Data migration or database schema change is required.
- The v1.4 per-destination queue/schedule model is unchanged.
- RC7 duplicate-review window sizing and authoritative last-used destination selection are unchanged.
- Publication transport, Fact Guard, media workflow, duplicate engine, and scheduling behaviour are unchanged.

## Validation

- Added regression coverage for exact destination donation policy, legacy Instagram compatibility, visible enabled-profile counting, and use of the v1.4 destination resolver.
- Windows CI passes on Python 3.11, 3.12, and 3.13 before release promotion.
- Release workflow additionally performs compile/tests, signed portable-runtime startup validation, Microsoft Defender scans, ZIP integrity checks, and SHA-256 generation.
