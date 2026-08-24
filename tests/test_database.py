from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from gilodam.database import CatalogDatabase, SCHEMA_VERSION


class DatabaseTests(unittest.TestCase):
    def test_fresh_migration_and_backup_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = CatalogDatabase(root / "catalog.sqlite3")
            database.initialize()
            with sqlite3.connect(database.path) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(database.integrity_check(), "ok")
            backup = database.backup_to(root / "backup.sqlite3")
            with sqlite3.connect(backup) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_settings_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite3"
            first = CatalogDatabase(path)
            first.initialize()
            first.set_setting("slideshow_interval_seconds", 7)
            second = CatalogDatabase(path)
            second.initialize()
            self.assertEqual(second.get_setting("slideshow_interval_seconds", 3), 7)


if __name__ == "__main__":
    unittest.main()

