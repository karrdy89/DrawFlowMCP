"""Tiny Markdown subset used inside details PNG cards.

Supports headings, bullets, ordered lists, blockquotes, fenced code, and a
handful of inline marks (bold, italic, inline code, link text). HTML and
remote images are intentionally not supported.
"""
from __future__ import annotations

import re

from PIL import ImageDraw, ImageFont

from . import text as textlib
from .theme import Color, PALETTE, scaled_font


def s(value: int | float, scale: int) -> int:
    return max(1, int(round(float(value) * scale)))


def clean_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def blocks(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    in_code = False
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(("paragraph", clean_inline(" ".join(paragraph))))
            paragraph.clear()

    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            in_code = not in_code
            out.append(("code_fence", ""))
            continue
        if in_code:
            out.append(("code", line))
            continue
        if not stripped:
            flush()
            out.append(("gap", ""))
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            flush()
            out.append((f"h{len(heading.group(1))}", clean_inline(heading.group(2))))
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            flush()
            out.append(("bullet", clean_inline(bullet.group(1))))
            continue
        ordered = re.match(r"^(\d+)[.)]\s+(.+)$", stripped)
        if ordered:
            flush()
            out.append(("bullet", f"{ordered.group(1)}. {clean_inline(ordered.group(2))}"))
            continue
        quote = re.match(r"^>\s?(.+)$", stripped)
        if quote:
            flush()
            out.append(("quote", clean_inline(quote.group(1))))
            continue
        paragraph.append(stripped)
    flush()
    return out


def block_font(block_type: str, scale: int) -> ImageFont.ImageFont:
    if block_type == "h1":
        return scaled_font(18, scale, bold=True)
    if block_type == "h2":
        return scaled_font(16, scale, bold=True)
    if block_type == "h3":
        return scaled_font(15, scale, bold=True)
    if block_type == "code":
        return scaled_font(13, scale)
    return scaled_font(14, scale)


def measure_height(draw: ImageDraw.ImageDraw, text: str, max_width: int, scale: int) -> int:
    height = 0
    for block_type, body in blocks(text):
        if block_type == "gap":
            height += s(9, scale)
            continue
        if block_type == "code_fence":
            height += s(4, scale)
            continue
        font = block_font(block_type, scale)
        left_pad = s(24, scale) if block_type in {"bullet", "quote"} else 0
        available = max(20, max_width - left_pad)
        lines = textlib.wrap(draw, body, font, available) or [""]
        line_height = textlib.text_size(draw, "Ag", font)[1] + s(6, scale)
        if block_type == "code":
            height += len(lines) * line_height + s(17, scale)
            continue
        height += len(lines) * line_height + s(5, scale)
    return height


def draw_markdown(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    max_width: int,
    scale: int,
    fill: Color,
) -> int:
    for block_type, body in blocks(text):
        if block_type == "gap":
            y += s(9, scale)
            continue
        if block_type == "code_fence":
            y += s(4, scale)
            continue
        font = block_font(block_type, scale)
        line_height = textlib.text_size(draw, "Ag", font)[1] + s(6, scale)
        block_fill = fill
        block_x = x
        available = max_width
        prefix = ""
        if block_type == "bullet":
            prefix = "- "
            block_x = x + s(20, scale)
            available = max_width - s(24, scale)
        elif block_type == "quote":
            draw.line((x, y, x, y + line_height), fill=PALETTE["container_border"], width=s(3, scale))
            block_x = x + s(16, scale)
            available = max_width - s(20, scale)
            block_fill = PALETTE["muted"]
        elif block_type == "code":
            block_fill = PALETTE["ink"]
            code_lines = textlib.wrap(draw, body, font, max_width - s(20, scale)) or [""]
            code_height = len(code_lines) * line_height + s(12, scale)
            draw.rounded_rectangle((x, y, x + max_width, y + code_height), radius=s(8, scale), fill=(226, 232, 240))
            code_y = y + s(6, scale)
            for line in code_lines:
                draw.text((x + s(10, scale), code_y), line, font=font, fill=block_fill)
                code_y += line_height
            y += code_height + s(5, scale)
            continue
        elif block_type.startswith("h"):
            block_fill = PALETTE["ink"]
        for index, line in enumerate(textlib.wrap(draw, body, font, available) or [""]):
            if prefix and index == 0:
                draw.text((x, y), prefix, font=font, fill=block_fill)
            draw.text((block_x, y), line, font=font, fill=block_fill)
            y += line_height
        y += s(5, scale)
    return y
