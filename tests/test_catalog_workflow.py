from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gilodam.database import CatalogDatabase
from gilodam.service import GiloDAMService
from gilodam.thumbnails import ThumbnailCache

from .helpers import create_png, create_service, file_digest, snapshot_files


class CatalogWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        original = create_png(self.source / "robot.png", (250, 90, 40))
        shutil.copyfile(original, self.source / "robot-duplicate.png")
        (self.source / "essay.md").write_text("# Why Robots\n\nBecause I like robots.\n", encoding="utf-8")
        self.service = create_service(self.root / "appdata")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _index(self):
        report = self.service.analyze(self.source)
        counts = self.service.index_report(report)
        return report, counts

    def test_index_identity_metadata_search_and_restart(self) -> None:
        before = snapshot_files(self.source)
        report, counts = self._index()
        self.assertEqual(counts["indexed"], 3)
        self.assertEqual(counts["created"], 2)
        self.assertEqual(counts["reused"], 1)
        self.assertEqual(before, snapshot_files(self.source))

        assets = self.service.assets()
        self.assertEqual(len(assets), 2)
        image = next(asset for asset in assets if asset.media_type == "image")
        self.assertEqual(image.location_count, 2)
        permanent_id = image.asset_id

        updated = self.service.save_metadata(
            image.asset_id,
            title="Orange Robot",
            description="A controlled test asset",
            keywords=["finished artwork", "robot"],
            vocabulary_name="Artist Studio",
        )
        self.assertEqual(updated.title, "Orange Robot")
        self.assertEqual([item.asset_id for item in self.service.assets(query="Orange")], [permanent_id])
        self.assertEqual([item.asset_id for item in self.service.assets(query="robot")], [permanent_id])
        self.assertEqual(self.service.assets(query='"'), [])
        self.assertEqual(before, snapshot_files(self.source))

        restarted = GiloDAMService(
            CatalogDatabase(self.root / "appdata" / "catalog.sqlite3"),
            ThumbnailCache(self.root / "appdata" / "cache"),
        )
        restarted.initialize()
        reopened = restarted.asset(permanent_id)
        self.assertIsNotNone(reopened)
        self.assertEqual(reopened.asset_id, permanent_id)
        self.assertEqual(reopened.title, "Orange Robot")
        self.assertEqual(restarted.database.integrity_check(), "ok")

    def test_sidecar_is_explicit_and_round_trips(self) -> None:
        original_digest = file_digest(self.source / "robot.png")
        self._index()
        image = next(asset for asset in self.service.assets() if asset.media_type == "image")
        self.service.save_metadata(
            image.asset_id,
            title="Portable Robot",
            description="Metadata should travel",
            keywords=["archive", "provenance"],
            vocabulary_name="Artist Studio",
        )
        self.assertFalse((Path(image.path).with_name(Path(image.path).name + ".gilodam.json")).exists())
        sidecar = self.service.sync_sidecar(image.asset_id)
        self.assertTrue(sidecar.exists())
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload["asset_id"], image.asset_id)
        self.assertEqual(payload["descriptive_metadata"]["title"], "Portable Robot")
        self.assertEqual(file_digest(Path(image.path)), original_digest)

        second = create_service(self.root / "second-appdata")
        second_report = second.analyze(self.source)
        self.assertEqual(second_report.total_files, 3)
        result = second.index_report(second_report)
        self.assertEqual(result["sidecars_imported"], 1)
        imported = next(asset for asset in second.assets() if asset.content_hash == image.content_hash)
        self.assertEqual(imported.asset_id, image.asset_id)
        self.assertEqual(imported.title, "Portable Robot")

    def test_sidecar_refuses_to_overwrite_unrelated_json(self) -> None:
        self._index()
        image = next(asset for asset in self.service.assets() if asset.media_type == "image")
        sidecar = Path(image.path).with_name(Path(image.path).name + ".gilodam.json")
        sidecar.write_text('{"belongs_to": "another program"}\n', encoding="utf-8")
        before = sidecar.read_bytes()
        with self.assertRaises(FileExistsError):
            self.service.sync_sidecar(image.asset_id)
        self.assertEqual(sidecar.read_bytes(), before)

    def test_thumbnail_cache_clear_and_exports_are_non_destructive(self) -> None:
        before = snapshot_files(self.source)
        self._index()
        image = next(asset for asset in self.service.assets() if asset.media_type == "image")
        thumbnail = self.service.thumbnail_for(image, 128)
        self.assertIsNotNone(thumbnail)
        self.assertTrue(thumbnail.exists())
        self.assertEqual(before, snapshot_files(self.source))
        self.assertGreaterEqual(self.service.clear_thumbnail_cache(), 1)
        self.assertFalse(thumbnail.exists())
        self.assertIsNotNone(self.service.asset(image.asset_id))
        self.assertEqual(before, snapshot_files(self.source))

        json_export = self.service.export_json(self.root / "metadata.json")
        csv_export = self.service.export_csv(self.root / "metadata.csv")
        backup = self.service.backup_catalog(self.root / "backup.sqlite3")
        self.assertTrue(json_export.exists())
        self.assertTrue(csv_export.exists())
        self.assertTrue(backup.exists())
        self.assertEqual(before, snapshot_files(self.source))

    def test_export_and_backup_refuse_active_catalog_or_original_paths(self) -> None:
        self._index()
        image = next(asset for asset in self.service.assets() if asset.media_type == "image")
        original = Path(image.path)
        before = original.read_bytes()
        with self.assertRaises(ValueError):
            self.service.export_json(original)
        self.assertEqual(original.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.service.backup_catalog(self.service.database.path)

    def test_active_application_data_cannot_be_selected_as_media(self) -> None:
        with self.assertRaises(ValueError):
            self.service.analyze(self.service.database.path.parent)

    def test_corrupt_media_is_cataloged_as_read_error_without_aborting(self) -> None:
        (self.source / "corrupt.jpg").write_bytes(b"not a valid jpeg")
        report = self.service.analyze(self.source)
        counts = self.service.index_report(report)
        self.assertEqual(counts["failed"], 0)
        corrupt = next(asset for asset in self.service.assets() if asset.filename == "corrupt.jpg")
        self.assertEqual(corrupt.status, "read_error")
        self.assertEqual(self.service.database.integrity_check(), "ok")

    def test_missing_asset_relinks_only_on_verified_hash(self) -> None:
        create_png(self.source / "unique-blue.png", (25, 70, 210))
        self._index()
        image = next(asset for asset in self.service.assets() if asset.filename == "unique-blue.png")
        original_path = Path(image.path)
        moved_dir = self.root / "moved"
        moved_dir.mkdir()
        moved_path = moved_dir / original_path.name
        original_path.replace(moved_path)

        rescan = self.service.analyze(self.source)
        counts = self.service.index_report(rescan)
        self.assertEqual(counts["missing"], 1)
        missing = self.service.asset(image.asset_id)
        self.assertIsNotNone(missing)
        self.assertEqual(missing.status, "missing")

        bad_path = moved_dir / "different.png"
        create_png(bad_path, (10, 20, 30))
        with self.assertRaises(ValueError):
            self.service.relink(image.asset_id, bad_path)
        relinked = self.service.relink(image.asset_id, moved_path)
        self.assertEqual(relinked.asset_id, image.asset_id)
        self.assertEqual(Path(relinked.path), moved_path)


if __name__ == "__main__":
    unittest.main()
