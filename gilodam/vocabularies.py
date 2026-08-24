from __future__ import annotations


STARTER_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "General Creator": (
        "announcement", "archive", "behind-the-scenes", "concept", "detail",
        "evergreen", "finished work", "process", "reference", "tutorial",
    ),
    "YouTube": (
        "b-roll", "behind-the-scenes", "hook", "long-form", "product demo",
        "review", "short", "sponsor", "thumbnail", "tutorial", "vlog",
    ),
    "Instagram": (
        "alt-text-needed", "caption-ready", "carousel", "cover", "crop-1x1",
        "crop-4x5", "feed", "reel", "story", "vertical-9x16",
    ),
    "Artist Studio": (
        "detail", "exhibition", "finished artwork", "installation", "materials",
        "press", "process", "provenance", "sale-ready", "studio", "work-in-progress",
    ),
}


def vocabulary_values(name: str) -> tuple[str, ...]:
    return STARTER_VOCABULARIES.get(name, ())

