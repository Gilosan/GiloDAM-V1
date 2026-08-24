from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    OTHER = "other"


class CancelRequested(RuntimeError):
    """Raised when a long-running operation is cancelled safely."""


@dataclass(slots=True)
class FileCandidate:
    path: Path
    media_type: MediaType
    mime_type: str
    file_size: int
    modified_at: str
    content_hash: str = ""
    quick_fingerprint: str = ""
    technical_metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(slots=True)
class AnalysisReport:
    root: Path
    candidates: list[FileCandidate]
    started_at: str
    completed_at: str
    cancelled: bool = False
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.candidates)

    @property
    def unreadable(self) -> list[FileCandidate]:
        return [candidate for candidate in self.candidates if candidate.error]

    @property
    def unreadable_count(self) -> int:
        return len(self.unreadable) + len(self.scan_errors)

    @property
    def counts(self) -> dict[str, int]:
        counts = Counter(candidate.media_type.value for candidate in self.candidates)
        return {kind.value: counts.get(kind.value, 0) for kind in MediaType}

    @property
    def duplicate_candidates(self) -> int:
        hashes = Counter(c.content_hash for c in self.candidates if c.content_hash)
        return sum(count - 1 for count in hashes.values() if count > 1)

    @property
    def estimated_index_bytes(self) -> int:
        return self.total_files * 1800

    @property
    def estimated_cache_bytes(self) -> int:
        return sum(min(256_000, max(16_000, c.file_size // 10)) for c in self.candidates if c.media_type == MediaType.IMAGE)


@dataclass(slots=True)
class AssetView:
    asset_id: str
    filename: str
    media_type: str
    mime_type: str
    file_size: int
    content_hash: str
    status: str
    path: str
    location_id: str
    source_id: str
    title: str
    description: str
    keywords: list[str]
    vocabulary_name: str
    technical_metadata: dict[str, Any]
    location_count: int = 1
