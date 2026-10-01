from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = -1) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"missing patch token in {path}: {old[:80]!r}")
    text = text.replace(old, new, count)
    write(path, text)


# Version alignment.
write("VERSION.txt", "2.0.0-rc55\n")
write("PUBLIC_VERSION.txt", "2.0.0-rc55\n")
replace("content_agent/__init__.py", '__version__ = "2.0.0-rc54"', '__version__ = "2.0.0-rc55"')

# Fact Guard: RC54 accidentally double-escaped regex metacharacters inside raw strings.
p = ROOT / "content_agent/fact_guard.py"
s = p.read_text(encoding="utf-8")
for old, new in (
    (r'r"тис\\.?', r'r"тис\.?'),
    (r'|тыс\\.?', r'|тыс\.?'),
    (r'r"млн\\.?', r'r"млн\.?'),
    (r'|млн\\.?', r'|млн\.?'),
    (r'r"млрд\\.?', r'r"млрд\.?'),
    (r'|млрд\\.?', r'|млрд\.?'),
    (r'|\\$|€', r'|\$|€'),
    (r'r"(?<![\\w])"', r'r"(?<![\w])"'),
    (r'\\s*|(?P<prefix_word>USD|EUR|UAH)\\s+', r'\s*|(?P<prefix_word>USD|EUR|UAH)\s+'),
    (r'\\d{1,3}(?:[ \\u00a0\\u202f,\'’ʼ]\\d{3})+|\\d+(?:[.,]\\d+)?', r'\d{1,3}(?:[ \u00a0\u202f,\'’ʼ]\d{3})+|\d+(?:[.,]\d+)?'),
    (r'(?P<suffix>(?:\\s*(?:', r'(?P<suffix>(?:\s*(?:'),
):
    s = s.replace(old, new)
p.write_text(s, encoding="utf-8")

# Canonical shell: remove duplicate legacy search and destructive legacy column-reset UI.
path = "content_agent/v2/ui/manual_topics_window_rc44.py"
s = read(path)
s = s.replace(
    "        super().__init__(root, database_or_services, config)\n        self._apply_rc54_dpi_layout()",
    "        super().__init__(root, database_or_services, config)\n        self._apply_rc55_inbox_cleanup()\n        self._apply_rc54_dpi_layout()",
)
marker = "    def _install_manual_topic_inbox_filters(self) -> None:\n"
method = '''    def _apply_rc55_inbox_cleanup(self) -> None:\n        \"\"\"Remove obsolete Inbox controls and lock the operator-visible column contract.\"\"\"\n        old_search = getattr(self, \"_rc14_keyword_entry\", None)\n        if old_search is not None:\n            try:\n                old_search.destroy()\n            except tk.TclError:\n                pass\n        tree = getattr(self, \"groups_tree\", None)\n        if tree is not None:\n            try:\n                tree.configure(displaycolumns=(\"title\", \"topic\", \"sources\", \"published\"))\n            except tk.TclError:\n                pass\n        # RC54 live review proved that the historical column-reset action can\n        # resurrect removed ID/status/score columns. Remove that UI path entirely.\n        for widget in tuple(self._rc48_walk(self.root)):\n            if widget is getattr(self, \"_rc53_filter_bar\", None):\n                continue\n            try:\n                text = str(widget.cget(\"text\") or \"\").strip()\n            except Exception:\n                continue\n            if text in {\"Пошук у Вхідних:\", \"Знайти\", \"Колонки\", \"Відновити стандартні колонки\"}:\n                try:\n                    widget.destroy()\n                except tk.TclError:\n                    pass\n\n'''
if method not in s:
    s = s.replace(marker, method + marker)
write(path, s)

# Keep manual block-composition editing, but remove the legacy rename that exposes column reset.
path = "content_agent/v2/ui/legacy_manual_topics_window_rc44.py"
s = read(path)
s = s.replace('            "Відновити стандартні колонки": "Колонки",\n', '')
write(path, s)

# Reconcile obsolete literal-version UI tests with the dynamic APP_VERSION title contract.
for path in ROOT.glob("tests/test_r8_fix*.py"):
    s = path.read_text(encoding="utf-8")
    old = 'assert \'root.title("UA FREE Content Tool — v1.3.1-rc7")\' in source'
    if old in s:
        s = s.replace(old, 'assert \'root.title(f"UA FREE Content Tool — v{APP_VERSION}")\' in source')
        path.write_text(s, encoding="utf-8")

# Current NewsGroup derives combined_text from articles; update the stale constructor test.
path = "tests/test_rc40_active_global_dedupe_unicode_digits.py"
s = read(path)
s = s.replace("from content_agent.models import NewsGroup", "from content_agent.models import Article, NewsGroup")
s = s.replace(
    "        combined_text=body,\n        status=\"new\",",
    "        status=\"new\",",
)
s = s.replace(
    "        last_published_at=now,\n    )",
    "        last_published_at=now,\n        articles=[Article(id=group_id, source_id=1, title=title, url=\"https://example.test\", raw_text=body, status=\"new\", published_at=now)],\n    )",
)
write(path, s)

# Current Codex package is the pinned runtime shipped by RC55, not historical 0.147.0.
for path in ("tests/test_v1_4_rc24_live_router.py", "tests/test_v1_4_rc30_canonical_ai.py", "tests/test_v1_4_rc28_ai_runtime.py"):
    s = read(path)
    s = s.replace("0.147.0", "0.156.1")
    write(path, s)

# RC28 side-by-side storage moved from Data to Tools; preserve the actual side-by-side contract.
path = "tests/test_v1_4_rc28_ai_runtime.py"
s = read(path)
s = s.replace('monkeypatch.setattr(codex.legacy, "data_dir", lambda: tmp_path)', 'monkeypatch.setattr(codex, "tools_dir", lambda: tmp_path)')
s = s.replace('old = tmp_path / "ai_runtime" / "codex"', 'old = tmp_path / "Codex" / "codex"')
s = s.replace('(tmp_path / "ai_runtime" / "codex_active.json")', '(tmp_path / "Codex" / "codex_active.json")')
s = s.replace('active = tmp_path / "ai_runtime" / pointer["directory"]', 'active = tmp_path / "Codex" / pointer["directory"]')
write(path, s)

# Tk hosted-runner defect: skip only when Tk itself cannot initialize.
path = "tests/test_v1_4_ui_smoke.py"
s = read(path)
s = s.replace('    root = tk.Tk()\n    root.withdraw()', '    try:\n        root = tk.Tk()\n    except tk.TclError as exc:\n        pytest.skip(f"Hosted runner Tk unavailable: {exc}")\n    root.withdraw()')
write(path, s)

# Updater regression follows the current preservation contract (Data + Tools).
path = "tests/test_v2_rc8_remote_control.py"
s = read(path)
s = s.replace('assert \'Where-Object { $_.Name -ne "Data" }\' in script', 'assert \'Where-Object { $_.Name -notin @("Data", "Tools") }\' in script')
write(path, s)

print("RC55 deterministic patches applied")
