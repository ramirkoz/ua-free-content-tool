from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from content_agent.i18n import tr

CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
FILES = [
    ROOT / "content_agent" / "ui" / "main_window.py",
    ROOT / "content_agent" / "ui" / "topic_candidates_dialog.py",
    ROOT / "content_agent" / "ui" / "queue_migration_dialog.py",
]


def visible_candidates(tree: ast.AST) -> list[tuple[int, str, str]]:
    results: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in {"text", "title", "message", "label"} and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str) and CYRILLIC.search(keyword.value.value):
                        results.append((keyword.value.lineno, keyword.arg, keyword.value.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"showinfo", "showwarning", "showerror", "askyesno", "askokcancel"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and CYRILLIC.search(arg.value):
                        results.append((arg.lineno, "dialog", arg.value))
    return results


report: dict[str, list[dict[str, object]]] = {}
for path in FILES:
    if not path.exists():
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    missing: list[dict[str, object]] = []
    for line, kind, text in visible_candidates(tree):
        if tr(text, "en") == text:
            missing.append({"line": line, "kind": kind, "text": text})
    report[str(path.relative_to(ROOT))] = missing

print("I18N_AUDIT_BEGIN")
print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
print("I18N_AUDIT_END")
print("UNTRANSLATED_VISIBLE_LITERALS=" + str(sum(len(items) for items in report.values())))
