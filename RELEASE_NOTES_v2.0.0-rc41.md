# UA FREE Content Tool v2.0.0-rc41

Windows synchronization build focused on Google Drive authorization recovery.

## Google Drive authorization
- Generic Google Drive HTTP 403 responses are no longer treated as proof that OAuth authorization is revoked.
- Existing Drive publication blocks can self-heal when the saved refresh credentials still validate.
- True authorization failures such as HTTP 401 and invalid_grant continue to require reauthorization.

## Preserved behavior
- RC40 duplicate-search hardening, Fact Guard, scheduling, editorial workflow, destinations, source handling and publishing logic remain intact.

## Verification
- Application source compilation: PASS.
- Focused Drive authorization regressions: PASS.
- Signed Windows portable build: PASS.

This release is the synchronized testing baseline; synchronization does not by itself mean final Windows user acceptance.
