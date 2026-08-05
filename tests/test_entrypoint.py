from __future__ import annotations


def test_entrypoint_import() -> None:
    import content_agent.main  # noqa: F401


def test_windows_build_uses_signed_runtime_with_application_data() -> None:
    from pathlib import Path

    batch = Path("Build_Portable_Windows.bat").read_text(encoding="utf-8-sig")
    builder = Path("tools/build_signed_python_runtime.ps1").read_text(encoding="utf-8")

    assert "build_signed_python_runtime.ps1" in batch
    assert "pyinstaller" not in batch.casefold()
    assert 'Copy-Item (Join-Path $repo "content_agent")' in builder
    assert 'Copy-Item (Join-Path $pythonRoot "pythonw.exe")' in builder
    assert "Europe_Kyiv.tzif" not in batch  # copied with the complete application package
    assert "content_agent" in builder
