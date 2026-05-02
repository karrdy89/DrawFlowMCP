"""Node shape drawing.

Each ``kind`` has its own painter. Shapes share a small helper set
(``_node_label``, ``_external_ref_anchor``, ``_box``, ``_s``, ``_shade``)
so kind-specific code only has to express the *outline* of the shape.

``intrinsic_size(node)`` returns the size we expect the layout to use for
this node before grandalf rounds anything. ``intersect_outline(node, target)``
computes the boundary point on the node's actual outline closest to a
target point — used by the edge router to land arrowheads on the visible
silhouette instead of inside a bbox.
"""
from __future__ import annotations

import math
from typing import Any

from PIL import ImageDraw

from . import text as textlib
from .geometry import Point, line_ellipse_intersection, line_polygon_intersection
from .theme import (
    PALETTE,
    Color,
    node_fill,
    scaled_font,
)


def intrinsic_size(node: dict[str, Any]) -> tuple[int, int]:
    label_len = len(str(node.get("label", "")))
    summary_len = len(str(node.get("summary", "")))
    width = min(260, max(148, 96 + max(label_len, min(summary_len, 24)) * 8))
    height = 98 if summary_len else 84
    kind = node.get("kind")
    if kind == "decision":
        return max(width, 156), max(height, 110)
    if kind == "actor":
        return max(width, 132), max(height, 92)
    if kind == "document":
        return max(width, 148), max(height, 90)
    if kind == "database":
        return max(width, 148), max(height, 100)
    if kind == "gateway":
        return max(width, 158), max(height, 90)
    return width, height


