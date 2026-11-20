"""Math / LaTeX auto-delimiter plugin.

Drops into ``~/.config/remark/plugins/`` (or wherever
``plugins.plugin_dir`` in your ``config.yaml`` points) and runs as a
``NoteProcessorHook``: whenever the engine finishes building a note it
looks for bare LaTeX fragments and wraps them in ``$...$`` so Obsidian
(and any Markdown renderer with MathJax/KaTeX) picks them up as math.

"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.plugins.hooks import NoteProcessorHook, PluginMetadata

logger = logging.getLogger(__name__)


# Commands and symbols that strongly suggest a LaTeX fragment. The list
# is deliberately conservative — false positives wrap normal prose in
# dollar signs, which is worse than missing a match.
_LATEX_MARKERS = [
    r"\\frac\{[^{}]+\}\{[^{}]+\}",            # \frac{a}{b}
    r"\\sqrt\{[^{}]+\}",                       # \sqrt{...}
    r"\\(sum|int|prod|oint|iint)_[^\s]+\^[^\s]+",  # \sum_{i=0}^{n}
    r"\\(alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|omega)\b",
    r"\\(mathbb|mathcal|mathbf|mathrm)\{[A-Za-z]+\}",
    r"\\begin\{equation\}[\s\S]+?\\end\{equation\}",
    r"\\begin\{align\*?\}[\s\S]+?\\end\{align\*?\}",
]

_LATEX_RE = re.compile("|".join(_LATEX_MARKERS))

# Skip matches that are already inside math delimiters or code blocks.
_FENCED_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_EXISTING_MATH_RE = re.compile(r"\$[^$\n]+\$|\$\$[\s\S]+?\$\$")


class MathLatexProcessor(NoteProcessorHook):
    """Wrap bare LaTeX fragments in $...$ so Obsidian renders them."""

    def __init__(self) -> None:
        self._wrap_inline = True
        self._wrap_block = True

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="math_latex",
            version="0.1.0",
            description="Auto-wraps bare LaTeX fragments in $...$ for Obsidian math rendering.",
            author="BGGBTAC",
        )

    def configure(self, settings: dict[str, Any]) -> None:
        self._wrap_inline = bool(settings.get("wrap_inline", True))
        self._wrap_block = bool(settings.get("wrap_block", True))

    async def process(
        self, content: str, frontmatter: dict,
    ) -> tuple[str, dict]:
        if not self._wrap_inline and not self._wrap_block:
            return content, frontmatter

        # Build a set of ranges we must not touch: existing math
        # delimiters, inline code, fenced code blocks.
        forbidden: list[tuple[int, int]] = []
        for pattern in (_FENCED_BLOCK_RE, _INLINE_CODE_RE, _EXISTING_MATH_RE):
            for m in pattern.finditer(content):
                forbidden.append(m.span())

        def _is_forbidden(start: int, end: int) -> bool:
            return any(
                fs <= start and end <= fe for fs, fe in forbidden
            )

        # Collect non-overlapping LaTeX matches in one pass, emit the
        # wrapped output in a single rebuild — string slicing keeps us
        # O(N) in content length.
        pieces: list[str] = []
        cursor = 0
        wrapped_count = 0
        for match in _LATEX_RE.finditer(content):
            start, end = match.span()
            if _is_forbidden(start, end):
                continue
            is_block = "\\begin" in match.group(0)
            if is_block and not self._wrap_block:
                continue
            if not is_block and not self._wrap_inline:
                continue
            pieces.append(content[cursor:start])
            if is_block:
                pieces.append(f"$$\n{match.group(0)}\n$$")
            else:
                pieces.append(f"${match.group(0)}$")
            cursor = end
            wrapped_count += 1

        if wrapped_count == 0:
            return content, frontmatter

        pieces.append(content[cursor:])
        new_content = "".join(pieces)
        frontmatter.setdefault("math_fragments", wrapped_count)
        logger.debug("math_latex: wrapped %d fragment(s)", wrapped_count)
        return new_content, frontmatter
