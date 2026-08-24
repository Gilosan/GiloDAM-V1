from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import AssetView, FileCandidate, utc_now


SCHEMA_VERSION = 1


class CatalogDatabase:
    """SQLite adapter. Every public operation owns its connection and transaction."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        connection = self.connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sources (
                        source_id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        root_locator TEXT NOT NULL UNIQUE,
                        watch_enabled INTEGER NOT NULL DEFAULT 0,
                        scan_settings_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS assets (
                        asset_id TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL UNIQUE,
                        quick_fingerprint TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        filename TEXT NOT NULL,
                        extension TEXT NOT NULL,
                        technical_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'available',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        schema_version INTEGER NOT NULL DEFAULT 1
                    );

                    CREATE TABLE IF NOT EXISTS asset_locations (
                        location_id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                        locator_uri TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL DEFAULT 'available',
                        last_seen_at TEXT NOT NULL,
                        last_known_locator TEXT NOT NULL,
                        read_error TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_assets_media_type ON assets(media_type);
                    CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
                    CREATE INDEX IF NOT EXISTS idx_locations_asset ON asset_locations(asset_id);
                    CREATE INDEX IF NOT EXISTS idx_locations_source ON asset_locations(source_id);
                    CREATE INDEX IF NOT EXISTS idx_locations_status ON asset_locations(status);

                    CREATE TABLE IF NOT EXISTS descriptive_metadata (
                        asset_id TEXT PRIMARY KEY REFERENCES assets(asset_id) ON DELETE CASCADE,
                        title TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        keywords_json TEXT NOT NULL DEFAULT '[]',
                        vocabulary_name TEXT NOT NULL DEFAULT 'General Creator',
                        custom_json TEXT NOT NULL DEFAULT '{}',
                        modified_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS scan_sessions (
                        scan_id TEXT PRIMARY KEY,
                        source_id TEXT,
                        root_locator TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        state TEXT NOT NULL,
                        counts_json TEXT NOT NULL DEFAULT '{}',
                        error TEXT
                    );

                    CREATE TABLE IF NOT EXISTS sidecar_state (
                        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                        location_id TEXT NOT NULL REFERENCES asset_locations(location_id) ON DELETE CASCADE,
                        sidecar_locator TEXT NOT NULL,
                        last_write_at TEXT,
                        status TEXT NOT NULL,
                        error TEXT,
                        PRIMARY KEY(asset_id, location_id)
                    );

                    CREATE TABLE IF NOT EXISTS catalog_events (
                        event_id TEXT PRIMARY KEY,
                        severity TEXT NOT NULL,
                        category TEXT NOT NULL,
                        reference_id TEXT,
                        message TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO catalog_meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS asset_fts USING fts5("
                        "asset_id UNINDEXED, filename, title, description, keywords, path)"
                    )
                    connection.execute(
                        "INSERT INTO catalog_meta(key, value) VALUES('fts5_enabled', '1') "
                        "ON CONFLICT(key) DO UPDATE SET value='1'"
                    )
                except sqlite3.OperationalError:
                    connection.execute(
                        "INSERT INTO catalog_meta(key, value) VALUES('fts5_enabled', '0') "
                        "ON CONFLICT(key) DO UPDATE SET value='0'"
                    )
        finally:
            connection.close()

    @staticmethod
    def _normalize_locator(path: Path | str) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def get_or_create_source(self, root: Path) -> str:
        locator = self._normalize_locator(root)
        now = utc_now()
        connection = self.connect()
        try:
            with connection:
                row = connection.execute("SELECT source_id FROM sources WHERE root_locator = ?", (locator,)).fetchone()
                if row:
                    connection.execute("UPDATE sources SET updated_at = ? WHERE source_id = ?", (now, row["source_id"]))
                    return str(row["source_id"])
                source_id = str(uuid.uuid4())
                display_name = Path(locator).name or locator
                connection.execute(
                    "INSERT INTO sources(source_id, type, display_name, root_locator, created_at, updated_at) "
                    "VALUES(?, 'desktop_folder', ?, ?, ?, ?)",
                    (source_id, display_name, locator, now, now),
                )
                return source_id
        finally:
            connection.close()

    def start_scan(self, root: Path, source_id: str | None = None) -> str:
        scan_id = str(uuid.uuid4())
        connection = self.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO scan_sessions(scan_id, source_id, root_locator, started_at, state) VALUES(?, ?, ?, ?, 'running')",
                    (scan_id, source_id, self._normalize_locator(root), utc_now()),
                )
            return scan_id
        finally:
            connection.close()

    def finish_scan(self, scan_id: str, *, state: str, counts: dict[str, Any], error: str | None = None) -> None:
        connection = self.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE scan_sessions SET completed_at = ?, state = ?, counts_json = ?, error = ? WHERE scan_id = ?",
                    (utc_now(), state, json.dumps(counts, sort_keys=True), error, scan_id),
                )
        finally:
            connection.close()

    def index_candidate(
        self,
        source_id: str,
        candidate: FileCandidate,
        *,
        preferred_asset_id: str | None = None,
    ) -> tuple[str, str, bool]:
        if not candidate.content_hash:
            raise ValueError(f"Cannot index {candidate.path}: content hash is missing")
        locator = self._normalize_locator(candidate.path)
        now = utc_now()
        status = "read_error" if candidate.error else "available"
        connection = self.connect()
        try:
            with connection:
                asset_row = connection.execute(
                    "SELECT asset_id FROM assets WHERE content_hash = ?", (candidate.content_hash,)
                ).fetchone()
                created = asset_row is None
                if created:
                    asset_id = str(uuid.uuid4())
                    if preferred_asset_id:
                        try:
                            candidate_id = str(uuid.UUID(preferred_asset_id))
                        except (ValueError, AttributeError):
                            candidate_id = ""
                        if candidate_id and connection.execute(
                            "SELECT 1 FROM assets WHERE asset_id=?", (candidate_id,)
                        ).fetchone() is None:
                            asset_id = candidate_id
                    connection.execute(
                        """INSERT INTO assets(
                            asset_id, content_hash, quick_fingerprint, media_type, mime_type,
                            file_size, filename, extension, technical_json, status,
                            created_at, updated_at, schema_version
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            asset_id,
                            candidate.content_hash,
                            candidate.quick_fingerprint,
                            candidate.media_type.value,
                            candidate.mime_type,
                            candidate.file_size,
                            candidate.filename,
                            candidate.path.suffix.lower(),
                            json.dumps(candidate.technical_metadata, sort_keys=True),
                            status,
                            now,
                            now,
                            SCHEMA_VERSION,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO descriptive_metadata(asset_id, modified_at) VALUES(?, ?)", (asset_id, now)
                    )
                else:
                    asset_id = str(asset_row["asset_id"])
                    connection.execute(
                        """UPDATE assets SET quick_fingerprint=?, media_type=?, mime_type=?, file_size=?,
                           filename=?, extension=?, technical_json=?, status=?, updated_at=? WHERE asset_id=?""",
                        (
                            candidate.quick_fingerprint,
                            candidate.media_type.value,
                            candidate.mime_type,
                            candidate.file_size,
                            candidate.filename,
                            candidate.path.suffix.lower(),
                            json.dumps(candidate.technical_metadata, sort_keys=True),
                            status,
                            now,
                            asset_id,
                        ),
                    )

                location_row = connection.execute(
                    "SELECT location_id FROM asset_locations WHERE locator_uri = ?", (locator,)
                ).fetchone()
                if location_row:
                    location_id = str(location_row["location_id"])
                    connection.execute(
                        """UPDATE asset_locations SET asset_id=?, source_id=?, status=?, last_seen_at=?,
                           last_known_locator=?, read_error=? WHERE location_id=?""",
                        (asset_id, source_id, status, now, locator, candidate.error, location_id),
                    )
                else:
                    location_id = str(uuid.uuid4())
                    connection.execute(
                        """INSERT INTO asset_locations(
                           location_id, asset_id, source_id, locator_uri, status,
                           last_seen_at, last_known_locator, read_error
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                        (location_id, asset_id, source_id, locator, status, now, locator, candidate.error),
                    )
                self._refresh_fts(connection, asset_id)
                return asset_id, location_id, created
        finally:
            connection.close()

    def _fts_enabled(self, connection: sqlite3.Connection) -> bool:
        row = connection.execute("SELECT value FROM catalog_meta WHERE key='fts5_enabled'").fetchone()
        return bool(row and row["value"] == "1")

    def _refresh_fts(self, connection: sqlite3.Connection, asset_id: str) -> None:
        if not self._fts_enabled(connection):
            return
        row = connection.execute(
            """SELECT a.asset_id, a.filename, d.title, d.description, d.keywords_json,
               COALESCE((SELECT GROUP_CONCAT(locator_uri, ' ') FROM asset_locations WHERE asset_id=a.asset_id), '') AS path
               FROM assets a JOIN descriptive_metadata d ON d.asset_id=a.asset_id WHERE a.asset_id=?""",
            (asset_id,),
        ).fetchone()
        connection.execute("DELETE FROM asset_fts WHERE asset_id = ?", (asset_id,))
        if row:
            try:
                keywords = " ".join(json.loads(row["keywords_json"] or "[]"))
            except json.JSONDecodeError:
                keywords = ""
            connection.execute(
                "INSERT INTO asset_fts(asset_id, filename, title, description, keywords, path) VALUES(?, ?, ?, ?, ?, ?)",
                (row["asset_id"], row["filename"], row["title"], row["description"], keywords, row["path"]),
            )

    def save_metadata(
        self,
        asset_id: str,
        *,
        title: str,
        description: str,
        keywords: Iterable[str],
        vocabulary_name: str,
        custom: dict[str, Any] | None = None,
    ) -> None:
        cleaned_keywords = sorted({item.strip() for item in keywords if item.strip()}, key=str.casefold)
        now = utc_now()
        connection = self.connect()
        try:
            with connection:
                cursor = connection.execute(
                    """UPDATE descriptive_metadata SET title=?, description=?, keywords_json=?,
                       vocabulary_name=?, custom_json=?, modified_at=? WHERE asset_id=?""",
                    (
                        title.strip(),
                        description.strip(),
                        json.dumps(cleaned_keywords, ensure_ascii=False),
                        vocabulary_name,
                        json.dumps(custom or {}, ensure_ascii=False, sort_keys=True),
                        now,
                        asset_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Unknown asset: {asset_id}")
                connection.execute("UPDATE assets SET updated_at=? WHERE asset_id=?", (now, asset_id))
                self._refresh_fts(connection, asset_id)
        finally:
            connection.close()

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> AssetView:
        try:
            keywords = list(json.loads(row["keywords_json"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            keywords = []
        try:
            technical = dict(json.loads(row["technical_json"] or "{}"))
        except (json.JSONDecodeError, TypeError):
            technical = {}
        return AssetView(
            asset_id=str(row["asset_id"]),
            filename=str(row["filename"]),
            media_type=str(row["media_type"]),
            mime_type=str(row["mime_type"]),
            file_size=int(row["file_size"]),
            content_hash=str(row["content_hash"]),
            status=str(row["location_status"] or row["asset_status"]),
            path=str(row["locator_uri"]),
            location_id=str(row["location_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"] or ""),
            description=str(row["description"] or ""),
            keywords=keywords,
            vocabulary_name=str(row["vocabulary_name"] or "General Creator"),
            technical_metadata=technical,
            location_count=int(row["location_count"]),
        )

    def _base_asset_query(self) -> str:
        return """
            SELECT a.asset_id, a.filename, a.media_type, a.mime_type, a.file_size,
                   a.content_hash, a.status AS asset_status, a.technical_json,
                   l.location_id, l.source_id, l.locator_uri, l.status AS location_status,
                   d.title, d.description, d.keywords_json, d.vocabulary_name,
                   (SELECT COUNT(*) FROM asset_locations lc WHERE lc.asset_id=a.asset_id) AS location_count
            FROM assets a
            JOIN descriptive_metadata d ON d.asset_id=a.asset_id
            JOIN asset_locations l ON l.location_id = (
                SELECT lx.location_id FROM asset_locations lx WHERE lx.asset_id=a.asset_id
                ORDER BY CASE lx.status WHEN 'available' THEN 0 ELSE 1 END, lx.last_seen_at DESC LIMIT 1
            )
        """

    def get_asset(self, asset_id: str) -> AssetView | None:
        connection = self.connect()
        try:
            row = connection.execute(self._base_asset_query() + " WHERE a.asset_id=?", (asset_id,)).fetchone()
            return self._asset_from_row(row) if row else None
        finally:
            connection.close()

    def list_assets(
        self,
        *,
        query: str = "",
        media_type: str = "all",
        source_id: str | None = None,
        limit: int = 5000,
        _force_like: bool = False,
    ) -> list[AssetView]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if media_type and media_type != "all":
            clauses.append("a.media_type = ?")
            parameters.append(media_type)
        if source_id:
            clauses.append("EXISTS(SELECT 1 FROM asset_locations sl WHERE sl.asset_id=a.asset_id AND sl.source_id=?)")
            parameters.append(source_id)
        query = query.strip()
        connection = self.connect()
        try:
            if query and self._fts_enabled(connection) and not _force_like:
                terms = [term.replace('"', '""') for term in query.split() if term]
                if terms:
                    fts_query = " AND ".join(f'"{term}"*' for term in terms)
                    clauses.append("a.asset_id IN (SELECT asset_id FROM asset_fts WHERE asset_fts MATCH ?)")
                    parameters.append(fts_query)
            elif query:
                like = f"%{query}%"
                clauses.append(
                    "(a.filename LIKE ? OR d.title LIKE ? OR d.description LIKE ? OR d.keywords_json LIKE ? OR l.locator_uri LIKE ?)"
                )
                parameters.extend([like] * 5)
            sql = self._base_asset_query()
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY COALESCE(NULLIF(d.title, ''), a.filename) COLLATE NOCASE LIMIT ?"
            parameters.append(limit)
            try:
                rows = connection.execute(sql, parameters).fetchall()
            except sqlite3.OperationalError as exc:
                if query and not _force_like:
                    return self.list_assets(
                        query=query,
                        media_type=media_type,
                        source_id=source_id,
                        limit=limit,
                        _force_like=True,
                    )
                raise
            return [self._asset_from_row(row) for row in rows]
        finally:
            connection.close()

    def source_rows(self) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                """SELECT s.*, COUNT(DISTINCT l.asset_id) AS asset_count
                   FROM sources s LEFT JOIN asset_locations l ON l.source_id=s.source_id
                   GROUP BY s.source_id ORDER BY s.display_name COLLATE NOCASE"""
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def catalog_counts(self) -> dict[str, int]:
        connection = self.connect()
        try:
            rows = connection.execute("SELECT media_type, COUNT(*) AS count FROM assets GROUP BY media_type").fetchall()
            result = {str(row["media_type"]): int(row["count"]) for row in rows}
            result["total"] = sum(result.values())
            result["duplicate_locations"] = int(
                connection.execute(
                    "SELECT COALESCE(SUM(location_count - 1), 0) FROM (SELECT COUNT(*) AS location_count FROM asset_locations GROUP BY asset_id HAVING COUNT(*) > 1)"
                ).fetchone()[0]
            )
            return result
        finally:
            connection.close()

    def mark_source_missing_locations(self, source_id: str, seen_paths: set[str]) -> int:
        normalized = {self._normalize_locator(path) for path in seen_paths}
        connection = self.connect()
        changed = 0
        try:
            with connection:
                rows = connection.execute(
                    "SELECT location_id, locator_uri, asset_id FROM asset_locations WHERE source_id=?", (source_id,)
                ).fetchall()
                for row in rows:
                    if row["locator_uri"] not in normalized:
                        cursor = connection.execute(
                            "UPDATE asset_locations SET status='missing' WHERE location_id=? AND status!='missing'",
                            (row["location_id"],),
                        )
                        changed += cursor.rowcount
                        self._refresh_fts(connection, str(row["asset_id"]))
            return changed
        finally:
            connection.close()

    def relink_location(self, location_id: str, new_path: Path) -> None:
        locator = self._normalize_locator(new_path)
        connection = self.connect()
        try:
            with connection:
                row = connection.execute("SELECT asset_id FROM asset_locations WHERE location_id=?", (location_id,)).fetchone()
                if not row:
                    raise KeyError(f"Unknown location: {location_id}")
                target = connection.execute(
                    "SELECT location_id, asset_id FROM asset_locations WHERE locator_uri=?", (locator,)
                ).fetchone()
                if target and target["location_id"] != location_id:
                    if target["asset_id"] != row["asset_id"]:
                        raise ValueError("The selected location is already assigned to a different asset.")
                    connection.execute("DELETE FROM asset_locations WHERE location_id=?", (location_id,))
                    connection.execute(
                        "UPDATE asset_locations SET status='available', last_seen_at=?, read_error=NULL WHERE location_id=?",
                        (utc_now(), target["location_id"]),
                    )
                else:
                    connection.execute(
                        """UPDATE asset_locations SET locator_uri=?, last_known_locator=?, status='available',
                           last_seen_at=?, read_error=NULL WHERE location_id=?""",
                        (locator, locator, utc_now(), location_id),
                    )
                self._refresh_fts(connection, str(row["asset_id"]))
        finally:
            connection.close()

    def locations_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM asset_locations WHERE asset_id=? ORDER BY status, locator_uri", (asset_id,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def record_sidecar(
        self, asset_id: str, location_id: str, sidecar_path: Path, *, status: str, error: str | None = None
    ) -> None:
        connection = self.connect()
        try:
            with connection:
                connection.execute(
                    """INSERT INTO sidecar_state(asset_id, location_id, sidecar_locator, last_write_at, status, error)
                       VALUES(?, ?, ?, ?, ?, ?)
                       ON CONFLICT(asset_id, location_id) DO UPDATE SET sidecar_locator=excluded.sidecar_locator,
                       last_write_at=excluded.last_write_at, status=excluded.status, error=excluded.error""",
                    (asset_id, location_id, self._normalize_locator(sidecar_path), utc_now(), status, error),
                )
        finally:
            connection.close()

    def log_event(self, severity: str, category: str, message: str, reference_id: str | None = None) -> None:
        connection = self.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO catalog_events(event_id, severity, category, reference_id, message, timestamp) VALUES(?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), severity, category, reference_id, message, utc_now()),
                )
        finally:
            connection.close()

    def export_rows(self) -> list[dict[str, Any]]:
        assets = self.list_assets(limit=1_000_000)
        return [
            {
                "asset_id": asset.asset_id,
                "filename": asset.filename,
                "path": asset.path,
                "media_type": asset.media_type,
                "mime_type": asset.mime_type,
                "file_size": asset.file_size,
                "content_hash": asset.content_hash,
                "status": asset.status,
                "title": asset.title,
                "description": asset.description,
                "keywords": asset.keywords,
                "vocabulary_name": asset.vocabulary_name,
                "technical_metadata": asset.technical_metadata,
                "locations": self.locations_for_asset(asset.asset_id),
            }
            for asset in assets
        ]

    def backup_to(self, destination: Path) -> Path:
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError("Choose a backup destination different from the active catalog.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}")
        source = self.connect()
        target = sqlite3.connect(temporary)
        try:
            source.backup(target)
            target.commit()
            check = target.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise sqlite3.DatabaseError(f"Backup integrity check failed: {check}")
        finally:
            target.close()
            source.close()
        os.replace(temporary, destination)
        return destination

    def integrity_check(self) -> str:
        connection = self.connect()
        try:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

    def is_asset_location(self, path: Path) -> bool:
        locator = self._normalize_locator(path)
        connection = self.connect()
        try:
            return connection.execute(
                "SELECT 1 FROM asset_locations WHERE locator_uri=? LIMIT 1", (locator,)
            ).fetchone() is not None
        finally:
            connection.close()

    def set_setting(self, key: str, value: Any) -> None:
        connection = self.connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, json.dumps(value)),
                )
        finally:
            connection.close()

    def get_setting(self, key: str, default: Any = None) -> Any:
        connection = self.connect()
        try:
            row = connection.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
            return json.loads(row["value_json"]) if row else default
        finally:
            connection.close()