def draw_node(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    kind = str(node.get("kind", "service"))
    drawer = _SHAPE_DRAWERS.get(kind, _draw_service)
    drawer(draw, node, scale)


# ---------------------------------------------------------------------------
# Shape painters
# ---------------------------------------------------------------------------


def _draw_container(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    draw.rounded_rectangle(
        (x, y, x + w, y + h),
        radius=_s(22, scale),
        fill=PALETTE["container_fill"],
        outline=PALETTE["container_border"],
        width=_s(2, scale),
    )
    label_x = x + _s(18, scale)
    if node.get("ref"):
        badge = (x + _s(14, scale), y + _s(12, scale), x + _s(46, scale), y + _s(31, scale))
        draw.rounded_rectangle(badge, radius=_s(7, scale), fill=PALETTE["container_ref_badge"])
        textlib.draw_centered_box(draw, badge, str(node["ref"]), scaled_font(10, scale, bold=True), PALETTE["ref_badge_text"])
        label_x = x + _s(54, scale)
    draw.text((label_x, y + _s(11, scale)), str(node["label"]), font=scaled_font(16, scale, bold=True), fill=PALETTE["container_label"])
    if node.get("summary"):
        summary = textlib.ellipsize(str(node["summary"]), 54)
        draw.text((label_x, y + _s(35, scale)), summary, font=scaled_font(12, scale), fill=PALETTE["muted"])


def _draw_service(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    fill = node_fill(str(node.get("kind", "service")))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=_s(16, scale), fill=fill, outline=PALETTE["border"], width=_s(2, scale))
    _node_label(draw, node, (x, y, x + w, y + h), scale)


def _draw_external(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    fill = node_fill("external")
    border = PALETTE["border"]
    draw.rounded_rectangle((x, y, x + w, y + h), radius=_s(18, scale), fill=fill, outline=border, width=_s(2, scale))
    size = _s(14, scale)
    pad = _s(8, scale)
    points = [(x + w - pad - size, y + pad), (x + w - pad, y + pad), (x + w - pad, y + pad + size)]
    draw.polygon(points, fill=border)
    _node_label(draw, node, (x, y, x + w, y + h), scale)


def _draw_decision(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    points = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    draw.polygon(points, fill=node_fill("decision"), outline=PALETTE["border"])
    for a, b in zip(points, points[1:] + points[:1]):
        draw.line((a[0], a[1], b[0], b[1]), fill=PALETTE["border"], width=_s(2, scale))
    _node_label(
        draw,
        node,
        (x + _s(14, scale), y + _s(20, scale), x + w - _s(14, scale), y + h - _s(20, scale)),
        scale,
        ref_anchor=_external_ref_anchor(x, y, scale),
    )


def _draw_gateway(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    inset = _s(22, scale)
    points = [
        (x + inset, y),
        (x + w - inset, y),
        (x + w, y + h / 2),
        (x + w - inset, y + h),
        (x + inset, y + h),
        (x, y + h / 2),
    ]
    draw.polygon(points, fill=node_fill("gateway"), outline=PALETTE["border"])
    for a, b in zip(points, points[1:] + points[:1]):
        draw.line((a[0], a[1], b[0], b[1]), fill=PALETTE["border"], width=_s(2, scale))
    _node_label(draw, node, (x + inset, y, x + w - inset, y + h), scale)


def _draw_actor(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    draw.ellipse((x, y, x + w, y + h), fill=node_fill("actor"), outline=PALETTE["border"], width=_s(2, scale))
    _node_label(
        draw,
        node,
        (x + _s(10, scale), y + _s(10, scale), x + w - _s(10, scale), y + h - _s(10, scale)),
        scale,
        ref_anchor=_external_ref_anchor(x, y, scale),
    )


def _draw_document(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    fill = node_fill("document")
    draw.rounded_rectangle((x, y, x + w, y + h), radius=_s(10, scale), fill=fill, outline=PALETTE["border"], width=_s(2, scale))
    fold = _s(20, scale)
    fold_color = _shade(fill, -28)
    draw.polygon(
        [(x + w - fold, y), (x + w, y + fold), (x + w - fold, y + fold)],
        fill=fold_color,
        outline=PALETTE["border"],
    )
    _node_label(draw, node, (x, y, x + w, y + h), scale)


def _draw_queue(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    x, y, w, h = _box(node)
    fill = node_fill("queue")
    draw.rounded_rectangle(
        (x, y, x + w, y + h),
        radius=_s(14, scale),
        fill=fill,
        outline=PALETTE["border"],
        width=_s(2, scale),
    )
    _node_label(draw, node, (x, y, x + w, y + h), scale)


def _draw_database(draw: ImageDraw.ImageDraw, node: dict[str, Any], scale: int) -> None:
    """Single-volume cylinder: cap + body + front-only bottom arc."""
    x, y, w, h = _box(node)
    fill = node_fill("database")
    border = PALETTE["border"]
    stroke = _s(2, scale)
    top_h = max(_s(20, scale), min(_s(34, scale), int(h * 0.26)))

    body_top = y + top_h / 2
    body_bottom = y + h - top_h / 2
    draw.rectangle((x, body_top, x + w, body_bottom), fill=fill)
    draw.chord((x, y + h - top_h, x + w, y + h), start=0, end=180, fill=fill)
    draw.line((x, body_top, x, body_bottom), fill=border, width=stroke)
    draw.line((x + w, body_top, x + w, body_bottom), fill=border, width=stroke)
    draw.arc((x, y + h - top_h, x + w, y + h), start=0, end=180, fill=border, width=stroke)
    draw.ellipse((x, y, x + w, y + top_h), fill=_shade(fill, 14), outline=border, width=stroke)

    visible_top = y + top_h
    visible_bottom = y + h - top_h
    label_box = (x + _s(8, scale), int(visible_top), x + w - _s(8, scale), int(visible_bottom))
    _node_label(draw, node, label_box, scale, ref_anchor=_external_ref_anchor(x, y, scale))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _node_label(
    draw: ImageDraw.ImageDraw,
    node: dict[str, Any],
    box: tuple[int, int, int, int],
    scale: int,
    ref_anchor: tuple[int, int] | None = None,
) -> None:
    label_font = scaled_font(18, scale, bold=True)
    summary_font = scaled_font(13, scale)
    summary = textlib.ellipsize(str(node.get("summary", "")), 42)
    if not summary:
        textlib.draw_wrapped_centered(draw, box, str(node["label"]), label_font, PALETTE["ink"])
    else:
        x1, y1, x2, y2 = box
        content_width = max(10, x2 - x1 - _s(18, scale))
        label_lines = textlib.wrap(draw, str(node["label"]), label_font, content_width)[:2]
        summary_lines = textlib.wrap(draw, summary, summary_font, content_width)[:2]
        label_lh = textlib.text_size(draw, "Ag", label_font)[1] + _s(4, scale)
        summary_lh = textlib.text_size(draw, "Ag", summary_font)[1] + _s(3, scale)
        total = len(label_lines) * label_lh + _s(5, scale) + len(summary_lines) * summary_lh
        y = y1 + max(_s(7, scale), ((y2 - y1) - total) / 2 - _s(4, scale))
        for line in label_lines:
            width, _h = textlib.text_size(draw, line, label_font)
            draw.text((x1 + ((x2 - x1) - width) / 2, y), line, font=label_font, fill=PALETTE["ink"])
            y += label_lh
        y += _s(3, scale)
        for line in summary_lines:
            width, _h = textlib.text_size(draw, line, summary_font)
            draw.text((x1 + ((x2 - x1) - width) / 2, y), line, font=summary_font, fill=PALETTE["muted"])
            y += summary_lh
    if node.get("ref"):
        anchor_x, anchor_y = ref_anchor if ref_anchor is not None else (box[0], box[1])
        ref_font = scaled_font(10, scale, bold=True)
        badge = (
            anchor_x + _s(6, scale),
            anchor_y + _s(5, scale),
            anchor_x + _s(34, scale),
            anchor_y + _s(22, scale),
        )
        draw.rounded_rectangle(badge, radius=_s(7, scale), fill=PALETTE["ref_badge"])
        textlib.draw_centered_box(draw, badge, str(node["ref"]), ref_font, PALETTE["ref_badge_text"])


def _shade(color: Color, delta: int) -> Color:
    return tuple(max(0, min(255, channel + delta)) for channel in color)


def _external_ref_anchor(x: int, y: int, scale: int) -> tuple[int, int]:
    """Anchor for ref badges that hover above the node (used by shapes whose
    interior is dominated by their label — diamond, ellipse, cylinder)."""
    return (x - _s(2, scale), y - _s(20, scale))


def _box(node: dict[str, Any]) -> tuple[int, int, int, int]:
    return int(node["x"]), int(node["y"]), int(node["width"]), int(node["height"])


def _s(value: int | float, scale: int) -> int:
    return max(1, int(round(float(value) * scale)))


# ---------------------------------------------------------------------------
# Outline-aware anchors (Mermaid's intersect-* pattern)
# ---------------------------------------------------------------------------


def intersect_outline(node: dict[str, Any], target: Point, scale: int) -> Point:
    """Return the boundary point where a line from ``target`` enters ``node``."""
    return _INTERSECTORS.get(str(node.get("kind", "service")), _intersect_rect)(node, target, scale)


def outward_side(node: dict[str, Any], target: Point) -> Point:
    cx, cy = _center(node)
    dx = target[0] - cx
    dy = target[1] - cy
    w = float(node["width"])
    h = float(node["height"])
    if abs(dy) * w > abs(dx) * h:
        return (0.0, 1.0) if dy >= 0 else (0.0, -1.0)
    return (1.0, 0.0) if dx >= 0 else (-1.0, 0.0)


def _center(node: dict[str, Any]) -> Point:
    return (float(node["x"]) + float(node["width"]) / 2, float(node["y"]) + float(node["height"]) / 2)


def _intersect_rect(node: dict[str, Any], target: Point, scale: int) -> Point:
    cx, cy = _center(node)
    w = float(node["width"]) / 2
    h = float(node["height"]) / 2
    dx = target[0] - cx
    dy = target[1] - cy
    if dx == 0 and dy == 0:
        return (cx, cy + h)
    if abs(dy) * w > abs(dx) * h:
        sx = (h * dx) / abs(dy) if dy != 0 else 0
        sy = h if dy >= 0 else -h
    else:
        sx = w if dx >= 0 else -w
        sy = (w * dy) / abs(dx) if dx != 0 else 0
    return (cx + sx, cy + sy)


def _intersect_polygon(node: dict[str, Any], target: Point, polygon: list[Point]) -> Point:
    cx, cy = _center(node)
    far = _ray_far(target, (cx, cy))
    hit = line_polygon_intersection((cx, cy), far, polygon)
    return hit if hit is not None else (cx, cy)


def _intersect_diamond(node: dict[str, Any], target: Point, scale: int) -> Point:
    return _intersect_polygon(node, target, _diamond_polygon(node))


def _intersect_hexagon(node: dict[str, Any], target: Point, scale: int) -> Point:
    return _intersect_polygon(node, target, _hexagon_polygon(node, scale))


def _intersect_ellipse(node: dict[str, Any], target: Point, scale: int) -> Point:
    cx, cy = _center(node)
    rx = float(node["width"]) / 2
    ry = float(node["height"]) / 2
    hit = line_ellipse_intersection((cx, cy), _ray_far(target, (cx, cy)), (cx, cy), rx, ry)
    return hit if hit is not None else _intersect_rect(node, target, scale)


def _intersect_database(node: dict[str, Any], target: Point, scale: int) -> Point:
    x = float(node["x"])
    y = float(node["y"])
    w = float(node["width"])
    h = float(node["height"])
    cap_h = max(_s(20, scale), min(_s(34, scale), int(h * 0.26)))
    body_top = y + cap_h / 2
    body_bottom = y + h - cap_h / 2
    rect_hit = _intersect_rect(node, target, scale)
    if abs(rect_hit[0] - x) < 1.5 or abs(rect_hit[0] - (x + w)) < 1.5:
        clamped_y = max(body_top + _s(8, scale), min(rect_hit[1], body_bottom - _s(8, scale)))
        return (rect_hit[0], clamped_y)
    return rect_hit


def _diamond_polygon(node: dict[str, Any]) -> list[Point]:
    x = float(node["x"])
    y = float(node["y"])
    w = float(node["width"])
    h = float(node["height"])
    return [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]


def _hexagon_polygon(node: dict[str, Any], scale: int) -> list[Point]:
    x = float(node["x"])
    y = float(node["y"])
    w = float(node["width"])
    h = float(node["height"])
    inset = float(_s(22, scale))
    return [
        (x + inset, y),
        (x + w - inset, y),
        (x + w, y + h / 2),
        (x + w - inset, y + h),
        (x + inset, y + h),
        (x, y + h / 2),
    ]


def _ray_far(point: Point, origin: Point) -> Point:
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return (point[0] + 1.0, point[1])
    factor = 5000.0 / length
    return (origin[0] + dx * factor, origin[1] + dy * factor)


_SHAPE_DRAWERS = {
    "container": _draw_container,
    "service": _draw_service,
    "custom": _draw_service,
    "external": _draw_external,
    "decision": _draw_decision,
    "gateway": _draw_gateway,
    "actor": _draw_actor,
    "document": _draw_document,
    "queue": _draw_queue,
    "database": _draw_database,
}

_INTERSECTORS = {
    "actor": _intersect_ellipse,
    "decision": _intersect_diamond,
    "gateway": _intersect_hexagon,
    "database": _intersect_database,
    "service": _intersect_rect,
    "queue": _intersect_rect,
    "document": _intersect_rect,
    "external": _intersect_rect,
    "container": _intersect_rect,
    "custom": _intersect_rect,
}
