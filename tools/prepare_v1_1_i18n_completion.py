from __future__ import annotations

from pathlib import Path

helper = Path(__file__)
target = helper.with_name("apply_v1_1_i18n_completion.py")
text = target.read_text(encoding="utf-8")
old = '    "            self.status_var.set(\\"Готово. Планувальник публікацій увімкнено.\\")\\n",'
new = '    "        self.status_var.set(\\"Готово. Планувальник публікацій увімкнено.\\")\\n",'
old_replacement = '    "            self.set_status(\\"Готово. Планувальник публікацій увімкнено.\\")\\n",'
new_replacement = '    "        self.set_status(\\"Готово. Планувальник публікацій увімкнено.\\")\\n",'
if old not in text or old_replacement not in text:
    raise SystemExit("Localization completion status anchor not found")
text = text.replace(old, new, 1).replace(old_replacement, new_replacement, 1)
target.write_text(text, encoding="utf-8", newline="\n")
helper.unlink()
print("localization completion source anchor aligned")
