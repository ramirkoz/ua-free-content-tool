from __future__ import annotations

from .v1_2_rc4_window import MainWindow as RC4Window


class MainWindow(RC4Window):
    def _rebuild_target_controls(self) -> None:
        super()._rebuild_target_controls()
        check = getattr(self, "target_checks", {}).get("instagram")
        if check is None:
            return
        if self.config.platform_ready("instagram"):
            name = self.config.instagram_profile_name or self.config.instagram_user_id or "Instagram"
            check.configure(text=f"{name} (Instagram)")
        else:
            check.configure(text="Instagram (не підключено)")
