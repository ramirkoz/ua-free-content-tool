"""UA FREE Content Tool."""

__version__ = "2.0.0-rc50"

from .windows_ui import enable_dpi_awareness
from .drive_auth_recovery import install_drive_auth_recovery

enable_dpi_awareness()
install_drive_auth_recovery()
