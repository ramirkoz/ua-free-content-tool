# UA FREE Content Tool v1.1.3

Security rebuild of the v1.1.2 feature set.

## Why this release exists

The v1.1.2 Windows executable was withdrawn after Microsoft Defender reported a critical `Trojan:Win32/Wacatac.C!ml` detection. The withdrawn executable must not be restored, allowed, or added to Defender exclusions.

v1.1.3 preserves the application features introduced in v1.1.2 but replaces the Windows packaging architecture.

## New Windows runtime

- The generated unsigned PyInstaller launcher has been removed.
- `UA_FREE_Content_Tool.exe` is now the unchanged official `pythonw.exe` runtime launcher.
- Its Authenticode signature must validate to the Python Software Foundation before a build can continue.
- Python runs in isolated `_pth` mode without registry, user-site, `PYTHONPATH`, or current-directory package injection.
- Only declared runtime dependencies and application sources are included.
- Build diagnostics are deleted before packaging.
- Standard-library test suites, development utilities, virtual-environment launchers, and unrelated helper executables are removed.
- The final Windows archive contains exactly one executable: `UA_FREE_Content_Tool.exe`.

## Mandatory release security gates

Every Windows release now requires:

- the complete automated test suite;
- application import and Tk runtime checks;
- a ten-second GUI startup smoke test;
- Authenticode signature and signer verification;
- current Microsoft Defender definitions;
- a Defender custom scan of the extracted application;
- a Defender scan of the final ZIP archive;
- CRC, duplicate path, path traversal, executable-count, runtime-data, and diagnostic-file checks;
- published SHA-256 checksums.

The final v1.1.3 release passed:

- 255 automated tests;
- Windows CI on Python 3.11, 3.12, and 3.13;
- isolated application import and Tk checks;
- a ten-second GUI startup smoke test;
- Authenticode validation to the Python Software Foundation;
- a Microsoft Defender scan of the extracted runtime with current definitions: no threats;
- a Microsoft Defender scan of the final Windows ZIP: no threats;
- independent ZIP verification: 2260 unique entries, clean CRC, no unsafe paths, no runtime data, no diagnostics, and one executable only.

Published Windows Portable SHA-256:

```text
30d74d8764d3db42e0b2b45ebf95ce7eb8979a531d03edda42145d76b159c57b
```

## Included application features

v1.1.3 includes the v1.1.2 functionality:

- **Refresh all metrics** in Publication History;
- sequential background collection of available social-network statistics;
- preservation of previously collected metrics when a later request fails;
- **Evaluate potential**, combining current Threads activity with a forecast from the installation's own measured publication history;
- separate platform normalization and no conversion of unavailable metrics into artificial zeroes;
- score, confidence, measured-history count, comparable-publication count, and per-platform results.

## Updating

1. Keep the old v1.1.2 executable in quarantine or remove it through Windows Security.
2. Delete the downloaded v1.1.2 ZIP and extracted v1.1.2 application folder.
3. Extract v1.1.3 into a new folder.
4. Copy only the complete trusted `Data` folder from v1.1.1 or another known-good backup.
5. Do not copy the v1.1.2 executable, `_internal` folder, or any runtime files.
6. Scan the extracted v1.1.3 folder with Microsoft Defender before first use.

Database schema remains version 8.
