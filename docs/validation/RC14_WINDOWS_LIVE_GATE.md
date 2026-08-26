# RC14 Windows live gate

After installing the signed portable build over a fresh program folder and preserving the existing Data folder:

- first launch must show the startup window immediately;
- no Task Manager termination should be needed to make a second launch work;
- `Data/ui_startup_freeze_trace.log` is diagnostic only and should stay quiet during a healthy start;
- history and full metric refresh must cover only the last seven days;
- publication batches older than seven days must leave operational queue/history tables after background maintenance;
- archived sent targets must still prevent accidental duplicate publication.
