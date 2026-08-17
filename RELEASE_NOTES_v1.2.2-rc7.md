# UA FREE Content Tool v1.2.2 RC7

RC7 fixed the reproduced live RC6 failure where global duplicate search could time out and return no proposals despite an obvious duplicate pair in a large Inbox.

## Final live acceptance

On 17.08.2026 the same working `Data` used to reproduce the earlier failures passed live acceptance:

- rewrite completed successfully through the production AI Router;
- global duplicate grouping returned relevant proposals;
- the application remained responsive;
- the workflow worked end to end on the real working dataset.

RC7 is therefore promoted into the stable v1.2.2 codebase.

## Duplicate grouping changes

- Strictly bounded title-first candidate generator.
- Rare adjacent title bigrams are prioritized.
- Only a small body-text supplement is used.
- Candidate-pair materialization is capped.
- Final candidate graph is bounded.
- Strong deterministic review candidates survive AI `NONE`, invalid output, quota errors and timeout.
- No automatic merge: every proposal still requires explicit human confirmation.

## Runtime and AI

- Production rewrite uses the bounded AI Router.
- Existing Ollama is the final local emergency fallback.
- Ollama is reused if already installed; models are not pulled automatically.
- Local prompts are compacted for smaller models.
- Duplicate search is non-blocking, cancellable and protected by deadlines/watchdog handling.

## Validation

- 406 tests PASS on the final RC7 Windows gate.
- Windows CI Python 3.11 / 3.12 / 3.13 PASS.
- Portable build PASS.
- GUI startup smoke PASS.
- Microsoft Defender PASS.
- ZIP CRC/integrity validation PASS.
- Live working-Data acceptance PASS.
