# UA FREE Content Tool v1.2.2 RC6

RC6 is a focused live-failure fix for the global duplicate/grouping workflow.

## Fixed
- Replaced the quadratic all-pairs duplicate prefilter with a bounded token-blocking prefilter suitable for large inboxes.
- One global duplicate search now has a 45-second internal deadline and a 55-second UI watchdog.
- Added a visible **Cancel search** state on the existing duplicate-search button.
- Duplicate AI verification uses one compact batch instead of serial AI calls for every batch.
- Duplicate search skips Codex, uses short cloud request timeouts, short Ollama timeout, and suppresses a provider for the rest of the task after quota/429.
- If AI cannot finish quickly, local deterministic candidates are shown for manual review instead of hanging or failing the whole operation.
- Rowboat/editorial-memory synchronization is no longer performed before global duplicate search because the RC6 classifier does not need it.
- Cancellation remains authoritative if an AI response arrives after the user has already cancelled the operation.
- Late worker results are ignored by the existing operation-id guard after a UI timeout.

## Safety
- No automatic merge is introduced. Every proposed merge still requires manual confirmation.
- Existing rewrite routing and Ollama fallback remain unchanged.

## Validation
- Final source test suite: 403 tests passed.
- Windows CI: Python 3.11, 3.12 and 3.13 PASS.
- Windows portable build, GUI startup smoke, Microsoft Defender and ZIP validation are required on the exact RC6 head before live acceptance.
