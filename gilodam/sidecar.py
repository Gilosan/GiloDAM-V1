from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from .media import SIDECAR_SUFFIX
from .models import AssetView, utc_now


SIDECAR_SCHEMA = "https://gilodam.local/schemas/sidecar/v1"


def sidecar_path_for(media_path: Path) -> Path:
    return media_path.with_name(media_path.name + SIDECAR_SUFFIX)


def build_sidecar(asset: AssetView) -> dict[str, Any]:
    return {
        "$schema": SIDECAR_SCHEMA,
        "schema_version": 1,
        "asset_id": asset.asset_id,
        "content_hash": asset.content_hash,
        "media_type": asset.media_type,
        "descriptive_metadata": {
            "title": asset.title,
            "description": asset.description,
            "keywords": list(asset.keywords),
            "vocabulary_name": asset.vocabulary_name,
        },
        "technical_metadata": asset.technical_metadata,
        "synced_at": utc_now(),
    }


def write_sidecar(asset: AssetView, media_path: Path) -> Path:
    """Atomically write portable metadata only after an explicit user action."""
    destination = sidecar_path_for(media_path)
    if destination.exists():
        try:
            with destination.open("r", encoding="utf-8") as existing_handle:
                existing = json.load(existing_handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise FileExistsError(
                f"Refusing to overwrite an existing non-GiloDAM sidecar: {destination}"
            ) from exc
        if not isinstance(existing, dict) or existing.get("$schema") != SIDECAR_SCHEMA:
            raise FileExistsError(f"Refusing to overwrite an unrelated JSON file: {destination}")
    temporary = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}")
    payload = build_sidecar(asset)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def read_sidecar(media_path: Path) -> dict[str, Any] | None:
    path = sidecar_path_for(media_path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return None
        return payload
    except (OSError, json.JSONDecodeError):
        return None
