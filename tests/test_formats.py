"""Tests for .rm file format parsing and document handling."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from rmscene import simple_text_document, write_blocks
from rmscene.scene_items import PenColor
from rmscene.text import TextDocument

from src.remarkable.documents import DocumentManager
from src.remarkable.formats import (
    COLOR_INDEX_MAP,
    INDEX_COLOR_MAP,
    Notebook,
    PageContent,
    parse_notebook,
    parse_rm_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


# -- Helpers --


def create_rm_fixture(path: Path, text: str) -> Path:
    """Create a .rm file with the given text content."""
    blocks = list(simple_text_document(text))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        write_blocks(f, blocks)
    return path


def typed_lines(page: PageContent) -> list[str]:
    text = page.tree.root_text
    return [str(paragraph) for paragraph in TextDocument.from_scene_item(text).contents] if text else []


def create_content_file(doc_dir: Path, doc_id: str, page_ids: list[str]) -> None:
    """Create a .content JSON file for a document."""
    content = {"cPages": {"pages": [{"id": pid} for pid in page_ids]}}
    (doc_dir / f"{doc_id}.content").write_text(json.dumps(content))


def create_metadata_file(doc_dir: Path, doc_id: str, name: str) -> None:
    """Create a .metadata JSON file for a document."""
    meta = {"visibleName": name, "type": "DocumentType"}
    (doc_dir / f"{doc_id}.metadata").write_text(json.dumps(meta))


# -- parse_rm_file --


class TestParseRmFile:
    def test_parse_text_content(self):
        page = parse_rm_file(FIXTURES / "test-page-001.rm")

        assert not page.lines
        assert "Meeting Notes" in typed_lines(page)
        assert "TODO: send report to team" in typed_lines(page)

    def test_parse_text_preserves_lines(self):
        page = parse_rm_file(FIXTURES / "test-page-001.rm")
        lines = typed_lines(page)
        assert len(lines) == 4
        assert lines[0] == "Meeting Notes"
        assert lines[3] == "Q: What is the deadline?"

    def test_parse_generated_fixture(self, tmp_path):
        rm_path = create_rm_fixture(
            tmp_path / "page-abc.rm",
            "Hello World\nThis is a test",
        )
        page = parse_rm_file(rm_path)

        assert page.page_id == "page-abc"
        assert typed_lines(page) == ["Hello World", "This is a test"]

    def test_parse_empty_text(self, tmp_path):
        rm_path = create_rm_fixture(tmp_path / "empty.rm", "")
        page = parse_rm_file(rm_path)
        assert not any(typed_lines(page))

    def test_page_id_from_filename(self):
        page = parse_rm_file(FIXTURES / "test-page-001.rm")
        assert page.page_id == "test-page-001"


# -- parse_notebook --


class TestParseNotebook:
    def test_parse_multipage_notebook(self, tmp_path):
        doc_id = "doc-123"
        doc_dir = tmp_path / doc_id
        doc_dir.mkdir()

        page_ids = ["page-a", "page-b", "page-c"]

        # Create .rm files for each page
        for i, pid in enumerate(page_ids):
            create_rm_fixture(
                doc_dir / f"{pid}.rm",
                f"Page {i + 1} content\nSome notes here",
            )

        pages = parse_notebook(doc_dir, doc_id, page_ids)

        assert len(pages) == 3
        assert [typed_lines(page)[0] for page in pages] == [
            "Page 1 content", "Page 2 content", "Page 3 content"
        ]

    def test_missing_page_returns_empty(self, tmp_path):
        doc_dir = tmp_path / "doc-456"
        doc_dir.mkdir()

        pages = parse_notebook(doc_dir, "doc-456", ["nonexistent-page"])

        assert len(pages) == 1
        assert not typed_lines(pages[0])
        assert not pages[0].lines

    def test_corrupt_page_raises_instead_of_appearing_blank(self, tmp_path):
        (tmp_path / "page-a.rm").write_bytes(b"invalid reMarkable page")
        with pytest.raises(ValueError, match="Failed to parse reMarkable page page-a"):
            parse_notebook(tmp_path, "doc", ["page-a"])


# -- Color mapping --


class TestColorMapping:
    def test_color_index_map_covers_basic_colors(self):
        assert COLOR_INDEX_MAP[PenColor.BLACK] == 0
        assert COLOR_INDEX_MAP[PenColor.RED] == 6
        assert COLOR_INDEX_MAP[PenColor.BLUE] == 5
        assert COLOR_INDEX_MAP[PenColor.YELLOW] == 3

    def test_index_color_roundtrip(self):
        for color, index in COLOR_INDEX_MAP.items():
            assert INDEX_COLOR_MAP[index] == color


# -- DocumentManager --


class TestDocumentManager:
    @pytest.mark.asyncio
    async def test_list_documents_filters_by_folder(self, tmp_path):
        from src.remarkable.cloud import DocumentMetadata

        mock_cloud = AsyncMock()
        mock_cloud.list_items = AsyncMock(
            return_value=[
                DocumentMetadata(
                    id="f1",
                    name="Work",
                    parent="",
                    doc_type="CollectionType",
                    version=1,
                    hash="a",
                    modified="",
                ),
                DocumentMetadata(
                    id="f2",
                    name="Trash",
                    parent="",
                    doc_type="CollectionType",
                    version=1,
                    hash="b",
                    modified="",
                ),
                DocumentMetadata(
                    id="d1",
                    name="Note 1",
                    parent="f1",
                    doc_type="DocumentType",
                    version=1,
                    hash="c",
                    modified="",
                ),
                DocumentMetadata(
                    id="d2",
                    name="Note 2",
                    parent="f2",
                    doc_type="DocumentType",
                    version=1,
                    hash="d",
                    modified="",
                ),
                DocumentMetadata(
                    id="d3",
                    name="Note 3",
                    parent="f1",
                    doc_type="DocumentType",
                    version=1,
                    hash="e",
                    modified="",
                ),
            ]
        )

        mgr = DocumentManager(mock_cloud, tmp_path)
        docs = await mgr.list_documents(sync_folders=["Work"], ignore_folders=["Trash"])

        names = [d.name for d in docs]
        assert "Note 1" in names
        assert "Note 3" in names
        assert "Note 2" not in names

    def test_read_page_ids_cpages_format(self, tmp_path):

        doc_id = "doc-pages"
        doc_dir = tmp_path / doc_id
        doc_dir.mkdir()

        content = {"cPages": {"pages": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]}}
        (doc_dir / f"{doc_id}.content").write_text(json.dumps(content))

        mgr = DocumentManager(MagicMock(), tmp_path)
        page_ids = mgr._read_page_ids(doc_dir, doc_id)

        assert page_ids == ["p1", "p2", "p3"]

    def test_read_page_ids_legacy_format(self, tmp_path):
        doc_id = "doc-legacy"
        doc_dir = tmp_path / doc_id
        doc_dir.mkdir()

        content = {"pages": ["page-a", "page-b"]}
        (doc_dir / f"{doc_id}.content").write_text(json.dumps(content))

        mgr = DocumentManager(MagicMock(), tmp_path)
        page_ids = mgr._read_page_ids(doc_dir, doc_id)

        assert page_ids == ["page-a", "page-b"]

    def test_read_doc_name(self, tmp_path):
        doc_id = "doc-meta"
        doc_dir = tmp_path / doc_id
        doc_dir.mkdir()

        meta = {"visibleName": "My Important Notes"}
        (doc_dir / f"{doc_id}.metadata").write_text(json.dumps(meta))

        mgr = DocumentManager(MagicMock(), tmp_path)
        name = mgr._read_doc_name(doc_dir, doc_id)

        assert name == "My Important Notes"

    def test_read_doc_name_missing(self, tmp_path):
        mgr = DocumentManager(MagicMock(), tmp_path)
        name = mgr._read_doc_name(tmp_path / "no-dir", "no-doc")
        assert name is None


# -- Notebook dataclass --


class TestNotebook:
    def test_page_count_includes_blank_pages(self):
        pages = [PageContent(page_id="p1"), PageContent(page_id="p2")]

        nb = Notebook(id="nb1", name="Test", folder="", modified="", pages=pages)

        assert nb.page_count == 2

    def test_empty_notebook(self):
        nb = Notebook(id="nb2", name="Empty", folder="", modified="", pages=[])
        assert nb.page_count == 0
