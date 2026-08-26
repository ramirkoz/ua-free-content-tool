# RC14 change scope

Runtime changes are intentionally limited to:

- version metadata and release notes;
- `content_agent/main.py` startup orchestration;
- additive `content_agent/database_rc14.py` database adapter;
- additive `content_agent/ui/rc14_window.py` UI adapter;
- RC14 regression tests and validation notes.

The RC13 schema version stays 8 and legacy production modules remain intact. RC14 uses adapters so rollback is a program-folder rollback with the same Data.
