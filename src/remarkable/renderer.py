"""Render typed text and pen strokes together from a reMarkable scene."""

from __future__ import annotations

import math
from io import BytesIO

import cairocffi as cairo
from rmscene import CrdtId
from rmscene.scene_items import GlyphRange, Group, Line, ParagraphStyle, Pen, PenColor, Text
from rmscene.text import TextDocument

from src.remarkable.formats import PageContent

_PAGE_WIDTH = 1404
_PAGE_HEIGHT = 1872
_TOP_ANCHOR = CrdtId(0, (1 << 48) - 2)
_BOTTOM_ANCHOR = CrdtId(0, (1 << 48) - 1)
_COLORS = {
    PenColor.GRAY: (0.5, 0.5, 0.5),
    PenColor.WHITE: (1, 1, 1),
    PenColor.YELLOW: (0.8, 0.8, 0),
    PenColor.GREEN: (0, 0.65, 0),
    PenColor.BLUE: (0, 0, 1),
    PenColor.RED: (1, 0, 0),
    PenColor.PINK: (1, 0.41, 0.71),
}
_LIST_MARKERS = {
    "BULLET": "• ",
    "BULLET2": "◦ ",
    "CHECKBOX": "☐ ",
    "CHECKBOX_CHECKED": "☑ ",
}


def render_page_to_png(page: PageContent, scale: float = 1.0) -> bytes:
    """Render a whole page, extending the canvas to include off-screen ink."""
    size = getattr(getattr(page.tree, "scene_info", None), "paper_size", None)
    width, height = size or (_PAGE_WIDTH, _PAGE_HEIGHT)
    recording = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
    drawing = cairo.Context(recording)
    anchors = _draw_text(drawing, page.tree.root_text, height)
    _draw_group(drawing, page.tree.root, anchors, page.tree.root_text is None)

    ink_x, ink_y, ink_width, ink_height = recording.ink_extents()
    left = min(-width / 2, ink_x)
    top = min(0, ink_y)
    width = max(width / 2, ink_x + ink_width) - left
    height = max(height, ink_y + ink_height) - top
    scale = min(scale, 4096 / max(width, height))
    surface = cairo.ImageSurface(
        cairo.FORMAT_RGB24, math.ceil(width * scale), math.ceil(height * scale)
    )
    output = cairo.Context(surface)
    output.set_source_rgb(1, 1, 1)
    output.paint()
    output.scale(scale, scale)
    output.set_source_surface(recording, -left, -top)
    output.paint()

    png = BytesIO()
    surface.write_to_png(png)
    return png.getvalue()


def _draw_text(drawing: cairo.Context, text: Text | None, height: float) -> dict[CrdtId, float]:
    if text is None:
        return {_TOP_ANCHOR: 0, _BOTTOM_ANCHOR: height}

    # Notebook text metrics in stroke coordinates.
    # See https://github.com/SamMorrowDrums/remarkable-mcp/pull/116
    scale = height / _PAGE_HEIGHT
    y = text.pos_y - 39 * scale
    anchors = {_TOP_ANCHOR: y}
    drawing.set_source_rgb(0, 0, 0)
    for paragraph in TextDocument.from_scene_item(text).contents:
        anchors[paragraph.start_id] = y
        for span in paragraph.contents:
            anchors.update(dict.fromkeys(span.i, y))

        style = paragraph.style.value
        heading = style == ParagraphStyle.HEADING
        font_size = (44 if heading else 30) * scale
        weight = cairo.FONT_WEIGHT_BOLD if heading or style == ParagraphStyle.BOLD else 0
        drawing.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, weight)
        drawing.set_font_size(font_size)
        x = text.pos_x + (30 * scale if style == ParagraphStyle.BULLET2 else 0)
        line_height = max(44 * scale, font_size * 1.25)
        margin = 70 * scale
        if heading:
            margin = 110 * scale
        value = str(paragraph)
        if value:
            label = _LIST_MARKERS.get(style.name, "") + value
            for row, line in enumerate(_wrap_lines(drawing, label, text.width - (x - text.pos_x))):
                drawing.move_to(x, y + margin + row * line_height)
                drawing.show_text(line)
            y += row * line_height
        y += margin

    anchors[_BOTTOM_ANCHOR] = y
    return anchors


def _wrap_lines(drawing: cairo.Context, text: str, width: float) -> list[str]:
    lines = []
    current = ""
    for word in text.expandtabs(4).split(" "):
        joined = f"{current} {word}" if current else word
        if current and drawing.text_extents(joined)[4] > width:
            lines.append(current)
            current = word
        else:
            current = joined
    lines.append(current)
    return lines


def _draw_group(
    drawing: cairo.Context, group: Group, anchors: dict[CrdtId, float], draw_glyph_text: bool
) -> None:
    if not group.visible.value:
        return
    with drawing:
        if group.anchor_id is not None:
            x = group.anchor_origin_x.value if group.anchor_origin_x is not None else 0
            drawing.translate(x, anchors.get(group.anchor_id.value, 0))
        for item in group.children.values():
            if isinstance(item, Group):
                _draw_group(drawing, item, anchors, draw_glyph_text)
            elif isinstance(item, Line):
                _draw_stroke(drawing, item)
            elif isinstance(item, GlyphRange):
                _draw_highlight(drawing, item, draw_glyph_text)


def _draw_stroke(drawing: cairo.Context, line: Line) -> None:
    if not line.points or line.tool in (Pen.ERASER, Pen.ERASER_AREA):
        return
    rgb = _COLORS.get(line.color, (0, 0, 0))
    rgba = getattr(line, "color_rgba", None)
    highlight = line.tool in (Pen.HIGHLIGHTER_1, Pen.HIGHLIGHTER_2)
    if rgba:
        rgb = tuple(value / 255 for value in rgba[:3])
    drawing.set_source_rgba(*rgb, 0.35 if highlight else 1)
    drawing.set_line_width(max(line.thickness_scale * 2, 1))
    drawing.set_line_cap(cairo.LINE_CAP_ROUND)
    drawing.set_line_join(cairo.LINE_JOIN_ROUND)
    drawing.move_to(line.points[0].x, line.points[0].y)
    for point in line.points:
        drawing.line_to(point.x, point.y)
    drawing.stroke()


def _draw_highlight(drawing: cairo.Context, glyph: GlyphRange, draw_text: bool) -> None:
    drawing.set_source_rgba(*_COLORS.get(glyph.color, (1, 1, 0)), 0.35)
    for rect in glyph.rectangles:
        drawing.rectangle(rect.x, rect.y, rect.w, rect.h)
        drawing.fill()
    if draw_text and glyph.rectangles:
        rect = glyph.rectangles[0]
        drawing.set_source_rgb(0, 0, 0)
        drawing.set_font_size(rect.h * 0.75)
        drawing.move_to(rect.x, rect.y + rect.h * 0.8)
        drawing.show_text(glyph.text.replace("\n", " "))
