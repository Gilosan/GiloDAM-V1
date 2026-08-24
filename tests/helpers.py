from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from gilodam.database import CatalogDatabase
from gilodam.service import GiloDAMService
from gilodam.thumbnails import ThumbnailCache


def create_png(path: Path, color: tuple[int, int, int] = (220, 55, 45), size: tuple[int, int] = (80, 60)) -> Path:
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def create_service(root: Path) -> GiloDAMService:
    service = GiloDAMService(CatalogDatabase(root / "catalog.sqlite3"), ThumbnailCache(root / "cache"))
    service.initialize()
    return service


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_files(root: Path) -> dict[str, tuple[str, int]]:
    return {
        str(path.relative_to(root)): (file_digest(path), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }

