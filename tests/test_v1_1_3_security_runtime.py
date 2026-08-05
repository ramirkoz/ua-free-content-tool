from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_portable_builder_uses_signed_python_runtime_not_pyinstaller() -> None:
    batch = (ROOT / "Build_Portable_Windows.bat").read_text(encoding="utf-8")
    lowered = batch.casefold()
    assert "build_signed_python_runtime.ps1" in lowered
    assert "pyinstaller" not in lowered
    assert "python 3.12" in lowered


def test_signed_runtime_builder_requires_authenticode_and_isolated_paths() -> None:
    script = (ROOT / "tools" / "build_signed_python_runtime.ps1").read_text(encoding="utf-8")
    assert "Get-AuthenticodeSignature" in script
    assert "Python Software Foundation" in script
    assert "UA_FREE_Content_Tool._pth" in script
    assert "python312._pth" in script
    assert "PYTHONNOUSERSITE" in script
    assert "_runtime_console.exe" in script


def test_release_workflow_scans_extracted_runtime_and_final_zip() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert workflow.count("-Scan -ScanType 3 -File") >= 2
    assert "-SignatureUpdate" in workflow
    assert "Python Software Foundation" in workflow
    assert "RELEASE_ZIP_VALIDATION_OK" in workflow
    assert "_runtime_console" in workflow


def test_withdrawn_v1_1_2_is_documented_as_not_restorable() -> None:
    security = (ROOT / "SECURITY_NOTES.md").read_text(encoding="utf-8")
    notes = (ROOT / "RELEASE_NOTES_v1.1.3.md").read_text(encoding="utf-8")
    assert "v1.1.2 Windows binary was withdrawn" in security
    assert "must not be restored" in security
    assert "must not be restored" in notes
