# UA FREE Content Tool v1.2.2 RC7

RC7 fixes the reproduced RC6 failure where global duplicate search completed with the message that the time limit was reached and returned no proposals, even though obvious duplicates were visible in the inbox.

## Fixed
- Strictly bounded duplicate candidate generation for large noisy inboxes.
- Title-focused blocking with rare adjacent title bigrams and a small body-text supplement.
- Candidate pair materialization is capped at 12,000; final review graph remains capped at 160 edges and 4 neighbours per group.
- Deterministic review candidates are no longer erased when AI returns NONE or otherwise rejects the compact AI batch.
- Added regression coverage for the visible Zaporizhzhia education-account duplicate pair from the live RC6 screenshot.
- Added dense 1000-item inbox regression coverage.

## Safety
- No automatic merge. Every proposed merge still requires manual confirmation.
- Existing AI Router and Ollama-first local fallback remain unchanged.

## Validation
- 406 tests PASS on the Windows RC7 build gate.
- Windows CI Python 3.11 / 3.12 / 3.13 PASS.
- Portable build, GUI startup smoke, Microsoft Defender and ZIP validation PASS.

Validated build head: `822f9315b6cd88c4fc3d48486280e9edee397311`.
Windows build run: `32021755621`.
Windows CI run: `32021759106`.
Portable SHA-256: `4f8691cf8485556f81d99a39ed3ac07634747fbb42d2e3457d440629887f70c8`.
Source SHA-256: `6fccb9829f4bc602feabd75e8b65ad15a6fc21b1c9bdcbfab4f4e1ebf7a2a3a4`.
