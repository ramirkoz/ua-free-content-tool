from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


# Backup validation must know the additive schema introduced for local learning.
replace_once(
    "content_agent/backup.py",
    '        "final_text", "headline", "created_at",\n',
    '        "final_text", "headline", "language", "created_at",\n',
)
replace_once(
    "content_agent/backup.py",
    '        "candidate_text", "created_at",\n',
    '        "candidate_text", "language", "created_at",\n',
)
replace_once(
    "content_agent/backup.py",
    '    "queue_text_migrations": {\n',
    '    "learning_events": {\n'
    '        "id", "event_type", "language", "group_id", "anchor_group_id",\n'
    '        "payload_json", "created_at",\n'
    '    },\n'
    '    "queue_text_migrations": {\n',
)

# Preserve the proven v1.0 Ukrainian safety contracts while adding English mode.
rewriter_path = "content_agent/rewriter.py"
rewriter = read(rewriter_path)
old = """Створи ОДИН спільний текст для Facebook, Threads, LinkedIn і Telegram до
{EDITORIAL_TEXT_LIMIT} символів разом із пробілами."""
new = """Не створюй окремі тексти для соцмереж.
Створи ОДИН спільний текст для Facebook, Threads, LinkedIn і Telegram до
{EDITORIAL_TEXT_LIMIT} символів разом із пробілами."""
if old not in rewriter:
    raise SystemExit("Ukrainian one-text prompt anchor not found")
rewriter = rewriter.replace(old, new, 1)
old = """Поверни JSON лише з полями headline, fact_card, rewrite. rewrite має містити"""
new = """Текст публікації всередині поля rewrite має бути без JSON.
Поверни JSON лише з полями headline, fact_card, rewrite. rewrite має містити"""
if old not in rewriter:
    raise SystemExit("Ukrainian JSON prompt anchor not found")
rewriter = rewriter.replace(old, new, 1)
old = "Не перенось їхні факти:\\n\\n"
new = "не перенось факти з прикладів і не копіюй їхні факти:\\n\\n"
if old not in rewriter:
    raise SystemExit("Editorial-memory safety anchor not found")
rewriter = rewriter.replace(old, new, 1)
old = 'else f"Ollama двічі повернула непридатний рерайт: {detail}."'
new = (
    'else f"Текст не збережено і не передано в чергу. "'
    'f"Ollama двічі повернула непридатний рерайт: {detail}."'
)
if old not in rewriter:
    raise SystemExit("Ukrainian fail-closed error anchor not found")
rewriter = rewriter.replace(old, new, 1)
write(rewriter_path, rewriter)

# Release-contract tests describe intentional public behavior. Update only the
# expectations superseded by v1.1.0, while retaining every old behavioral check.
for test_path in sorted((ROOT / "tests").glob("test_r8_fix*.py")):
    text = test_path.read_text(encoding="utf-8")
    text = text.replace("UA FREE Content Tool — R8 FIX30", "UA FREE Content Tool — v1.1.0")
    text = text.replace("DATABASE_SCHEMA_VERSION == 7", "DATABASE_SCHEMA_VERSION == 8")
    text = text.replace('"DATABASE_SCHEMA_VERSION = 7"', '"DATABASE_SCHEMA_VERSION = 8"')
    text = text.replace(
        'PRAGMA user_version").fetchone()[0] == 7',
        'PRAGMA user_version").fetchone()[0] == 8',
    )
    text = text.replace(
        'self.groups_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")',
        'self.groups_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")',
    )
    text = text.replace(
        'text="Запам’ятати й виключати"',
        'text="Запам’ятати й більше не пропонувати"',
    )
    text = text.replace(
        'text="Знайти все по темі"',
        'text="Пошук схожих за темою матеріалів"',
    )
    text = text.replace(
        'assert "Автоматичного об’єднання немає" in text',
        'assert "TopicCandidatesDialog" in text',
    )
    text = text.replace(
        'assert \'self.settings_vars["meta_app_secret"]\' in source',
        'assert \'self.settings_vars["facebook_app_secret"]\' in source\n'
        '    assert \'self.settings_vars["threads_app_secret"]\' in source',
    )
    test_path.write_text(text, encoding="utf-8", newline="\n")

config_test = ROOT / "tests" / "test_config.py"
config_text = config_test.read_text(encoding="utf-8")
if 'assert config.meta_graph_version == "v24.0"' not in config_text:
    raise SystemExit("Config version assertion anchor not found")
config_test.write_text(
    config_text.replace(
        'assert config.meta_graph_version == "v24.0"',
        'assert config.meta_graph_version == "v26.0"',
        1,
    ),
    encoding="utf-8",
    newline="\n",
)

Path(__file__).unlink()
print("v1.1.0 compatibility contracts aligned")
