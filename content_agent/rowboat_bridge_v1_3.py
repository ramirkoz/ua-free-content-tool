from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import data_dir

ROWBOAT_RELEASE_API = "https://api.github.com/repos/rowboatlabs/rowboat/releases/latest"


class RowboatError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RowboatStatus:
    installed: bool
    executable: str = ""
    memory_root: str = ""
    detail: str = ""


def memory_root() -> Path:
    root = data_dir() / "EditorialMemoryGraph"
    root.mkdir(parents=True, exist_ok=True)
    (root / "editorial-examples").mkdir(exist_ok=True)
    (root / "topic-decisions").mkdir(exist_ok=True)
    index = root / "README.md"
    if not index.exists():
        index.write_text(
            "# UA FREE Editorial Memory\n\n"
            "Локальний Markdown-граф редакційної пам'яті UA FREE Content Tool.\n\n"
            "- [[editorial-examples]] — схвалені редактором тексти.\n"
            "- [[topic-decisions]] — рішення про об'єднання або непов'язаність матеріалів.\n\n"
            "Ці файли можна переглядати та редагувати як звичайний Markdown і відкривати у Rowboat/Obsidian-сумісних інструментах.\n",
            encoding="utf-8",
        )
    return root


def _candidate_executables() -> list[Path]:
    values: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    if local:
        base = Path(local)
        values.extend([
            base / "Rowboat-win32-x64" / "rowboat.exe",
            base / "Programs" / "Rowboat" / "rowboat.exe",
            base / "Programs" / "rowboat" / "rowboat.exe",
            base / "rowboat" / "rowboat.exe",
        ])
        try:
            for child in base.glob("Rowboat*/*rowboat.exe"):
                values.append(child)
        except OSError:
            pass
    if program_files:
        values.append(Path(program_files) / "Rowboat" / "rowboat.exe")
    return values


def find_rowboat() -> Path | None:
    for candidate in _candidate_executables():
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def inspect_rowboat() -> RowboatStatus:
    graph = memory_root()
    exe = find_rowboat()
    if exe is None:
        return RowboatStatus(
            installed=False,
            memory_root=str(graph),
            detail="Rowboat не знайдено. Локальна Markdown-пам'ять UA FREE вже готова.",
        )
    return RowboatStatus(
        installed=True,
        executable=str(exe),
        memory_root=str(graph),
        detail="Rowboat знайдено. Локальна Markdown-пам'ять UA FREE готова.",
    )


def _latest_windows_asset() -> tuple[str, str, str]:
    request = urllib.request.Request(
        ROWBOAT_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "UA-FREE-Content-Tool"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RowboatError(f"Не вдалося отримати останній реліз Rowboat: {exc}") from exc
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise RowboatError("GitHub не повернув список файлів релізу Rowboat.")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.casefold().endswith("win32-x64-setup.exe"):
            url = str(asset.get("browser_download_url") or "")
            digest = str(asset.get("digest") or "")
            if url:
                return name, url, digest
    raise RowboatError("У поточному релізі Rowboat не знайдено Windows x64 setup.exe.")


def install_rowboat() -> Path:
    name, url, digest = _latest_windows_asset()
    if not url.startswith("https://github.com/rowboatlabs/rowboat/releases/download/"):
        raise RowboatError("Rowboat installer має неочікувану адресу; встановлення зупинено.")
    destination = Path(tempfile.gettempdir()) / name
    request = urllib.request.Request(url, headers={"User-Agent": "UA-FREE-Content-Tool"})
    sha = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                sha.update(chunk)
    except Exception as exc:
        raise RowboatError(f"Не вдалося завантажити Rowboat: {exc}") from exc
    if digest.casefold().startswith("sha256:"):
        expected = digest.split(":", 1)[1].strip().casefold()
        if expected and sha.hexdigest().casefold() != expected:
            destination.unlink(missing_ok=True)
            raise RowboatError("SHA-256 Rowboat installer не збігається з GitHub release.")
    try:
        completed = subprocess.run([str(destination)], timeout=600, check=False)
    except Exception as exc:
        raise RowboatError(f"Не вдалося запустити інсталятор Rowboat: {exc}") from exc
    if completed.returncode not in (0, 1):
        raise RowboatError(f"Rowboat installer завершився з кодом {completed.returncode}.")
    exe = find_rowboat()
    if exe is None:
        raise RowboatError("Інсталятор завершився, але rowboat.exe ще не знайдено. Перевірте завершення встановлення.")
    memory_root()
    return exe


def open_rowboat() -> None:
    exe = find_rowboat()
    if exe is None:
        raise RowboatError("Rowboat не встановлено.")
    subprocess.Popen([str(exe)], close_fds=True)


def open_memory_folder() -> None:
    root = memory_root()
    if os.name == "nt":
        os.startfile(root)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(root)])


def _safe_slug(value: str, fallback: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value or "").strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned[:80] or fallback).lower()


def sync_editorial_memory(database) -> dict[str, int]:
    root = memory_root()
    examples_dir = root / "editorial-examples"
    decisions_dir = root / "topic-decisions"
    examples = database.list_editorial_examples(language="uk")
    for item in examples:
        item_id = getattr(item, "id", None) or hashlib.sha1(str(getattr(item, "final_text", "")).encode("utf-8")).hexdigest()[:12]
        final_text = str(getattr(item, "final_text", "") or "").strip()
        source_text = str(getattr(item, "source_text", "") or "").strip()
        headline = str(getattr(item, "headline", "") or "").strip()
        name = examples_dir / f"example-{item_id}.md"
        name.write_text(
            "---\ntype: editorial-example\nlanguage: uk\n---\n\n"
            f"# {headline or 'Схвалений рерайт'}\n\n"
            f"## Джерело\n\n{source_text}\n\n"
            f"## Фінальний текст\n\n{final_text}\n\n"
            "Зв'язки: [[UA FREE Editorial Memory]]\n",
            encoding="utf-8",
        )
    feedback = []
    if hasattr(database, "list_topic_merge_feedback"):
        try:
            feedback = list(database.list_topic_merge_feedback(language="uk"))
        except TypeError:
            feedback = list(database.list_topic_merge_feedback())
    for index, item in enumerate(feedback, start=1):
        if isinstance(item, dict):
            decision = str(item.get("decision") or "unknown")
            anchor = str(item.get("anchor_text") or "")
            candidate = str(item.get("candidate_text") or "")
        else:
            decision = str(getattr(item, "decision", "unknown"))
            anchor = str(getattr(item, "anchor_text", "") or "")
            candidate = str(getattr(item, "candidate_text", "") or "")
        fingerprint = hashlib.sha1(f"{decision}|{anchor}|{candidate}".encode("utf-8")).hexdigest()[:12]
        path = decisions_dir / f"decision-{fingerprint}.md"
        path.write_text(
            "---\ntype: topic-decision\n"
            f"decision: {decision}\n---\n\n"
            f"# Редакційне рішення: {decision}\n\n"
            f"## Матеріал A\n\n{anchor}\n\n"
            f"## Матеріал B\n\n{candidate}\n\n"
            "Зв'язки: [[UA FREE Editorial Memory]]\n",
            encoding="utf-8",
        )
    return {"examples": len(examples), "decisions": len(feedback)}
