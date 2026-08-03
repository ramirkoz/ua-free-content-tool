from __future__ import annotations

import ast
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "content_agent" / "main.py"


def main() -> int:
    tree = ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("content_agent"):
            bad.append(f"line {node.lineno}: absolute internal import {node.module}")
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in {
            "config",
            "database",
            "instance_lock",
            "logging_setup",
            "ui",
        }:
            bad.append(f"line {node.lineno}: ambiguous top-level import {node.module}")
    if bad:
        print("FAIL")
        print("\n".join(bad))
        return 1
    print("PASS: content_agent.main uses package-relative internal imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
