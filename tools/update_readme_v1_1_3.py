from __future__ import annotations

from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
replacements = {
    "> **Public release:** `v1.1.2`": "> **Public release:** `v1.1.3`",
    "## What is new in v1.1.2": "## What is new in v1.1.3",
    "See [RELEASE_NOTES_v1.1.2.md](RELEASE_NOTES_v1.1.2.md)": "See [RELEASE_NOTES_v1.1.3.md](RELEASE_NOTES_v1.1.3.md)",
    "Download `UA_FREE_Content_Tool_v1.1.2_Windows_Portable.zip`.": "Download `UA_FREE_Content_Tool_v1.1.3_Windows_Portable.zip`.",
    "Extract v1.1.2 into a separate folder.": "Extract v1.1.3 into a separate folder.",
    "Start v1.1.2 and confirm": "Start v1.1.3 and confirm",
    "from v1.1.2.": "from v1.1.3.",
    "Do not replace only the EXE. The portable build also contains the version-specific `_internal` directory.": "Do not replace only the EXE. v1.1.3 uses a signed isolated Python runtime and depends on the accompanying `DLLs`, `Lib`, `tcl`, and `content_agent` directories.",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"README anchor not found: {old}")
    text = text.replace(old, new)

marker = "## What is new in v1.1.3\n\n"
security_intro = (
    "- The Windows package was rebuilt after the v1.1.2 executable was withdrawn following a critical Microsoft Defender detection.\n"
    "- The generated unsigned PyInstaller launcher was replaced with the unchanged official `pythonw.exe` runtime signed by the Python Software Foundation.\n"
    "- Release publication now requires Authenticode verification, isolated-runtime startup checks, and Microsoft Defender scans of both the extracted application and final ZIP.\n"
    "- Do not restore, allow, or add the v1.1.2 executable to Defender exclusions.\n"
)
if marker not in text:
    raise SystemExit("README v1.1.3 section marker not found")
text = text.replace(marker, marker + security_intro, 1)

old_update_intro = "## Updating from v1.0.0 or any v1.1.x build\n\n1. Close the application completely."
new_update_intro = (
    "## Updating from v1.0.0 or any v1.1.x build\n\n"
    "The v1.1.2 Windows executable is withdrawn. Keep it quarantined or remove it through Windows Security, delete its ZIP and extracted runtime, and migrate only a trusted `Data` folder from v1.1.1 or another known-good backup.\n\n"
    "1. Close the application completely."
)
if old_update_intro not in text:
    raise SystemExit("README update section anchor not found")
text = text.replace(old_update_intro, new_update_intro, 1)

path.write_text(text, encoding="utf-8", newline="\n")
print("README updated for v1.1.3")
