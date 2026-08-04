from __future__ import annotations

from pathlib import Path

helper = Path(__file__)
apply_path = helper.with_name("apply_v1_1_0.py")
apply_text = apply_path.read_text(encoding="utf-8")
old = 'schedule = ttk.LabelFrame(form, text="3. Розклад і резервні копії", padding=8)'
new = 'schedule = ttk.LabelFrame(form, text="5. Розклад", padding=10)'
if old not in apply_text:
    raise SystemExit("Expected legacy schedule anchor was not found in migration script.")
apply_path.write_text(apply_text.replace(old, new), encoding="utf-8", newline="\n")

fix_path = helper.with_name("fix_v1_1_0_generated_sources.py")
fix_text = fix_path.read_text(encoding="utf-8")
old_sub = "updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S | re.M)"
new_sub = "updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.S | re.M)"
if old_sub not in fix_text:
    raise SystemExit("Expected generated-source repair call was not found.")
fix_path.write_text(fix_text.replace(old_sub, new_sub), encoding="utf-8", newline="\n")

helper.unlink()
print("v1.1.0 migration anchors and literal prompt escapes aligned")
