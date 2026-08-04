from __future__ import annotations

from pathlib import Path

path = Path(__file__).with_name("apply_v1_1_0.py")
text = path.read_text(encoding="utf-8")
old = 'schedule = ttk.LabelFrame(form, text="3. Розклад і резервні копії", padding=8)'
new = 'schedule = ttk.LabelFrame(form, text="5. Розклад", padding=10)'
if old not in text:
    raise SystemExit("Expected legacy schedule anchor was not found in migration script.")
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print("v1.1.0 migration anchors aligned")
