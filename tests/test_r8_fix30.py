from __future__ import annotations

from pathlib import Path

from content_agent.ui.main_window import MainWindow


def test_fix30_range_helper_is_inclusive_and_direction_independent() -> None:
    rows = ("10", "20", "30", "40", "50")
    assert MainWindow._tree_range(rows, "20", "40") == ("20", "30", "40")
    assert MainWindow._tree_range(rows, "40", "20") == ("20", "30", "40")
    assert MainWindow._tree_range(rows, None, "30") == ("30",)
    assert MainWindow._tree_range(rows, "missing", "30") == ("30",)
    assert MainWindow._tree_range(rows, "20", "missing") == ()


def test_fix30_explicit_windows_shift_bindings_exist_for_inbox_and_queue() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "ui" / "main_window.py"
    text = source.read_text(encoding="utf-8")

    assert 'self.groups_tree.bind("<Shift-Button-1>", self._select_group_range)' in text
    assert 'self.queue_tree.bind("<Shift-Button-1>", self._select_queue_range)' in text
    assert "def _remember_group_selection_anchor" in text
    assert "def _select_group_range" in text
    assert "def _remember_queue_selection_anchor" in text
    assert "def _select_queue_range" in text
    assert 'return "break"' in text


def test_fix30_is_schema_neutral_program_only_hotfix() -> None:
    source = Path(__file__).parents[1] / "content_agent" / "database.py"
    text = source.read_text(encoding="utf-8")
    assert "DATABASE_SCHEMA_VERSION = 7" in text


class _FakeTree:
    def __init__(self) -> None:
        self.rows = ("10", "20", "30", "40")
        self._selection = ("20",)
        self._focus = "20"
        self.selected_set: tuple[str, ...] = ()
        self.seen = ""

    def identify_row(self, y: int) -> str:
        return {10: "10", 20: "20", 30: "30", 40: "40"}.get(y, "")

    def get_children(self) -> tuple[str, ...]:
        return self.rows

    def focus(self, iid: str | None = None) -> str:
        if iid is not None:
            self._focus = iid
        return self._focus

    def selection(self) -> tuple[str, ...]:
        return self._selection

    def selection_set(self, rows: tuple[str, ...]) -> None:
        self.selected_set = tuple(rows)
        self._selection = tuple(rows)

    def see(self, iid: str) -> None:
        self.seen = iid


class _Event:
    def __init__(self, y: int, state: int = 0) -> None:
        self.y = y
        self.state = state


def test_fix30_group_shift_handler_selects_real_range() -> None:
    window = MainWindow.__new__(MainWindow)
    window.groups_tree = _FakeTree()  # type: ignore[assignment]
    window._groups_selection_anchor = "20"

    result = window._select_group_range(_Event(40))  # type: ignore[arg-type]

    assert result == "break"
    assert window.groups_tree.selected_set == ("20", "30", "40")
    assert window.groups_tree.focus() == "40"
    assert window.groups_tree.seen == "40"


def test_fix30_queue_shift_handler_selects_real_range() -> None:
    window = MainWindow.__new__(MainWindow)
    window.queue_tree = _FakeTree()  # type: ignore[assignment]
    window._queue_selection_anchor = "30"

    result = window._select_queue_range(_Event(10))  # type: ignore[arg-type]

    assert result == "break"
    assert window.queue_tree.selected_set == ("10", "20", "30")
    assert window.queue_tree.focus() == "10"
    assert window.queue_tree.seen == "10"

import pytest

from content_agent.models import Article
from content_agent.ollama_client import OllamaError
from content_agent.rewriter import _rewrite_quality_issue, _ukrainian_language_issue, rewrite_article


def _rewrite_article_fixture() -> Article:
    return Article(
        id=1,
        source_id=1,
        title="В Україні запустили проєкт відстеження лелек",
        url="https://example.com/storks",
        raw_text=(
            "У межах проєкту ДТЕК Трек Лелек десять молодих білих лелек отримали GPS-трекери. "
            "Із другої половини серпня за їхньою міграцією можна буде стежити на інтерактивній карті. "
            "Дані допоможуть науковцям досліджувати маршрути, а енергетикам враховувати їх під час розвитку електромереж."
        ),
        status="new",
    )


def test_fix30_language_guard_rejects_english_essay() -> None:
    english = (
        "According to several alternative sources, this development could indicate a broader strategy. "
        "It remains unclear whether the project will have a meaningful impact."
    )
    issue = _ukrainian_language_issue("New tracking initiative", english)
    assert "англій" in issue or "латини" in issue


def test_fix30_first_english_answer_is_rewritten_from_sources_not_translated() -> None:
    class Client:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def generate_json(self, _model: str, prompt: str, _schema: dict[str, object], **_kwargs: object) -> dict[str, str]:
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return {
                    "headline": "A broader energy strategy",
                    "rewrite": (
                        "According to several alternative sources, this initiative may indicate a broader strategy. "
                        "It is possible that the tracking project will influence future policy."
                    ),
                }
            return {
                "headline": "Десятьох лелек відстежуватимуть за допомогою GPS",
                "rewrite": (
                    "У межах проєкту ДТЕК «Трек Лелек» десять молодих білих лелек отримали GPS-трекери. "
                    "Із другої половини серпня за їхньою міграцією можна буде стежити на інтерактивній карті. "
                    "Дані допоможуть науковцям досліджувати маршрути, а енергетикам враховувати їх під час розвитку електромереж."
                ),
            }

    client = Client()
    result = rewrite_article(client, "qwen3:4b", _rewrite_article_fixture())  # type: ignore[arg-type]
    assert len(client.prompts) == 2
    assert "Не перекладай і не редагуй її" in client.prompts[1]
    assert "МАТЕРІАЛИ ВСІХ ДЖЕРЕЛ" in client.prompts[1]
    assert "According to" not in result.rewrite
    assert result.rewrite.startswith("У межах проєкту")


def test_fix30_second_english_or_speculative_answer_fails_closed() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def generate_json(self, _model: str, _prompt: str, _schema: dict[str, object], **_kwargs: object) -> dict[str, str]:
            self.calls += 1
            return {
                "headline": "A possible broader strategy",
                "rewrite": "According to alternative sources, this may suggest a broader political strategy.",
            }

    client = Client()
    with pytest.raises(OllamaError, match="Текст не збережено і не передано в чергу"):
        rewrite_article(client, "qwen3:4b", _rewrite_article_fixture())  # type: ignore[arg-type]
    assert client.calls == 2


def test_fix30_rejects_unsupported_editorial_reflections() -> None:
    source = "Компанія встановила десять GPS-трекерів на білих лелек для дослідження міграції."
    rewrite = (
        "Компанія встановила GPS-трекери на лелек. Це може свідчити про ширшу енергетичну стратегію, "
        "а її наслідки, ймовірно, стануть помітними пізніше."
    )
    issue = _rewrite_quality_issue("Лелек відстежуватимуть через GPS", rewrite, source)
    assert "домисли" in issue
