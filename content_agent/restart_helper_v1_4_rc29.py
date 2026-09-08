from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def schedule_delayed_restart() -> None:
    """Relaunch the signed portable executable after the current process releases its lock."""
    executable = Path(sys.executable).resolve()
    workdir = executable.parent
    command = f'ping 127.0.0.1 -n 4 >nul & start "" /d "{workdir}" "{executable}"'
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        ["cmd.exe", "/d", "/s", "/c", command],
        cwd=str(workdir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
