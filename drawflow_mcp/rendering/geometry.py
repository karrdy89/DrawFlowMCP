"""Pure-math geometry helpers shared by shapes/arrows/labels.

No drawing here. Just point/box/segment primitives.
"""
from __future__ import annotations

import math


Point = tuple[float, float]
Box = tuple[int, int, int, int]


def s(value: int | float, scale: int) -> int:
    """Scale a logical pixel value to the supersampled render space."""
    return max(1, int(round(float(value) * scale)))


def expand(box: Box, amount: int) -> Box:
    return (box[0] - amount, box[1] - amount, box[2] + amount, box[3] + amount)


def overlap_area(a: Box, b: Box) -> int:
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return width * height


def point_in_box(point: Point, box: Box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def line_polygon_intersection(start: Point, end: Point, polygon: list[Point]) -> Point | None:
    """Closest segment-edge hit when the segment crosses a polygon."""
    closest: Point | None = None
    closest_t = math.inf
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        hit = _segment_intersection_param(start, end, a, b)
        if hit is None:
            continue
        t, point = hit
        if 0.0 <= t <= 1.0 and t < closest_t:
            closest_t = t
            closest = point
    return closest


def line_ellipse_intersection(start: Point, end: Point, center: Point, rx: float, ry: float) -> Point | None:
    if rx <= 0 or ry <= 0:
        return None
    cx, cy = center
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return None
    fx = (start[0] - cx) / rx
    fy = (start[1] - cy) / ry
    gx = dx / rx
    gy = dy / ry
    a = gx * gx + gy * gy
    b = 2 * (fx * gx + fy * gy)
    c = fx * fx + fy * fy - 1
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    sqrt_disc = math.sqrt(disc)
    candidates = [(-b - sqrt_disc) / (2 * a), (-b + sqrt_disc) / (2 * a)]
    valid = [t for t in candidates if 0.0 <= t <= 1.0]
    if not valid:
        return None
    t = min(valid)
    return (start[0] + dx * t, start[1] + dy * t)


def clean_polyline(points: list[Point]) -> list[Point]:
    """Drop duplicate and collinear midpoints from an orthogonal polyline."""
    deduped: list[Point] = []
    for point in points:
        if not deduped or abs(point[0] - deduped[-1][0]) > 0.1 or abs(point[1] - deduped[-1][1]) > 0.1:
            deduped.append(point)
    if len(deduped) <= 2:
        return deduped
    cleaned = [deduped[0]]
    for index in range(1, len(deduped) - 1):
        prev = cleaned[-1]
        cur = deduped[index]
        nxt = deduped[index + 1]
        same_x = abs(prev[0] - cur[0]) < 0.1 and abs(cur[0] - nxt[0]) < 0.1
        same_y = abs(prev[1] - cur[1]) < 0.1 and abs(cur[1] - nxt[1]) < 0.1
        if not same_x and not same_y:
            cleaned.append(cur)
    cleaned.append(deduped[-1])
    return cleaned


def path_length(points: list[Point]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def path_midpoint(points: list[Point]) -> tuple[Point, Point]:
    """Return ``(point, tangent_unit_vector)`` at the midpoint of the polyline."""
    total = max(1.0, path_length(points))
    target = total / 2
    walked = 0.0
    for a, b in zip(points, points[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg <= 0:
            continue
        if walked + seg >= target:
            local = (target - walked) / seg
            anchor = (a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local)
            tangent = ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
            return anchor, tangent
        walked += seg
    a, b = points[-2], points[-1]
    seg = max(1.0, math.hypot(b[0] - a[0], b[1] - a[1]))
    return b, ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)


def _segment_intersection_param(p1: Point, p2: Point, p3: Point, p4: Point) -> tuple[float, Point] | None:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0.0 <= u <= 1.0:
        point = (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        return t, point
    return None
