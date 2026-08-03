from __future__ import annotations


def test_entrypoint_import() -> None:
    import content_agent.main  # noqa: F401


def test_windows_build_uses_absolute_data_sources() -> None:
    from pathlib import Path

    script = Path("Build_Portable_Windows.bat").read_text(encoding="utf-8-sig")
    assert (
        '--add-data "%CD%\\content_agent\\data\\Europe_Kyiv.tzif;content_agent\\data"'
        in script
    )
    assert (
        '--add-data "%CD%\\content_agent\\data\\README.txt;content_agent\\data"'
        in script
    )
    assert '--specpath build' in script
