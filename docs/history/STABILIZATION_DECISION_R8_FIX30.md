# R8 FIX30 Stabilization Decision

FIX30 is a program-only hotfix intended to run on an existing working FIX29 `Data` folder.

## Fixed

- Reliable Shift-click range selection in Incoming and Queue views on Windows.
- English model output no longer passes Ukrainian-language validation.
- An invalid first Ollama response is not translated or polished; the retry is generated again from the original source materials.
- Speculative analysis and meta-commentary not supported by the sources are rejected.
- After two invalid responses, no text is saved and nothing enters the queue.
- SQLite schema remains version 7; existing `Data` and queue content are not migrated.

## Validation status at the stabilization decision

- Local gate: PASS, 223/223 tests.
- Windows Gate: not yet tested at that point.
- Live Ollama gate: not yet tested at that point.
- Live platform gate: not yet tested at that point.

A working FIX29 installation was to be replaced only in a full copy after a Windows Gate PASS and a backup of the complete folder.
