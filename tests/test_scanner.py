from __future__ import annotations

import shutil
import os
import tempfile
import threading
import unittest
from pathlib import Path

from gilodam.models import CancelRequested
from gilodam.scanner import analyze_folder

from .helpers import create_png, snapshot_files


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        original = create_png(self.root / "robot.png")
        shutil.copyfile(original, self.root / "robot-copy.png")
        (self.root / "notes.txt").write_text("GiloDAM test note\n", encoding="utf-8")
        (self.root / "unknown.bin").write_bytes(b"\x00\x01unknown")
        (self.root / "broken.jpg").write_bytes(b"this is not a jpeg")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_analysis_is_read_only_and_reports_mixed_media(self) -> None:
        before = snapshot_files(self.root)
        report = analyze_folder(self.root)
        after = snapshot_files(self.root)
        self.assertEqual(before, after)
        self.assertEqual(report.total_files, 5)
        self.assertEqual(report.counts["image"], 3)
        self.assertEqual(report.counts["document"], 1)
        self.assertEqual(report.counts["other"], 1)
        self.assertEqual(report.duplicate_candidates, 1)
        self.assertEqual(report.unreadable_count, 1)
        self.assertIn("broken.jpg", report.unreadable[0].path.name)

    def test_gilodam_sidecars_are_not_assets(self) -> None:
        (self.root / "robot.png.gilodam.json").write_text('{"schema_version": 1}', encoding="utf-8")
        report = analyze_folder(self.root)
        self.assertEqual(report.total_files, 5)

    def test_analysis_is_cancellable(self) -> None:
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelRequested):
            analyze_folder(self.root, cancel_event=cancel)

    def test_symbolic_link_is_not_followed(self) -> None:
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside selected source", encoding="utf-8")
        link = self.root / "outside-link.txt"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable")
        report = analyze_folder(self.root)
        self.assertNotIn(link, [candidate.path for candidate in report.candidates])
        self.assertTrue(any("symbolic link" in error for error in report.scan_errors))


if __name__ == "__main__":
    unittest.main()
