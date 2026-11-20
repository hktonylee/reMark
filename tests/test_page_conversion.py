import asyncio
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
from rmscene import (
    CrdtId,
    CrdtSequenceItem,
    LwwValue,
    SceneLineItemBlock,
    simple_text_document,
    write_blocks,
)
from rmscene.scene_items import (
    GlyphRange,
    Group,
    Line,
    ParagraphStyle,
    Pen,
    PenColor,
    Point,
    Rectangle,
)

from src.processing.codex import convert_page
from src.remarkable.formats import PageContent, parse_rm_file
from src.remarkable.renderer import render_page_to_png

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><circle cx="10" cy="10" r="8"/></svg>'


def write_page(path, typed="", ink=False):
    blocks = list(simple_text_document(typed))
    if ink:
        blocks.append(
            SceneLineItemBlock(
                parent_id=CrdtId(0, 11),
                item=CrdtSequenceItem(
                    item_id=CrdtId(1, 100),
                    left_id=CrdtId(0, 0),
                    right_id=CrdtId(0, 0),
                    deleted_length=0,
                    value=Line(
                        color=PenColor.BLUE,
                        tool=Pen.BALLPOINT_1,
                        points=[
                            Point(-500, 600, 0, 0, 4, 128),
                            Point(-400, 600, 0, 0, 4, 128),
                            Point(-450, 500, 0, 0, 4, 128),
                            Point(-500, 600, 0, 0, 4, 128),
                        ],
                        thickness_scale=2.0,
                        starting_length=0,
                    ),
                ),
            ),
        )
    with path.open("wb") as output:
        write_blocks(output, blocks)


