from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .editorial_memory import weighted_similarity
from .paths import data_dir

ROWBOAT_RELEASE_API = "https://api.github.com/repos/rowboatlabs/rowboat/releases/latest"


class RowboatError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RowboatStatus:
    installed: bool
    executable: str = ""
    workdir: str = ""
    memory_root: str = ""
    detail: str = ""


def rowboat_workdir() -> Path:
    root = data_dir() / "RowboatWorkDir"
    (root / "knowledge").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    return root


def memory_root() -> Path:
    root = rowboat_workdir() / "knowledge" / "ua-free"
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
            "Цей каталог розташований усередині Rowboat WorkDir/knowledge. "
            "UA FREE Content Tool читає його напряму, а Rowboat запускається з цим самим WorkDir.\n",
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
            base / "rowboat" / "rowboat.exe",
            base / "Programs" / "Rowboat" / "rowboat.exe",
            base / "Programs" / "rowboat" / "rowboat.exe",
        ])
        try:
            values.extend(base.glob("Rowboat*/*rowboat.exe"))
            values.extend(base.glob("rowboat*/*rowboat.exe"))
            values.extend(base.glob("Rowboat*/app-*/rowboat.exe"))
            values.extend(base.glob("rowboat*/app-*/rowboat.exe"))
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
    workdir = rowboat_workdir()
    graph = memory_root()
    exe = find_rowboat()
    if exe is None:
        return RowboatStatus(
            False,
            workdir=str(workdir),
            memory_root=str(graph),
            detail="Rowboat не знайдено. Ізольований WorkDir і Markdown-пам'ять UA FREE уже готові.",
        )
    return RowboatStatus(
        True,
        executable=str(exe),
        workdir=str(workdir),
        memory_root=str(graph),
        detail="Rowboat знайдено. Він запускатиметься з окремим UA FREE WorkDir.",
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
        lowered = name.casefold()
        if lowered.startswith("rowboat-win32-x64-") and lowered.endswith("-setup.exe"):
            url = str(asset.get("browser_download_url") or "")
            if url:
                return name or "rowboat-setup.exe", url, str(asset.get("digest") or "")
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
    if completed.returncode != 0:
        raise RowboatError(f"Rowboat installer завершився з кодом {completed.returncode}.")
    exe = None
    for _ in range(30):
        exe = find_rowboat()
        if exe is not None:
            break
        time.sleep(1)
    if exe is None:
        raise RowboatError("Інсталятор завершився, але rowboat.exe не знайдено протягом 30 секунд.")
    memory_root()
    return exe


def open_rowboat() -> None:
    exe = find_rowboat()
    if exe is None:
        raise RowboatError("Rowboat не встановлено.")
    workdir = rowboat_workdir()
    memory_root()
    env = dict(os.environ)
    env["ROWBOAT_WORKDIR"] = str(workdir)
    subprocess.Popen([str(exe)], close_fds=True, env=env)


def open_memory_folder() -> None:
    root = memory_root()
    if os.name == "nt":
        os.startfile(root)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(root)])


def sync_editorial_memory(database) -> dict[str, int]:
    root = memory_root()
    examples_dir = root / "editorial-examples"
    decisions_dir = root / "topic-decisions"
    examples = list(database.list_editorial_examples(language="uk"))
    for row in examples:
        item_id = row.get("id") or hashlib.sha1(str(row.get("final_text") or "").encode("utf-8")).hexdigest()[:12]
        final_text = str(row.get("final_text") or "").strip()
        source_text = str(row.get("source_text") or "").strip()
        headline = str(row.get("headline") or "").strip()
        (examples_dir / f"example-{item_id}.md").write_text(
            "---\ntype: editorial-example\nlanguage: uk\n---\n\n"
            f"# {headline or 'Схвалений рерайт'}\n\n## Джерело\n\n{source_text}\n\n"
            f"## Фінальний текст\n\n{final_text}\n\nЗв'язки: [[UA FREE Editorial Memory]]\n",
            encoding="utf-8",
        )
    feedback = list(database.list_topic_feedback(language="uk")) if hasattr(database, "list_topic_feedback") else []
    for row in feedback:
        decision = str(row.get("decision") or "unknown")
        anchor = str(row.get("anchor_text") or "")
        candidate = str(row.get("candidate_text") or "")
        fingerprint = hashlib.sha1(f"{decision}|{anchor}|{candidate}".encode("utf-8")).hexdigest()[:12]
        (decisions_dir / f"decision-{fingerprint}.md").write_text(
            "---\ntype: topic-decision\n"
            f"decision: {decision}\n---\n\n# Редакційне рішення: {decision}\n\n"
            f"## Матеріал A\n\n{anchor}\n\n## Матеріал B\n\n{candidate}\n\n"
            "Зв'язки: [[UA FREE Editorial Memory]]\n",
            encoding="utf-8",
        )
    return {"examples": len(examples), "decisions": len(feedback)}


def memory_context(query_text: str, *, limit: int = 6) -> str:
    ranked: list[tuple[float, str]] = []
    root = memory_root()
    for folder in (root / "editorial-examples", root / "topic-decisions"):
        for path in folder.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            score = weighted_similarity(query_text, text)
            if score >= 0.04:
                ranked.append((score, text[:2200]))
    ranked.sort(key=lambda item: -item[0])
    if not ranked:
        return ""
    return "\n\n--- MEMORY ---\n\n".join(text for _score, text in ranked[:max(1, int(limit))])
