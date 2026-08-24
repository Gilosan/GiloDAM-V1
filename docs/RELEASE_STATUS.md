# GiloDAM 1.0.0 Alpha 2 — Release Status

## What this build is

This is the buildable, tested first vertical slice required by Section 24 of the developer specification. It proves the non-destructive Asset → Location → Source architecture and the complete everyday path:

**Launch → select folder → read-only analysis → review → index → counts/list → preview → technical metadata → Title/Keyword edit → controlled vocabulary → save/search → explicit JSON sidecar → close/reopen with the same Asset ID.**

It also includes verified duplicate detection, a disposable thumbnail cache, manual source rescanning, missing-location status, hash-verified relinking, image zoom/pan/navigation/slideshow, PDF/text preview, catalog backup, and JSON/CSV metadata export.

It is not being mislabeled as the production-complete implementation of all FR-001 through FR-032.

## Functional-requirement status

| Requirement | Alpha status | Note |
|---|---|---|
| FR-001 Source selection | Implemented | Manual folder selection; subfolders included. |
| FR-002 Read-only analysis | Implemented | Review precedes catalog indexing. |
| FR-003 One master catalog | Implemented | Multiple folder sources share one SQLite catalog. |
| FR-004 Original-file protection | Implemented/tested | Checksums, mtimes, and paths remain unchanged across representative operations. |
| FR-005 Technical metadata | Implemented for vertical slice | Image/text/PDF plus generic file data; ffprobe enriches A/V when present. |
| FR-006 Descriptive metadata | Implemented | Title, description, keywords, vocabulary; immediate catalog/search update on Save. |
| FR-007 Batch metadata | Deferred | Not in the locked narrow vertical slice. |
| FR-008 Schemas/templates | Partial | Four starter vocabulary/use-case sets; custom field-schema editor deferred. |
| FR-009 Controlled vocabularies | Implemented | Assisted dropdown plus freeform additions. |
| FR-010 Sidecar synchronization | Implemented/tested | Explicit, atomic JSON sync; failures leave SQLite safe. |
| FR-011 Global search | Implemented | Filename, Title, description, keyword, and path through FTS5/LIKE fallback. |
| FR-012 Structured filters | Partial | Media type and source filters implemented; full compound filter panel deferred. |
| FR-013 Image preview | Implemented | Fit, 100%, zoom, pan, previous/next. |
| FR-014 Image slideshow | Implemented | Current result set, play/pause, next/previous, configurable interval. |
| FR-015 Video preview | Deferred | Indexed/technical metadata; opens in default player. |
| FR-016 Audio preview | Deferred | Indexed/technical metadata; opens in default player. |
| FR-017 Document preview | Partial | TXT/MD read-only and PDF first-page preview; full PDF page controls deferred. |
| FR-018 Project Tags | Deferred | Data/UI extension after vertical-slice validation. |
| FR-019 Saved Collections | Deferred | Query model extension after filter completion. |
| FR-020 Duplicate detection | Implemented/tested | Cryptographic content hash; no automatic deletion/merge. |
| FR-021 Missing/offline media | Implemented | Manual scan marks missing and retains catalog/metadata/cache. |
| FR-022 Relink | Implemented/tested | Only verified hash matches are accepted. |
| FR-023 Corrupt files | Implemented/tested | Read Error is isolated; scan continues. |
| FR-024 Thumbnail cache | Implemented/tested | Application-managed and disposable. |
| FR-025 Cache limit | Partial | LRU enforcement exists in cache adapter; settings UI not wired. |
| FR-026 Catalog backup | Implemented/tested | Manual atomic SQLite backup with integrity check. |
| FR-027 Restore | Deferred | Must include guarded version/integrity workflow before exposure. |
| FR-028 Metadata export | Implemented/tested | JSON and CSV; originals are never bundled. |
| FR-029 Settings | Partial | Slideshow interval and window geometry; remaining settings deferred. |
| FR-030 Advanced Settings | Deferred | No automatic watcher/background source process in this alpha. |
| FR-031 Crash/interruption recovery | Partial | Transactional writes/cancellable scans; resume checkpoint UI deferred. |
| FR-032 Scan progress | Implemented | Analyze/index progress and safe cancellation; thumbnails generate in background. |

## Known limitations

- The Windows executable and installer scripts must be run on a Windows machine; this workspace cannot cross-compile or visually launch a Windows GUI.
- Source launch/build scripts detect both `py.exe` and standard `python.exe` installations. A consent-based helper can install 64-bit Python 3.12 per user through Windows Package Manager when neither is available.
- Embedded video/audio playback, batch editing, Project Tags, Collections, full compound filters, restore, and Advanced Settings remain intentionally deferred.
- A/V technical metadata is richer when `ffprobe` is available; indexing still proceeds without it.
- The one-million-record architecture stress test passed, but materializing 5,000 complete browse rows took about 2.12 seconds in the build environment. The specification correctly treats one million assets as an architectural target rather than the V1 SLA.
- The package is unsigned, so a private Windows build may show SmartScreen.

## Release decision

Use this alpha with copied/test media first. It is appropriate for validating the workflow and architecture. Do not call it production V1 until deferred requirements are implemented or explicitly waived and Windows manual QA is complete.
