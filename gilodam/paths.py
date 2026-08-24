from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "GiloDAM"


def app_data_dir(*, create: bool = True) -> Path:
    """Return a per-user data directory without tying the domain model to Windows."""
    override = os.environ.get("GILODAM_HOME")
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME.lower()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def catalog_path() -> Path:
    return app_data_dir() / "catalog.sqlite3"


def thumbnail_cache_dir() -> Path:
    path = app_data_dir() / "cache" / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_dir() -> Path:
    path = app_data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path

