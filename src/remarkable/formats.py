"""reMarkable file format parsing.

Wraps the rmscene library to read .rm v6 pages and group colored strokes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from rmscene import SceneTree, read_tree
from rmscene.scene_items import Line, PenColor

logger = logging.getLogger(__name__)

# Map rmscene PenColor enum to the integer indices used in config
COLOR_INDEX_MAP: dict[PenColor, int] = {
    PenColor.BLACK: 0,
    PenColor.GRAY: 1,
    PenColor.WHITE: 2,
    PenColor.YELLOW: 3,
    PenColor.GREEN: 4,
    PenColor.BLUE: 5,
    PenColor.RED: 6,
    PenColor.PINK: 7,
}

# Reverse map for lookup by index
INDEX_COLOR_MAP: dict[int, PenColor] = {v: k for k, v in COLOR_INDEX_MAP.items()}

@dataclass
class StrokeGroup:
    """A group of strokes with the same color in a spatial region."""

    color: PenColor
    color_index: int
    lines: list[Line]
    bbox: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    page_id: str = ""

    @property
    def color_name(self) -> str:
        return self.color.name.lower()


@dataclass
class PageContent:
    """Parsed content from a single .rm page."""

    page_id: str
    tree: SceneTree = field(default_factory=SceneTree)

    @property
    def lines(self) -> list[Line]:
        return [item for item in self.tree.walk() if isinstance(item, Line)]


@dataclass
class Notebook:
    """A fully parsed reMarkable notebook."""

    id: str
    name: str
    folder: str
    modified: str
    pages: list[PageContent]
    file_type: str = "notebook"  # "notebook" | "pdf" | "epub"

    @property
    def page_count(self) -> int:
        return len(self.pages)

def parse_rm_file(rm_path: Path) -> PageContent:
    """Parse typed text, ink, and layout from one .rm v6 scene."""
    with rm_path.open("rb") as source:
        return PageContent(page_id=rm_path.stem, tree=read_tree(source))


def parse_notebook(doc_dir: Path, doc_id: str, page_ids: list[str]) -> list[PageContent]:
    """Parse all pages of a notebook.

    Args:
        doc_dir: Directory containing the downloaded document files.
        doc_id: The document UUID.
        page_ids: Ordered list of page UUIDs.

    Returns:
        List of PageContent, one per page.
    """
    pages = []

    for page_id in page_ids:
        # .rm files can be at different paths depending on download format
        rm_path = _find_rm_file(doc_dir, doc_id, page_id)

        if rm_path is None:
            logger.debug("No .rm file for blank page %s", page_id[:8])
            pages.append(PageContent(page_id=page_id))
            continue

        try:
            pages.append(parse_rm_file(rm_path))
        except Exception as e:
            raise ValueError(f"Failed to parse reMarkable page {page_id}: {e}") from e

    return pages


def extract_strokes_by_color(
    pages: list[PageContent], colors: list[int]
) -> dict[str, list[StrokeGroup]]:
    """Extract strokes filtered by color index.

    Args:
        colors: List of color indices (0=black, 1=grey, ..., 6=red, 7=pink).

    Returns {page_id: [StrokeGroup]} for pages with matching strokes.
    """
    target_colors = {INDEX_COLOR_MAP[c] for c in colors if c in INDEX_COLOR_MAP}

    if not target_colors:
        return {}

    result: dict[str, list[StrokeGroup]] = {}

    for page in pages:
        groups = _group_strokes_by_color(page.lines, target_colors, page.page_id)
        if groups:
            result[page.page_id] = groups

    return result


# -- Internal helpers --


def _group_strokes_by_color(
    lines: list[Line], target_colors: set[PenColor], page_id: str
) -> list[StrokeGroup]:
    """Group strokes by color, only keeping those in target_colors."""
    groups_by_color: dict[PenColor, list[Line]] = {}

    for line in lines:
        if line.color in target_colors:
            groups_by_color.setdefault(line.color, []).append(line)

    result = []
    for color, color_lines in groups_by_color.items():
        bbox = _compute_bbox(color_lines)
        result.append(
            StrokeGroup(
                color=color,
                color_index=COLOR_INDEX_MAP.get(color, -1),
                lines=color_lines,
                bbox=bbox,
                page_id=page_id,
            )
        )

    return result


def _compute_bbox(lines: list[Line]) -> tuple[float, float, float, float]:
    """Compute the bounding box for a list of lines."""
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    for line in lines:
        for point in line.points:
            min_x = min(min_x, point.x)
            min_y = min(min_y, point.y)
            max_x = max(max_x, point.x)
            max_y = max(max_y, point.y)

    if min_x == float("inf"):
        return (0, 0, 0, 0)

    return (min_x, min_y, max_x, max_y)


def _find_rm_file(doc_dir: Path, doc_id: str, page_id: str) -> Path | None:
    """Locate the .rm file for a given page, trying common path patterns."""
    candidates = [
        doc_dir / f"{doc_id}" / f"{page_id}.rm",
        doc_dir / f"{page_id}.rm",
        doc_dir / doc_id / f"{page_id}.rm",
    ]

    for path in candidates:
        if path.exists():
            return path

    # Fallback: search recursively
    for rm_file in doc_dir.rglob(f"{page_id}.rm"):
        return rm_file

    return None
