from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .database import CatalogDatabase
from .logging_config import configure_logging
from .paths import catalog_path, log_dir, thumbnail_cache_dir
from .platform_services import set_windows_dpi_awareness
from .service import GiloDAMService
from .thumbnails import ThumbnailCache


def build_service() -> GiloDAMService:
    service = GiloDAMService(CatalogDatabase(catalog_path()), ThumbnailCache(thumbnail_cache_dir()))
    service.initialize()
    return service


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GiloDAM local digital asset catalog")
    parser.add_argument("--self-test", action="store_true", help="run startup/catalog diagnostics without opening the UI")
    parser.add_argument(
        "--ui-smoke-test",
        action="store_true",
        help="open the desktop UI briefly, then close it cleanly (release verification)",
    )
    parser.add_argument("--data-dir", type=Path, help="override the per-user GiloDAM data directory")
    parser.add_argument("--version", action="store_true", help="print the application version")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.data_dir:
        os.environ["GILODAM_HOME"] = str(args.data_dir.expanduser().resolve())
    logger = configure_logging(log_dir())
    try:
        service = build_service()
        if args.self_test:
            result = {
                "application": "GiloDAM",
                "version": __version__,
                "catalog_path": str(catalog_path()),
                "catalog": service.status(),
                "result": "pass",
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        set_windows_dpi_awareness()
        import tkinter as tk

        from .ui import GiloDAMApp

        root = tk.Tk()
        GiloDAMApp(root, service, logger=logger)
        if args.ui_smoke_test:
            root.after(1500, root.destroy)
        root.mainloop()
        return 0
    except Exception as exc:
        logger.exception("GiloDAM startup failed: %s", exc)
        if args.self_test:
            print(json.dumps({"application": "GiloDAM", "version": __version__, "result": "fail", "error": str(exc)}))
            return 1
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror("GiloDAM could not start", f"GiloDAM could not start safely.\n\n{exc}")
        except Exception:
            print(f"GiloDAM could not start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
