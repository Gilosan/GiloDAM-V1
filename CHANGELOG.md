# Changelog

## 1.0.0-alpha.2 — 2026-08-24

- Removed the hard dependency on the Windows `py.exe` launcher.
- Added discovery and validation for standard 64-bit Python 3.11+ installations.
- Added consent-based, per-user Python 3.12 setup helpers for source launch and Windows packaging.
- Added actionable launcher troubleshooting without changing catalog or source-media behavior.

## 1.0.0-alpha.1 — 2026-08-24

- Built the first end-to-end GiloDAM vertical slice.
- Added permanent UUID/content-hash identity and Asset → Location → Source catalog model.
- Added read-only folder analysis, review counts, duplicate candidates, estimates, errors, selection, indexing, and progress/cancel.
- Added mixed-media classification and technical metadata adapters.
- Added image thumbnails, preview, fit/100%/zoom/pan, result navigation, and slideshow.
- Added TXT/Markdown and first-page PDF preview.
- Added descriptive metadata, starter controlled vocabularies, freeform keywords, SQLite search, and explicit JSON sidecars.
- Added manual source rescanning, missing status, verified relink, cache clearing, backup, and JSON/CSV export.
- Added graceful shutdown with no background watcher or persistent process lock.
- Added Windows source launcher, portable build, optional per-user installer, self-test, checksums, and automated tests.