@pytest.mark.parametrize(
    ("typed", "ink"), [("Typed & <text>", True), ("Typed only", False), ("", True), ("", False)]
)
def test_render_typed_text_and_ink_on_one_page(tmp_path, typed, ink):
    path = tmp_path / "source.rm"
    write_page(path, typed, ink)

    png = render_page_to_png(parse_rm_file(path))
    with Image.open(BytesIO(png)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
        colors = image.crop((150, 175, 850, 320)).getcolors(100_000)
        assert any(r == g == b and r < 100 for _, (r, g, b) in colors) == bool(typed)
        assert (image.getpixel((250, 600)) == (0, 0, 255)) == ink


@pytest.mark.parametrize("offset", [None, 40])
def test_render_moves_ink_with_its_text_anchor(tmp_path, offset):
    path = tmp_path / "anchored.rm"
    write_page(path, "Typed heading", ink=True)
    page = parse_rm_file(path)
    (layer,) = page.tree.root.children.values()
    assert isinstance(layer, Group)
    anchor = CrdtId(0, 0)  # First typed paragraph
    layer.anchor_id = LwwValue(anchor, anchor)
    if offset is not None:
        layer.anchor_origin_x = LwwValue(anchor, offset)

    with Image.open(BytesIO(render_page_to_png(page))) as image:
        assert image.getpixel((250, 600)) == (255, 255, 255)
        assert image.getpixel((250 + (offset or 0), 795)) == (0, 0, 255)


def test_render_wraps_typed_text_and_preserves_extended_ink(tmp_path):
    path = tmp_path / "long.rm"
    write_page(path, "Heading wraps here\n\nNext paragraph", ink=True)
    page = parse_rm_file(path)
    text = page.tree.root_text
    assert text is not None
    text.width = 185
    anchor = CrdtId(0, 0)
    text.styles[anchor] = LwwValue(anchor, ParagraphStyle.HEADING)
    for point in page.lines[0].points:
        point.y += 1500

    with Image.open(BytesIO(render_page_to_png(page))) as image:
        assert image.height > 2100
        assert image.getpixel((250, 2100)) == (0, 0, 255)
        assert image.crop((150, 321, 420, 420)).convert("L").getextrema() == (0, 255)


@pytest.mark.parametrize("change", ["eraser", "empty", "hidden"])
def test_render_ignores_erased_empty_or_hidden_ink(tmp_path, change):
    path = tmp_path / "hidden.rm"
    write_page(path, ink=True)
    page = parse_rm_file(path)
    if change == "eraser":
        page.lines[0].tool = Pen.ERASER
    elif change == "empty":
        page.lines[0].points.clear()
    else:
        (layer,) = page.tree.root.children.values()
        layer.visible = LwwValue(CrdtId(0, 0), False)

    with Image.open(BytesIO(render_page_to_png(page))) as image:
        assert image.getpixel((250, 600)) == (255, 255, 255)


@pytest.mark.parametrize("typed", [False, True])
def test_render_preserves_text_from_highlights_without_a_typed_block(tmp_path, typed):
    path = tmp_path / "glyph.rm"
    write_page(path, "Typed text" if typed else "")
    page = parse_rm_file(path)
    if not typed:
        page.tree.root_text = None
    glyph = GlyphRange(
        start=None,
        length=14,
        text="Important text",
        color=PenColor.YELLOW,
        rectangles=[Rectangle(-402, 500, 400, 40)],
    )
    page.tree.root.children.add(
        CrdtSequenceItem(CrdtId(1, 1), CrdtId(0, 0), CrdtId(0, 0), 0, glyph)
    )

    with Image.open(BytesIO(render_page_to_png(page))) as image:
        assert image.getpixel((600, 530)) != (255, 255, 255)
        assert (image.crop((300, 500, 600, 540)).convert("L").getextrema()[0] == 0) == (not typed)


def test_render_uses_true_highlighter_color(tmp_path):
    path = tmp_path / "highlight-ink.rm"
    write_page(path, ink=True)
    page = parse_rm_file(path)
    line = page.lines[0]
    line.tool = Pen.HIGHLIGHTER_1
    line.color_rgba = (255, 0, 0, 255)

    with Image.open(BytesIO(render_page_to_png(page))) as image:
        r, g, b = image.getpixel((250, 600))
        assert r == 255 and g == b and 0 < g < 255


def test_render_ignores_tombstones():
    page = PageContent("erased")
    page.tree.root.children.add(CrdtSequenceItem(CrdtId(1, 1), CrdtId(0, 0), CrdtId(0, 0), 1, None))

    with Image.open(BytesIO(render_page_to_png(page))) as image:
        assert image.convert("L").getextrema() == (255, 255)


@pytest.mark.parametrize("markdown", [f"# Page\n\n{SVG}", ""])
async def test_codex_gets_one_image_and_returns_its_final_markdown(tmp_path, monkeypatch, markdown):
    path = tmp_path / "source.rm"
    write_page(path, "Typed text", ink=True)
    page = parse_rm_file(path)
    workspaces = []

    async def exec_codex(*args, **kwargs):
        assert args[:2] == ("codex", "exec")
        image_file = Path(args[args.index("--image") + 1])
        output_file = Path(args[args.index("--output-last-message") + 1])
        schema_file = Path(args[args.index("--output-schema") + 1])
        assert image_file.read_bytes().startswith(b"\x89PNG\r\n")
        assert json.loads(schema_file.read_text())["required"] == ["markdown"]
        assert "inline SVG" in args[-1]
        assert image_file.parent == output_file.parent == Path(kwargs["cwd"])
        workspaces.append(image_file.parent)
        output_file.write_text(json.dumps({"markdown": markdown}))
        return AsyncMock(wait=AsyncMock(return_value=0))

    monkeypatch.setattr("src.processing.codex.asyncio.create_subprocess_exec", exec_codex)

    assert await convert_page(page) == markdown
    assert len(workspaces) == 1
    assert not workspaces[0].exists()


@pytest.mark.parametrize(
    ("status", "result", "error", "message"),
    [
        (1, None, RuntimeError, "Codex failed on page source"),
        (0, None, ValueError, "invalid output for page source"),
        (0, "{", ValueError, "invalid output for page source"),
        (0, "{}", ValueError, "invalid output for page source"),
        (0, '{"markdown": 42}', ValueError, "invalid Markdown for page source"),
    ],
)
async def test_conversion_errors_surface(tmp_path, monkeypatch, status, result, error, message):
    path = tmp_path / "source.rm"
    write_page(path)

    async def exec_codex(*args, **kwargs):
        if result is not None:
            output = Path(args[args.index("--output-last-message") + 1])
            output.write_text(result)
        return AsyncMock(wait=AsyncMock(return_value=status))

    monkeypatch.setattr("src.processing.codex.asyncio.create_subprocess_exec", exec_codex)
    with pytest.raises(error, match=message):
        await convert_page(parse_rm_file(path))


async def test_missing_codex_prompts_for_install(tmp_path, monkeypatch):
    path = tmp_path / "source.rm"
    write_page(path)
    monkeypatch.setattr(
        "src.processing.codex.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError),
    )

    with pytest.raises(RuntimeError, match="Codex CLI is missing from PATH"):
        await convert_page(parse_rm_file(path))


@pytest.mark.parametrize(
    ("cancel", "returncode", "os_name"),
    [(False, None, "posix"), (True, None, "nt"), (True, 0, "posix")],
)
async def test_interrupted_conversion_stops_codex(tmp_path, monkeypatch, cancel, returncode, os_name):
    path = tmp_path / "source.rm"
    write_page(path)
    wait_error = asyncio.CancelledError if cancel else TimeoutError
    process = Mock(pid=12345, returncode=returncode, wait=AsyncMock(side_effect=[wait_error, 0]))
    monkeypatch.setattr(
        "src.processing.codex.asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )
    kill = Mock()
    monkeypatch.setattr("src.processing.codex.os", SimpleNamespace(name=os_name, killpg=kill))
    process.kill = kill

    expected = asyncio.CancelledError if cancel else RuntimeError
    with pytest.raises(expected):
        await convert_page(parse_rm_file(path))

    assert kill.call_count == (returncode is None)
    assert process.wait.await_count == 2
