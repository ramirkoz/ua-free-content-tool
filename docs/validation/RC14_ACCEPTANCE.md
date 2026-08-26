# RC14 acceptance

Release is allowed only if:

1. PR CI passes on all configured Windows Python versions.
2. Source compile/test/import gates pass.
3. Release workflow builds the signed portable runtime.
4. Packaged EXE remains alive through the Windows startup smoke interval.
5. Microsoft Defender scan passes for extracted runtime and final ZIP.
6. Release assets are checksummed and the final Portable/Source ZIPs are roundtrip-verified after Google Drive sync.

Live acceptance after installation: UI must open without requiring Task Manager restart, and publication/statistics history must show only the rolling seven-day operational window.
