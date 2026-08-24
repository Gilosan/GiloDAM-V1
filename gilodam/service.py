from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from .database import CatalogDatabase
from .hashing import content_hash
from .models import AnalysisReport, AssetView, CancelRequested
from .scanner import ProgressCallback, analyze_folder
from .sidecar import read_sidecar, write_sidecar
from .thumbnails import ThumbnailCache


IndexProgress = Callable[[int, int, str], None]


class GiloDAMService:
    """Application use cases. UI and operating-system actions stay outside the core."""

    def __init__(self, database: CatalogDatabase, thumbnail_cache: ThumbnailCache):
        self.database = database
        self.thumbnail_cache = thumbnail_cache

    def initialize(self) -> None:
        self.database.initialize()

    def analyze(
        self,
        root: Path,
        *,
        cancel_event: threading.Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> AnalysisReport:
        selected = Path(root).expanduser().resolve()
        managed_root = self.database.path.parent.expanduser().resolve()
        try:
            selected.relative_to(managed_root)
            inside_managed_root = True
        except ValueError:
            inside_managed_root = False
        if inside_managed_root:
            raise ValueError("Choose a media folder outside GiloDAM's application-managed catalog/cache directory.")
        return analyze_folder(
            selected,
            cancel_event=cancel_event,
            progress=progress,
            excluded_roots=(managed_root,),
        )

    def index_report(
        self,
        report: AnalysisReport,
        *,
        selected_paths: Iterable[Path] | None = None,
        cancel_event: threading.Event | None = None,
        progress: IndexProgress | None = None,
    ) -> dict[str, int]:
        selected = {str(Path(path).resolve()) for path in selected_paths} if selected_paths is not None else None
        candidates = [candidate for candidate in report.candidates if selected is None or str(candidate.path.resolve()) in selected]
        sidecars_by_hash: dict[str, dict[str, Any]] = {}
        for candidate in report.candidates:
            if not candidate.content_hash:
                continue
            payload = read_sidecar(candidate.path)
            if payload and payload.get("content_hash") == candidate.content_hash:
                sidecars_by_hash.setdefault(candidate.content_hash, payload)
        source_id = self.database.get_or_create_source(report.root)
        scan_id = self.database.start_scan(report.root, source_id)
        counts = {"indexed": 0, "created": 0, "reused": 0, "failed": 0, "sidecars_imported": 0, "missing": 0}
        try:
            for index, candidate in enumerate(candidates, start=1):
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelRequested("Indexing cancelled")
                if progress:
                    progress(index - 1, len(candidates), f"Indexing {candidate.filename}")
                if not candidate.content_hash:
                    counts["failed"] += 1
                    self.database.log_event("warning", "index", candidate.error or "Missing content hash", str(candidate.path))
                    continue
                portable = sidecars_by_hash.get(candidate.content_hash)
                preferred_asset_id = str(portable.get("asset_id")) if portable and portable.get("asset_id") else None
                asset_id, _location_id, created = self.database.index_candidate(
                    source_id,
                    candidate,
                    preferred_asset_id=preferred_asset_id,
                )
                counts["indexed"] += 1
                counts["created" if created else "reused"] += 1
                if created and portable and self._import_sidecar_payload(asset_id, portable):
                    counts["sidecars_imported"] += 1
                if progress:
                    progress(index, len(candidates), f"Indexed {candidate.filename}")
            # The full read-only report is authoritative for this manual scan,
            # even when the user indexed only a subset of newly discovered files.
            counts["missing"] = self.database.mark_source_missing_locations(
                source_id, {str(candidate.path) for candidate in report.candidates}
            )
            self.database.finish_scan(scan_id, state="completed", counts=counts)
            return counts
        except CancelRequested:
            self.database.finish_scan(scan_id, state="cancelled", counts=counts)
            raise
        except Exception as exc:
            self.database.finish_scan(scan_id, state="failed", counts=counts, error=str(exc))
            raise

    def _import_sidecar_payload(self, asset_id: str, payload: dict[str, Any]) -> bool:
        metadata = payload.get("descriptive_metadata") or {}
        if not isinstance(metadata, dict):
            return False
        self.database.save_metadata(
            asset_id,
            title=str(metadata.get("title") or ""),
            description=str(metadata.get("description") or ""),
            keywords=[str(item) for item in metadata.get("keywords") or []],
            vocabulary_name=str(metadata.get("vocabulary_name") or "General Creator"),
        )
        return True

    def assets(self, *, query: str = "", media_type: str = "all", source_id: str | None = None) -> list[AssetView]:
        return self.database.list_assets(query=query, media_type=media_type, source_id=source_id)

    def asset(self, asset_id: str) -> AssetView | None:
        return self.database.get_asset(asset_id)

    def save_metadata(
        self,
        asset_id: str,
        *,
        title: str,
        description: str,
        keywords: Iterable[str],
        vocabulary_name: str,
    ) -> AssetView:
        self.database.save_metadata(
            asset_id,
            title=title,
            description=description,
            keywords=keywords,
            vocabulary_name=vocabulary_name,
        )
        updated = self.database.get_asset(asset_id)
        if updated is None:
            raise KeyError(asset_id)
        return updated

    def sync_sidecar(self, asset_id: str) -> Path:
        asset = self.database.get_asset(asset_id)
        if asset is None:
            raise KeyError(f"Unknown asset: {asset_id}")
        media_path = Path(asset.path)
        if not media_path.exists():
            raise FileNotFoundError(f"Cannot write sidecar while the original is offline: {media_path}")
        try:
            sidecar_path = write_sidecar(asset, media_path)
            self.database.record_sidecar(asset.asset_id, asset.location_id, sidecar_path, status="synced")
            return sidecar_path
        except Exception as exc:
            fallback = media_path.with_name(media_path.name + ".gilodam.json")
            self.database.record_sidecar(asset.asset_id, asset.location_id, fallback, status="failed", error=str(exc))
            raise

    def thumbnail_for(self, asset: AssetView, size: int = 256) -> Path | None:
        return self.thumbnail_cache.get_or_create(asset, size=size)

    def clear_thumbnail_cache(self) -> int:
        return self.thumbnail_cache.clear()

    def relink(self, asset_id: str, new_path: Path) -> AssetView:
        asset = self.database.get_asset(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        new_path = Path(new_path).expanduser().resolve()
        if not new_path.is_file():
            raise FileNotFoundError(new_path)
        observed_hash = content_hash(new_path)
        if observed_hash != asset.content_hash:
            raise ValueError("The selected file does not match this asset's verified content hash.")
        self.database.relink_location(asset.location_id, new_path)
        updated = self.database.get_asset(asset_id)
        if updated is None:
            raise KeyError(asset_id)
        return updated

    def refresh_missing_status(self, report: AnalysisReport) -> int:
        source_id = self.database.get_or_create_source(report.root)
        seen = {str(candidate.path) for candidate in report.candidates}
        return self.database.mark_source_missing_locations(source_id, seen)

    def export_json(self, destination: Path) -> Path:
        destination = Path(destination)
        if self.database.is_asset_location(destination):
            raise ValueError("Refusing to overwrite an indexed original with a metadata export.")
        payload = {"schema_version": 1, "assets": self.database.export_rows()}
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(destination)
        return destination

    def export_csv(self, destination: Path) -> Path:
        destination = Path(destination)
        if self.database.is_asset_location(destination):
            raise ValueError("Refusing to overwrite an indexed original with a metadata export.")
        rows = self.database.export_rows()
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "asset_id", "filename", "path", "media_type", "mime_type", "file_size",
                    "content_hash", "status", "title", "description", "keywords", "vocabulary_name",
                ],
            )
            writer.writeheader()
            for row in rows:
                flat = {key: row.get(key, "") for key in writer.fieldnames}
                flat["keywords"] = "; ".join(row.get("keywords") or [])
                writer.writerow(flat)
        temporary.replace(destination)
        return destination

    def backup_catalog(self, destination: Path) -> Path:
        return self.database.backup_to(destination)

    def status(self) -> dict[str, Any]:
        return {
            "catalog": self.database.catalog_counts(),
            "cache_bytes": self.thumbnail_cache.size_bytes(),
            "integrity": self.database.integrity_check(),
        }
