from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .hashing import content_hash, quick_fingerprint
from .media import extract_technical_metadata, is_sidecar, media_type_for_path, mime_type_for_path
from .models import AnalysisReport, CancelRequested, FileCandidate, utc_now


ProgressCallback = Callable[[str, int, int, str], None]


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelRequested("Analysis cancelled")


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def discover_files(
    root: Path,
    cancel_event: threading.Event | None = None,
    excluded_roots: tuple[Path, ...] = (),
) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    exclusions = tuple(path.expanduser().resolve() for path in excluded_roots)

    def on_error(error: OSError) -> None:
        errors.append(f"{type(error).__name__}: {error}")

    for directory, directory_names, file_names in os.walk(root, topdown=True, onerror=on_error, followlinks=False):
        _check_cancel(cancel_event)
        kept_directories: list[str] = []
        for name in sorted(directory_names, key=str.casefold):
            candidate_directory = (Path(directory) / name).resolve()
            if any(_is_within(candidate_directory, excluded) for excluded in exclusions):
                errors.append(f"Skipped GiloDAM application-managed directory: {candidate_directory}")
            else:
                kept_directories.append(name)
        directory_names[:] = kept_directories
        for file_name in sorted(file_names, key=str.casefold):
            path = Path(directory) / file_name
            if is_sidecar(path):
                continue
            if path.is_symlink():
                errors.append(f"Skipped symbolic link outside the V1 source contract: {path}")
                continue
            files.append(path)
    return files, errors


def analyze_folder(
    root: Path,
    *,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    excluded_roots: tuple[Path, ...] = (),
) -> AnalysisReport:
    root = Path(root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"The selected folder is unavailable: {root}")
    started = utc_now()
    if progress:
        progress("discover", 0, 0, "Finding files…")
    paths, scan_errors = discover_files(root, cancel_event, excluded_roots)
    candidates: list[FileCandidate] = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        _check_cancel(cancel_event)
        if progress:
            progress("analyze", index - 1, total, f"Analyzing {path.name}")
        media_type = media_type_for_path(path)
        mime_type = mime_type_for_path(path)
        candidate = FileCandidate(
            path=path,
            media_type=media_type,
            mime_type=mime_type,
            file_size=0,
            modified_at="",
        )
        errors: list[str] = []
        try:
            stat = path.stat()
            candidate.file_size = int(stat.st_size)
            candidate.modified_at = _timestamp(stat.st_mtime)
            candidate.quick_fingerprint = quick_fingerprint(path, cancel_event)
            candidate.content_hash = content_hash(path, cancel_event)
        except CancelRequested:
            raise
        except OSError as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

        if candidate.content_hash:
            technical, technical_error = extract_technical_metadata(path, media_type)
            candidate.technical_metadata = technical
            if technical_error:
                errors.append(technical_error)
        candidate.error = "; ".join(errors) if errors else None
        candidates.append(candidate)
        if progress:
            progress("analyze", index, total, f"Analyzed {path.name}")
    return AnalysisReport(
        root=root,
        candidates=candidates,
        started_at=started,
        completed_at=utc_now(),
        scan_errors=scan_errors,
    )
