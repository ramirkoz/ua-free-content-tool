from __future__ import annotations

import threading

# One process-wide lock serializes explicit backup/import against all SQLite work.
# The application also holds a cross-process InstanceLock, so no second app process
# can race an import.
DATA_MAINTENANCE_LOCK = threading.RLock()
