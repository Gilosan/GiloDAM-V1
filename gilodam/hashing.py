from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Callable

from .models import CancelRequested


CHUNK_SIZE = 1024 * 1024
FINGERPRINT_BYTES = 64 * 1024


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelRequested("Operation cancelled")


def quick_fingerprint(path: Path, cancel_event: threading.Event | None = None) -> str:
    """Fast prefilter fingerprint. Exact duplicates are confirmed with content_hash()."""
    _check_cancel(cancel_event)
    size = path.stat().st_size
    digest = hashlib.blake2b(digest_size=16)
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(FINGERPRINT_BYTES))
        _check_cancel(cancel_event)
        if size > FINGERPRINT_BYTES:
            handle.seek(max(0, size - FINGERPRINT_BYTES))
            digest.update(handle.read(FINGERPRINT_BYTES))
    return digest.hexdigest()


def content_hash(
    path: Path,
    cancel_event: threading.Event | None = None,
    progress: Callable[[int], None] | None = None,
) -> str:
    """Return a cryptographic BLAKE2b-256 digest, streaming and cancellable."""
    digest = hashlib.blake2b(digest_size=32)
    bytes_read = 0
    with path.open("rb") as handle:
        while True:
            _check_cancel(cancel_event)
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            bytes_read += len(chunk)
            if progress:
                progress(bytes_read)
    return digest.hexdigest()

