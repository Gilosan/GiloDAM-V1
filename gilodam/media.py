from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .models import MediaType


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md"}
SIDECAR_SUFFIX = ".gilodam.json"


def is_sidecar(path: Path) -> bool:
    return path.name.lower().endswith(SIDECAR_SUFFIX)


def media_type_for_path(path: Path) -> MediaType:
    extension = path.suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return MediaType.IMAGE
    if extension in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    if extension in AUDIO_EXTENSIONS:
        return MediaType.AUDIO
    if extension in DOCUMENT_EXTENSIONS:
        return MediaType.DOCUMENT
    return MediaType.OTHER


def mime_type_for_path(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type:
        return mime_type
    return "application/octet-stream"


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        # Force pixel decoding so truncated/corrupt files become a per-asset read error.
        image.load()
        metadata: dict[str, Any] = {
            "width": image.width,
            "height": image.height,
            "format": image.format or path.suffix.lstrip(".").upper(),
            "color_mode": image.mode,
            "frame_count": int(getattr(image, "n_frames", 1)),
        }
        if "icc_profile" in image.info:
            metadata["has_icc_profile"] = True
        try:
            exif = image.getexif()
            if exif:
                captured = exif.get(36867) or exif.get(306)
                if captured:
                    metadata["captured_at"] = str(captured)
        except Exception:
            pass
        return metadata


def _pdf_metadata(path: Path) -> dict[str, Any]:
    try:
        import fitz  # PyMuPDF, optional at runtime
    except ImportError:
        return {"preview_provider": "not installed"}
    document = fitz.open(path)
    try:
        return {"page_count": document.page_count, "pdf_version": document.metadata.get("format", "PDF")}
    finally:
        document.close()


def _av_metadata(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"metadata_provider": "ffprobe unavailable"}
    command = [
        ffprobe, "-v", "error", "-show_entries",
        "format=duration,bit_rate,format_name:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "ffprobe could not read the file")
    payload = json.loads(completed.stdout or "{}")
    result: dict[str, Any] = {}
    format_info = payload.get("format") or {}
    for key in ("duration", "bit_rate", "format_name"):
        if format_info.get(key) not in (None, ""):
            result[key] = format_info[key]
    streams = payload.get("streams") or []
    if streams:
        result["streams"] = streams
    return result


def extract_technical_metadata(path: Path, media_type: MediaType) -> tuple[dict[str, Any], str | None]:
    """Extract observed metadata. Parser failures are data, never scan-ending exceptions."""
    try:
        stat = path.stat()
        metadata: dict[str, Any] = {
            "file_size": stat.st_size,
            "modified_at": _iso_timestamp(stat.st_mtime),
            "created_at": _iso_timestamp(stat.st_ctime),
            "extension": path.suffix.lower(),
        }
        if media_type == MediaType.IMAGE:
            metadata.update(_image_metadata(path))
        elif media_type in (MediaType.VIDEO, MediaType.AUDIO):
            metadata.update(_av_metadata(path))
        elif media_type == MediaType.DOCUMENT and path.suffix.lower() == ".pdf":
            metadata.update(_pdf_metadata(path))
        elif media_type == MediaType.DOCUMENT:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                sample = handle.read(64 * 1024)
            metadata["sample_characters"] = len(sample)
        return metadata, None
    except (OSError, ValueError, RuntimeError, UnidentifiedImageError, json.JSONDecodeError) as exc:
        return {"extension": path.suffix.lower()}, f"{type(exc).__name__}: {exc}"
