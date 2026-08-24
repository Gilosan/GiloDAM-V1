# GiloDAM 1.0.0 Alpha 2 — Test Report

Test date: 24 August 2026

## Automated verification

The included `unittest` suite verifies:

- fresh SQLite schema creation, schema version, integrity check, and validated backup;
- read-only mixed-media analysis and cancellation;
- supported/unknown classification and corrupt-image isolation;
- exact duplicate detection and Asset/Location reuse;
- permanent Asset ID persistence after service restart;
- Title/Keyword save and immediate full-text search;
- controlled-vocabulary storage;
- explicit-only JSON sidecar creation and sidecar round-trip into a fresh catalog;
- thumbnail creation, cache clearing, JSON/CSV export, and catalog backup;
- byte/mtime/path preservation for original media across representative catalog operations;
- missing-location marking and hash-verified relinking;
- refusal to follow source-file symbolic links;
- refusal to overwrite indexed originals, the active catalog, or unrelated JSON during export/backup/sidecar actions;
- refusal to index GiloDAM's own application-managed catalog/cache directory;
- settings persistence.

Expected command:

```text
python -m unittest discover -v
```

Expected result for this release: **14 tests, all passing**.

## Additional checks

- Every Python module compiles with `compileall`.
- `run_gilodam.py --self-test` opens/validates the catalog without requiring a display.
- The source/package tree is checksum-verifiable after packaging.
- Windows bootstrap scripts no longer require `py.exe`: they probe the launcher, common per-user/system Python locations, and executable commands for 64-bit Python 3.11 or newer.
- The 100,000-record synthetic catalog passed the under-two-second interactive target: exact search 0.0025 seconds median, 5,000-row browse 0.2904 seconds, and count 0.0168 seconds.
- The one-million-record architecture stress test passed catalog integrity, expected counts, FTS search, and 5,000-row materialization without a schema or memory blocker. See `BENCHMARK_REPORT.md`.

## Environment boundary

Core and database tests were executed in the build workspace. Windows bootstrap scripts received static review, but a graphical display server and Windows toolchain were not available, so Windows interface launch, WinGet installation behavior, installer behavior, Explorer integration, SmartScreen behavior, and shutdown through Windows Task Manager require the manual Windows QA pass described below.

## Required Windows acceptance pass

1. On a clean non-admin Windows account without `py.exe`, run `INSTALL_PYTHON_AND_BUILD.bat`, approve the prompt, and confirm the build continues with the installed `python.exe`.
2. Run the packaged self-test.
3. Launch, close with the window X, relaunch, and repeat after an active scan cancellation.
4. Analyze/index a copied mixed-media test folder and verify its before/after hashes and paths.
5. Test NTFS local, read-only, Unicode, long-path, and removable-drive samples.
6. Verify JPG/PNG/TIFF/WebP/GIF previews; PDF/TXT/MD previews; A/V open-original behavior.
7. Move one indexed file, scan its source, confirm Missing, and relink it by hash.
8. Clear cache and confirm thumbnails regenerate while metadata and originals remain.
9. Install/uninstall per user and confirm `%LOCALAPPDATA%\GiloDAM` is preserved.
