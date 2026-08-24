# GiloDAM V1 Alpha Architecture

## Boundary

The implementation is intentionally split into four layers:

- `models.py`, `hashing.py`, `media.py`, and `sidecar.py`: portable domain and media rules.
- `database.py`, `scanner.py`, `thumbnails.py`, and `service.py`: application and persistence use cases.
- `platform_services.py`: desktop-specific open-file and DPI behavior.
- `ui.py`: the Tk desktop interface.

The core does not use drive-letter parsing, Windows path separators, registry calls, or Windows media APIs. `pathlib` and a platform adapter isolate desktop differences. A macOS desktop build can reuse the catalog and application layers. A future mobile companion can reuse the stable catalog contract even if its UI and source adapters are native.

## Identity

An Asset is a permanent UUID plus a verified BLAKE2b-256 content hash. A path is a Location, never the asset identity. Identical files at several paths become one Asset with several Locations. GiloDAM reports duplicate locations and never deletes or merges source files.

## Storage

SQLite is the operational catalog. It uses WAL mode, foreign keys, busy timeouts, transactions, schema versioning, indexed structured fields, and FTS5 when the bundled SQLite supports it. Descriptive metadata updates refresh the search index in the same transaction.

JSON sidecars are a deliberate interchange action. Catalog edits never write a sidecar per keystroke. Sidecars are written atomically beside the selected media only when the user chooses **Sync JSON Sidecar**. A failed sidecar write leaves the SQLite metadata intact.

## Non-destructive scan

Analysis enumerates, stats, reads, fingerprints, hashes, and parses selected files. It does not create files in the source folder. Indexing writes only to the application catalog and application-managed cache. Scan and hashing work is cancellable between read chunks/files.

## Cache

Thumbnails use an application-owned disposable cache. The cache can be cleared without touching asset rows, metadata, sidecars, or originals. Missing media can continue to use an existing cached thumbnail.

## Shutdown

No watcher or startup scan runs in this alpha. Worker threads are daemonized and receive a cancellation signal on shutdown. Each database operation owns its connection and transaction, so an interrupted operation rolls back to the last committed state. There is no persistent process lock that could force a reinstall before restart.

