from __future__ import annotations

import os
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .models import AssetView


class ThumbnailCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, asset_id: str, size: int = 256) -> Path:
        safe_id = "".join(character for character in asset_id if character.isalnum() or character in "-_")
        return self.directory / f"{safe_id}-{size}.jpg"

    def get_or_create(self, asset: AssetView, size: int = 256) -> Path | None:
        destination = self.path_for(asset.asset_id, size)
        if destination.exists() and destination.stat().st_size > 0:
            os.utime(destination, None)
            return destination
        source = Path(asset.path)
        if not source.exists():
            return destination if destination.exists() else None
        try:
            if asset.media_type == "image":
                thumbnail = self._from_image(source, size)
            elif asset.media_type == "document" and source.suffix.lower() == ".pdf":
                thumbnail = self._from_pdf(source, size)
            else:
                return None
            temporary = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}.jpg")
            try:
                thumbnail.convert("RGB").save(temporary, "JPEG", quality=86, optimize=True)
                os.replace(temporary, destination)
                return destination
            finally:
                temporary.unlink(missing_ok=True)
        except Exception:
            return None

    @staticmethod
    def _from_image(path: Path, size: int) -> Image.Image:
        with Image.open(path) as image:
            image.seek(0)
            converted = ImageOps.exif_transpose(image).convert("RGBA")
            converted.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (244, 246, 248, 255))
            x = (size - converted.width) // 2
            y = (size - converted.height) // 2
            canvas.alpha_composite(converted, (x, y))
            return canvas

    @staticmethod
    def _from_pdf(path: Path, size: int) -> Image.Image:
        import fitz

        document = fitz.open(path)
        try:
            if document.page_count == 0:
                raise ValueError("PDF has no pages")
            page = document.load_page(0)
            matrix = fitz.Matrix(1.5, 1.5)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (size, size), "white")
            canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
            return canvas
        finally:
            document.close()

    def placeholder(self, label: str, size: int = 96) -> Image.Image:
        image = Image.new("RGB", (size, size), "#e9edf1")
        draw = ImageDraw.Draw(image)
        text = label[:4].upper() or "FILE"
        bounds = draw.textbbox((0, 0), text)
        draw.text(
            ((size - (bounds[2] - bounds[0])) / 2, (size - (bounds[3] - bounds[1])) / 2),
            text,
            fill="#425466",
        )
        return image

    def clear(self) -> int:
        removed = 0
        for path in self.directory.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def size_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.directory.glob("*") if path.is_file())

    def enforce_limit(self, maximum_bytes: int | None) -> int:
        if not maximum_bytes or maximum_bytes <= 0:
            return 0
        files = sorted(
            (path for path in self.directory.glob("*") if path.is_file()),
            key=lambda path: path.stat().st_atime,
        )
        current = sum(path.stat().st_size for path in files)
        removed = 0
        for path in files:
            if current <= maximum_bytes:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            current -= size
            removed += 1
        return removed
