"""Text wrapping + centered drawing primitives."""
from __future__ import annotations

from PIL import ImageDraw, ImageFont

from .theme import Color


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    for raw_line in str(text).splitlines():
        words = raw_line.split(" ")
        if len(words) == 1:
            lines.extend(_wrap_unspaced(draw, raw_line, font, max_width))
            continue
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if text_size(draw, candidate, font)[0] <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            if text_size(draw, word, font)[0] <= max_width:
                current = word
            else:
                wrapped = _wrap_unspaced(draw, word, font, max_width)
                lines.extend(wrapped[:-1])
                current = wrapped[-1] if wrapped else ""
        if current:
            lines.append(current)
    return lines


def _wrap_unspaced(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = f"{current}{char}"
        if text_size(draw, candidate, font)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def ellipsize(text: str, max_chars: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(1, max_chars - 1)].rstrip() + "..."


def draw_centered_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Color,
) -> None:
    if not text:
        return
    text_box = draw.textbbox((0, 0), text, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    x = box[0] + ((box[2] - box[0]) - text_w) / 2 - text_box[0]
    y = box[1] + ((box[3] - box[1]) - text_h) / 2 - text_box[1]
    draw.text((x, y), text, font=font, fill=fill)


def draw_wrapped_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Color,
    max_lines: int = 2,
    line_gap: int = 6,
) -> None:
    x1, y1, x2, y2 = box
    lines = wrap(draw, text, font, max(10, x2 - x1 - 18))[:max_lines]
    if not lines:
        return
    line_height = max(text_size(draw, line, font)[1] for line in lines) + line_gap
    total = line_height * len(lines)
    y = y1 + ((y2 - y1) - total) / 2
    for line in lines:
        width, _ = text_size(draw, line, font)
        draw.text((x1 + ((x2 - x1) - width) / 2, y), line, font=font, fill=fill)
        y += line_height


def draw_wrapped_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    max_width: int,
    font: ImageFont.ImageFont,
    fill: Color,
    line_gap: int = 6,
) -> int:
    line_height = text_size(draw, "Ag", font)[1] + line_gap
    for line in wrap(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y
