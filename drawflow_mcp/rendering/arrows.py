"""Arrowheads + dashed/dotted polyline drawing."""
from __future__ import annotations

import math
from typing import Any

from PIL import ImageDraw

from .geometry import Point, s
from .theme import Color


def draw_arrow_head(
    draw: ImageDraw.ImageDraw,
    end: Point,
    prev: Point,
    shape: str,
    fill_shape: bool,
    color: Color,
    size: int = 14,
    background: Color = (255, 255, 255),
) -> None:
    if shape == "none":
        return
    width = max(1, size // 5)
    if shape == "open":
        head = _classic_head(end, prev, size)
        draw.line((head[0][0], head[0][1], head[1][0], head[1][1]), fill=color, width=width)
        draw.line((head[0][0], head[0][1], head[2][0], head[2][1]), fill=color, width=width)
        return
    if shape == "diamond":
        diamond = _diamond_head(end, prev, size)
        draw.polygon(diamond, fill=color if fill_shape else background, outline=color)
        return
    if shape == "oval":
        ex, ey = end
        radius = max(3, int(size * 0.58))
        draw.ellipse((ex - radius, ey - radius, ex + radius, ey + radius), fill=color if fill_shape else background, outline=color, width=width)
        return
    head = _classic_head(end, prev, size)
    draw.polygon(head, fill=color if fill_shape else background, outline=color)


def draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[Point],
    color: Color,
    width: int,
    line_style: str,
    scale: int,
) -> None:
    if line_style == "solid":
        try:
            draw.line(points, fill=color, width=width, joint="curve")
            return
        except TypeError:
            pass
    for a, b in zip(points, points[1:]):
        if line_style == "dotted":
            _dotted(draw, a, b, color, width, scale)
        elif line_style == "dashed":
            _dashed(draw, a, b, color, width, scale)
        else:
            draw.line((a[0], a[1], b[0], b[1]), fill=color, width=width)


def hex_to_color(value: str | None) -> Color | None:
    if not value:
        return None
    text = value.lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def edge_style(edge: dict[str, Any], scale: int, defaults: dict[str, object]) -> tuple[Color, str, int]:
    explicit = edge.get("style") or {}
    color = hex_to_color(explicit.get("strokeColor")) or defaults["color"]
    line_style = explicit.get("lineStyle") or defaults["line"]
    width_value = explicit.get("strokeWidth") or defaults["width"]
    return color, str(line_style), s(float(width_value), scale)


def _classic_head(end: Point, prev: Point, size: int) -> list[Point]:
    ex, ey = end
    px, py = prev
    angle = math.atan2(ey - py, ex - px)
    left = angle + math.pi * 0.82
    right = angle - math.pi * 0.82
    return [
        (ex, ey),
        (ex + math.cos(left) * size, ey + math.sin(left) * size),
        (ex + math.cos(right) * size, ey + math.sin(right) * size),
    ]


def _diamond_head(end: Point, prev: Point, size: int) -> list[Point]:
    ex, ey = end
    px, py = prev
    angle = math.atan2(ey - py, ex - px)
    ux = math.cos(angle)
    uy = math.sin(angle)
    nx, ny = -uy, ux
    return [
        (ex, ey),
        (ex - ux * size + nx * size * 0.55, ey - uy * size + ny * size * 0.55),
        (ex - ux * size * 2, ey - uy * size * 2),
        (ex - ux * size - nx * size * 0.55, ey - uy * size - ny * size * 0.55),
    ]


def _dashed(draw: ImageDraw.ImageDraw, start: Point, end: Point, color: Color, width: int, scale: int) -> None:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    dash = s(16, scale)
    gap = s(10, scale)
    ux = dx / length
    uy = dy / length
    distance = 0.0
    while distance < length:
        seg_end = min(distance + dash, length)
        draw.line(
            (sx + ux * distance, sy + uy * distance, sx + ux * seg_end, sy + uy * seg_end),
            fill=color,
            width=width,
        )
        distance += dash + gap


def _dotted(draw: ImageDraw.ImageDraw, start: Point, end: Point, color: Color, width: int, scale: int) -> None:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    step = s(13, scale)
    radius = max(1, width // 2)
    ux = dx / length
    uy = dy / length
    distance = 0.0
    while distance <= length:
        cx = sx + ux * distance
        cy = sy + uy * distance
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
        distance += step
