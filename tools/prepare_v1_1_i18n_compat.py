from __future__ import annotations

from pathlib import Path

helper = Path(__file__)
target = helper.with_name("apply_v1_1_i18n_completion.py")
text = target.read_text(encoding="utf-8")

anchor = '''replace_once(
    "content_agent/ui/main_window.py",
    "        self.config = config\\n        self._settings_loading = True\\n",
'''
compat_block = '''replace_once(
    "content_agent/ui/main_window.py",
    "class MainWindow:\\n    def __init__(self, root: tk.Tk, database: Database, config: AppConfig):\\n",
    "class MainWindow:\\n"
    "    def __getattr__(self, name: str):\\n"
    "        # Older regression tests construct MainWindow with __new__ and do not\\n"
    "        # run __init__. Fall back to the module dialogs in that narrow case.\\n"
    "        if name == 'msg':\\n"
    "            return messagebox\\n"
    "        if name == 'files':\\n"
    "            return filedialog\\n"
    "        raise AttributeError(name)\\n\\n"
    "    def __init__(self, root: tk.Tk, database: Database, config: AppConfig):\\n",
)
'''
if anchor not in text:
    raise SystemExit("MainWindow localization anchor not found")
text = text.replace(anchor, compat_block + anchor, 1)

status_anchor = '''replace_once(
    "content_agent/ui/main_window.py",
    "    def set_status(self, text: str) -> None:\\n        self.status_var.set(text)\\n",
'''
t_method_block = '''replace_once(
    "content_agent/ui/main_window.py",
    "    def t(self, text: str) -> str:\\n        return tr(text, self.config.ui_language)\\n",
    "    def t(self, text: str) -> str:\\n"
    "        config = getattr(self, 'config', None)\\n"
    "        return tr(text, getattr(config, 'ui_language', 'uk'))\\n",
)
'''
if status_anchor not in text:
    raise SystemExit("set_status localization anchor not found")
text = text.replace(status_anchor, t_method_block + status_anchor, 1)

target.write_text(text, encoding="utf-8", newline="\n")
helper.unlink()
print("legacy UI compatibility added to localization migration")
