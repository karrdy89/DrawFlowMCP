"""Graph PNG renderer.

Pipeline:

  GraphDocument  ─►  layered_layout.layout_nodes  (grandalf Sugiyama)
                 ─►  build edge polylines (orthogonal elbows on outline anchors)
                 ─►  Pillow paint:  panel  ─► clusters
                                            ├─► edges + arrows
                                            ├─► nodes (foreground)
                                            ├─► repaint cluster header
                                            └─► edge labels (polyline midpoint)

Layout (rank, crossing reduction, x-coordinate) is grandalf's
responsibility. Edge routing is intentionally simple: a straight line
when the two endpoints are nearly aligned, otherwise a single L-shape
elbow. Labels go on the polyline midpoint with a white pill — same
trick D2 / Mermaid use.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..errors import RenderError
from . import arrows, text as textlib
from .geometry import Point, path_midpoint, s
from .layered_layout import layout_nodes
from .shapes import draw_node, intersect_outline
from .theme import (
    GRAPH_ANTIALIAS_FACTOR,
    PALETTE,
    edge_defaults,
    scaled_font,
)


def render_graph_png(scene: dict[str, Any], output_path: Path) -> dict[str, int]:
    try:
        return _render(scene, output_path)
    except Exception as exc:  # pragma: no cover - converted to tool error
        raise RenderError(f"Failed to render graph PNG: {exc}") from exc


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def _render(scene: dict[str, Any], output_path: Path) -> dict[str, int]:
    diagram = scene["diagram"]
    canvas = scene["canvas"]

    output_scale = int(canvas.get("scale", 1))
    render_scale = max(output_scale, output_scale * GRAPH_ANTIALIAS_FACTOR)

    # Lay out in logical pixels first so node intrinsic sizes / cluster
    # padding stay readable; auto-size the canvas to fit the layout.
    laid_nodes = layout_nodes(diagram, canvas)
    canvas_w, canvas_h = _auto_canvas_size(laid_nodes, canvas)
    work_w = canvas_w * render_scale
    work_h = canvas_h * render_scale
    work_nodes = _scale_nodes(laid_nodes, render_scale)

    transparent = bool(canvas.get("transparentBackground", False))
    image_mode = "RGBA" if transparent else "RGB"
    background = (0, 0, 0, 0) if transparent else PALETTE["background"]
    image = Image.new(image_mode, (work_w, work_h), background)
    draw = ImageDraw.Draw(image)
    _draw_panel(draw, work_w, work_h, render_scale)
    _draw_title(draw, diagram, render_scale)

    foreground = [n for n in work_nodes if n.get("kind") != "container"]
    containers = [n for n in work_nodes if n.get("kind") == "container"]
    node_by_id = {n["id"]: n for n in work_nodes}

    # 1) cluster bodies
    for container in containers:
        draw_node(draw, container, render_scale)

    # Foreground node bboxes used by the edge router to detour around
    # nodes that don't belong to this edge.
    fg_box_by_id: dict[str, tuple[int, int, int, int]] = {
        n["id"]: (int(n["x"]), int(n["y"]), int(n["x"]) + int(n["width"]), int(n["y"]) + int(n["height"]))
        for n in foreground
    }
    # Container bboxes per cluster id, used as additional obstacles so a
    # detour that goes "below the obstacle band" lands past the container
    # bottom (inside the inter-cluster gap) rather than running parallel
    # to a cluster border line. We exclude the source/target's own
    # cluster so edges can still exit/enter their owning container.
    container_box_by_id: dict[str, tuple[int, int, int, int]] = {
        c["id"]: (int(c["x"]), int(c["y"]), int(c["x"]) + int(c["width"]), int(c["y"]) + int(c["height"]))
        for c in containers
    }
    parent_by_node: dict[str, str | None] = {n["id"]: n.get("parent") for n in foreground}

    # 2) edge polylines underneath nodes — port-aware routing so multiple
    # edges sharing the same source-side or target-side land at distinct
    # ports along that side instead of overlapping.
    src_offsets, tgt_offsets, sides = _assign_ports(diagram["edges"], node_by_id, render_scale)
    # Phase A: route every edge first, so we can analyse crossings before
    # painting and shift same-color crossing edges to distinct hues.
    # `claimed_h/v_lanes` track long horizontal/vertical detour segments
    # already chosen — each new edge's detour is then dynamically shifted
    # OFF any claimed lane that overlaps its x-range (or y-range), so two
    # edges never share a long parallel run on the same axis.
    claimed_h_lanes: list[tuple[float, float, float]] = []
    claimed_v_lanes: list[tuple[float, float, float]] = []
    # Pre-seed cluster border lines as occupied lanes so an edge bend never
    # lands ON a container's top/bottom/left/right border. Without this,
    # `_find_free_lane` only avoids previously-routed edges and can pick a
    # bend coord that runs parallel to a cluster border (visually looks
    # like the edge is drawn on top of the cluster's frame).
    for cbox in container_box_by_id.values():
        cx1, cy1, cx2, cy2 = cbox
        claimed_h_lanes.append((float(cx1), float(cx2), float(cy1)))
        claimed_h_lanes.append((float(cx1), float(cx2), float(cy2)))
        claimed_v_lanes.append((float(cy1), float(cy2), float(cx1)))
        claimed_v_lanes.append((float(cy1), float(cy2), float(cx2)))
    pending: list[tuple[dict[str, Any], list[Point], tuple[int, int, int], str, int, bool]] = []
    for idx, edge in enumerate(diagram["edges"]):
        source = node_by_id.get(edge["source"])
        target = node_by_id.get(edge["target"])
        if not source or not target:
            continue
        obstacles = [box for nid, box in fg_box_by_id.items() if nid not in (source["id"], target["id"])]
        # Add foreign-cluster containers as obstacle bands so the detour
        # leaves a real gutter between cluster borders and the routed
        # line — eliminates the visible "parallel-to-border" defect.
        src_parent = parent_by_node.get(source["id"])
        tgt_parent = parent_by_node.get(target["id"])
        for cid, cbox in container_box_by_id.items():
            if cid == src_parent or cid == tgt_parent:
                continue
            obstacles.append(cbox)
        # Source/target's OWN cluster: included as a "soft" obstacle so the
        # detour_y is pushed past the owning cluster's border too, but the
        # edge is still allowed to traverse it (since exit/entry points
        # live inside it). Without this the horizontal detour can run
        # immediately under/above the source's cluster border, looking
        # parallel-overlapped with the border line.
        soft_obstacles: list[tuple[int, int, int, int]] = []
        for cid in (src_parent, tgt_parent):
            if cid and cid in container_box_by_id:
                soft_obstacles.append(container_box_by_id[cid])
        ss, ts = sides[idx]
        polyline = _route_edge(
            source, target, render_scale, obstacles,
            src_off=src_offsets[idx], tgt_off=tgt_offsets[idx],
            src_side=ss, tgt_side=ts,
            soft_obstacles=soft_obstacles,
            claimed_h_lanes=claimed_h_lanes,
            claimed_v_lanes=claimed_v_lanes,
        )
        # Record the long axial segments this edge just claimed so later
        # edges can dodge them. Threshold weeds out the tiny port stubs.
        min_lane_len = s(40, render_scale)
        for a, b in zip(polyline, polyline[1:]):
            dx = abs(b[0] - a[0])
            dy = abs(b[1] - a[1])
            if dy < 1 and dx >= min_lane_len:
                claimed_h_lanes.append((min(a[0], b[0]), max(a[0], b[0]), float(a[1])))
            elif dx < 1 and dy >= min_lane_len:
                claimed_v_lanes.append((min(a[1], b[1]), max(a[1], b[1]), float(a[0])))
        color, line_style, width = arrows.edge_style(edge, render_scale, edge_defaults(str(edge.get("kind", "sync"))))
        explicit_color = bool((edge.get("style") or {}).get("strokeColor"))
        pending.append((edge, polyline, color, line_style, width, explicit_color))

    colors = _retint_crossing_edges([(p[1], p[2], p[5]) for p in pending])
    edge_routes: list[tuple[dict[str, Any], list[Point], tuple[int, int, int]]] = []
    for (edge, polyline, _orig_color, line_style, width, _explicit), color in zip(pending, colors):
        arrows.draw_polyline(draw, polyline, color, width, line_style, render_scale)
        edge_routes.append((edge, polyline, color))

    # 3) cluster headers re-drawn on top of any edges that cross them so
    # the cluster title is always readable, but the edge line itself stays
    # visible behind the text (no fill repaint).
    for container in containers:
        _repaint_container_header(draw, container, render_scale)

    # 4) foreground nodes
    for node in foreground:
        draw_node(draw, node, render_scale)

    # 5) arrowheads on top of nodes — head tip sits on the node outline,
    # head body extends backward along the last segment.
    for edge, polyline, color in edge_routes:
        if len(polyline) < 2:
            continue
        arrow = edge.get("arrow") or {}
        head_size = s(14, render_scale)
        arrows.draw_arrow_head(
            draw,
            polyline[0],
            polyline[1],
            arrow.get("start", "none"),
            bool(arrow.get("startFill", False)),
            color,
            size=head_size,
        )
        arrows.draw_arrow_head(
            draw,
            polyline[-1],
            polyline[-2],
            arrow.get("end", "classic"),
            bool(arrow.get("endFill", True)),
            color,
            size=head_size,
        )

    # 6) edge labels at polyline midpoint (pushed off node outlines and
    # off any cross-edge intersection so the pill never hides where two
    # edges cross).
    node_boxes = [
        (int(n["x"]), int(n["y"]), int(n["x"]) + int(n["width"]), int(n["y"]) + int(n["height"]))
        for n in foreground
    ]
    all_polys = [poly for _, poly, _ in edge_routes]
    placed_pills: list[tuple[float, float, float, float]] = []
    for idx, (edge, polyline, color) in enumerate(edge_routes):
        label = edge.get("label")
        if not label:
            continue
        others = [p for j, p in enumerate(all_polys) if j != idx]
        own_crossings = _crossings_on_polyline(polyline, others)
        pill = _draw_edge_label(
            draw, str(label), polyline, color, render_scale,
            node_boxes, own_crossings, placed_pills,
        )
        if pill is not None:
            placed_pills.append(pill)

    # Resize down to output scale and save.
    final_size = (canvas_w * output_scale, canvas_h * output_scale)
    if image.size != final_size:
        image = image.resize(final_size, Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return {"width": canvas_w, "height": canvas_h, "scale": output_scale}


# ---------------------------------------------------------------------------
# Canvas auto-sizing
# ---------------------------------------------------------------------------


def _auto_canvas_size(nodes: list[dict[str, Any]], canvas: dict[str, Any]) -> tuple[int, int]:
    """Pick a canvas size big enough to hold the laid-out nodes plus a
    bottom/right margin generous enough for edge detour lanes and label
    pills that sit outside the cluster band. We honor the user-provided
    width/height as a *minimum* so callers can request a wider canvas if
    they want.
    """
    min_w = int(canvas.get("width", 0))
    min_h = int(canvas.get("height", 0))
    if not nodes:
        return max(min_w, 600), max(min_h, 400)
    right = max(int(n["x"]) + int(n["width"]) for n in nodes)
    bottom = max(int(n["y"]) + int(n["height"]) for n in nodes)
    # Edges that detour below/right of the layout band stack additional
    # lanes (gap + N * lane_step) plus a label pill. For 6 stacked lanes
    # at lane_step ≈ 20 plus gap ≈ 26 plus pill half-height ≈ 18, the
    # worst case is ~160 logical px past the bottom-most node. Reserve
    # that headroom unconditionally — the canvas is auto-sized anyway,
    # so unused slack just renders as background.
    edge_margin = 160
    width = max(min_w, right + edge_margin)
    height = max(min_h, bottom + edge_margin)
    return width, height


def _scale_nodes(nodes: list[dict[str, Any]], scale: int) -> list[dict[str, Any]]:
    out = []
    for node in nodes:
        clone = copy.deepcopy(node)
        for key in ("x", "y", "width", "height"):
            if key in clone:
                clone[key] = int(round(int(clone[key]) * scale))
        zone = clone.get("_clusterZone")
        if zone:
            clone["_clusterZone"] = {k: int(round(int(v) * scale)) for k, v in zone.items()}
        out.append(clone)
    return out


# ---------------------------------------------------------------------------
# Panel + title
# ---------------------------------------------------------------------------


def _draw_panel(draw: ImageDraw.ImageDraw, width: int, height: int, scale: int) -> None:
    margin = s(24, scale)
    draw.rounded_rectangle(
        (margin, margin, width - margin, height - margin),
        radius=s(28, scale),
        fill=PALETTE["panel"],
        outline=PALETTE["panel_outline"],
        width=s(2, scale),
    )


def _draw_title(draw: ImageDraw.ImageDraw, diagram: dict[str, Any], scale: int) -> None:
    title_font = scaled_font(28, scale, bold=True)
    draw.text((s(48, scale), s(36, scale)), str(diagram.get("title", "")), font=title_font, fill=PALETTE["ink"])
    description = str(diagram.get("description") or "")[:160]
    if description:
        sub_font = scaled_font(15, scale)
        draw.text((s(48, scale), s(76, scale)), description, font=sub_font, fill=PALETTE["muted"])


# ---------------------------------------------------------------------------
# Cluster header repaint
# ---------------------------------------------------------------------------


def _repaint_container_header(draw: ImageDraw.ImageDraw, container: dict, scale: int) -> None:
    x = int(container["x"])
    y = int(container["y"])
    label_x = x + s(18, scale)
    if container.get("ref"):
        badge = (x + s(14, scale), y + s(12, scale), x + s(46, scale), y + s(31, scale))
        draw.rounded_rectangle(badge, radius=s(7, scale), fill=PALETTE["container_ref_badge"])
        textlib.draw_centered_box(draw, badge, str(container["ref"]), scaled_font(10, scale, bold=True), PALETTE["ref_badge_text"])
        label_x = x + s(54, scale)
    draw.text((label_x, y + s(11, scale)), str(container["label"]), font=scaled_font(16, scale, bold=True), fill=PALETTE["container_label"])
    if container.get("summary"):
        summary = textlib.ellipsize(str(container["summary"]), 54)
        draw.text((label_x, y + s(35, scale)), summary, font=scaled_font(12, scale), fill=PALETTE["muted"])


# ---------------------------------------------------------------------------
# Edge routing — simple: outline anchors + L-shape elbow
# ---------------------------------------------------------------------------


def _classify_side(sc: Point, tc: Point) -> tuple[str, str]:
    """Pick the dominant exit/entry side of source and target based on
    their relative center positions. Edges flow along the longer axis."""
    if abs(tc[0] - sc[0]) >= abs(tc[1] - sc[1]):
        if tc[0] >= sc[0]:
            return "right", "left"
        return "left", "right"
    if tc[1] >= sc[1]:
        return "bottom", "top"
    return "top", "bottom"


def _assign_ports(
    edges: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    scale: int,
) -> tuple[list[float], list[float], list[tuple[str, str]]]:
    """For each edge, classify its (source_side, target_side). Edges that
    share the same (node, side) are spaced out into distinct ports along
    that side so they don't draw on top of each other.

    Spacing is dagre/ELK style: a fixed perpendicular step per port,
    centered on the side. Larger fan-in (3+ edges) gets wider spacing so
    each edge has a clearly separable lane."""
    base_spacing = s(22, scale)
    fan_spacing = s(28, scale)
    sides: list[tuple[str, str]] = []
    src_groups: dict[tuple[str, str], list[int]] = {}
    tgt_groups: dict[tuple[str, str], list[int]] = {}
    for i, edge in enumerate(edges):
        s_node = node_by_id.get(edge["source"])
        t_node = node_by_id.get(edge["target"])
        if not s_node or not t_node:
            sides.append(("right", "left"))
            continue
        ss, ts = _classify_side(_center(s_node), _center(t_node))
        sides.append((ss, ts))
        src_groups.setdefault((edge["source"], ss), []).append(i)
        tgt_groups.setdefault((edge["target"], ts), []).append(i)

    src_off = [0.0] * len(edges)
    tgt_off = [0.0] * len(edges)

    def _ortho_key_target(i: int, side_: str) -> float:
        n = node_by_id[edges[i]["target"]]
        c = _center(n)
        return c[1] if side_ in ("left", "right") else c[0]

    def _ortho_key_source(i: int, side_: str) -> float:
        n = node_by_id[edges[i]["source"]]
        c = _center(n)
        return c[1] if side_ in ("left", "right") else c[0]

    def _node_span(nid: str, side_: str) -> float:
        n = node_by_id.get(nid)
        if not n:
            return 0.0
        return float(n["height"]) if side_ in ("left", "right") else float(n["width"])

    for (nid, side_), indices in src_groups.items():
        if len(indices) < 2:
            continue
        indices.sort(key=lambda i: _ortho_key_target(i, side_))
        n = len(indices)
        # Spacing scales with node size so 2 ports on a tall node aren't
        # 22px apart on a 90px side — they get a meaningful split.
        span = _node_span(nid, side_)
        spacing = max(fan_spacing if n >= 3 else base_spacing, span * 0.55 / max(n - 1, 1))
        spacing = min(spacing, span * 0.42)
        for k, i in enumerate(indices):
            src_off[i] = (k - (n - 1) / 2) * spacing
    for (nid, side_), indices in tgt_groups.items():
        if len(indices) < 2:
            continue
        indices.sort(key=lambda i: _ortho_key_source(i, side_))
        n = len(indices)
        span = _node_span(nid, side_)
        spacing = max(fan_spacing if n >= 3 else base_spacing, span * 0.55 / max(n - 1, 1))
        spacing = min(spacing, span * 0.42)
        for k, i in enumerate(indices):
            tgt_off[i] = (k - (n - 1) / 2) * spacing
    return src_off, tgt_off, sides


# Distinct, saturated tints used to re-color same-color edges that cross
# each other. Picked to stay visually separable from the default six edge
# kinds (sync/async/data/control/dependency/inheritance) and from each
# other under colorblind-safe heuristics. Order matters: we walk it in
# sequence per crossing conflict so adjacent re-tints are different hues.
_CROSSING_RETINT_PALETTE: tuple[tuple[int, int, int], ...] = (
    (217, 70, 70),     # vivid red
    (220, 138, 0),     # amber
    (5, 150, 105),     # teal-green (distinct from data-teal)
    (101, 67, 209),    # indigo (distinct from control-violet)
    (190, 24, 93),     # magenta
    (14, 116, 144),    # cyan
)


def _retint_crossing_edges(
    routed: list[tuple[list[Point], tuple[int, int, int], bool]],
) -> list[tuple[int, int, int]]:
    """Greedy re-color: when two edges of the same color cross, shift one
    to a distinct hue so the viewer can tell which strand is which.

    `routed` is a list of (polyline, original_color, explicit_color) per
    edge in render order. Edges with `explicit_color=True` (user picked
    `style.strokeColor`) are pinned and never recolored.
    """
    n = len(routed)
    colors: list[tuple[int, int, int]] = [c for _, c, _ in routed]
    if n < 2:
        return colors
    # Crossing matrix.
    crosses: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if _polylines_cross(routed[i][0], routed[j][0]):
                crosses[i].add(j)
                crosses[j].add(i)
    palette_cursor = 0
    for i in range(n):
        if routed[i][2]:  # explicit color → never retint
            continue
        # Conflict = any neighbor (crossing) sharing the same final color.
        conflict = any(colors[j] == colors[i] for j in crosses[i])
        if not conflict:
            continue
        # Pick a palette color that doesn't conflict with any crossing
        # neighbor's current color.
        for k in range(len(_CROSSING_RETINT_PALETTE)):
            cand = _CROSSING_RETINT_PALETTE[(palette_cursor + k) % len(_CROSSING_RETINT_PALETTE)]
            if all(colors[j] != cand for j in crosses[i]):
                colors[i] = cand
                palette_cursor = (palette_cursor + k + 1) % len(_CROSSING_RETINT_PALETTE)
                break
    return colors


def _polylines_cross(a: list[Point], b: list[Point]) -> bool:
    for p1, p2 in zip(a, a[1:]):
        for p3, p4 in zip(b, b[1:]):
            if _segments_cross(p1, p2, p3, p4):
                return True
    return False


_RECT_KINDS = {"ellipse", "actor", "cylinder", "database", "decision", "diamond", "gateway", "hexagon"}


def _exit_point(node: dict[str, Any], side: str, port_off: float, scale: int) -> Point:
    """Compute the boundary point where this edge enters/exits the node.
    Always start from the bbox-side port position. For rectangles that
    IS the boundary; for shaped nodes (ellipse/cylinder/diamond/hexagon/
    actor/gateway) we project the bbox port onto the actual outline by
    raycasting from center toward it. This keeps each port distinct even
    when one side of the shape collapses to a single vertex (e.g., the
    right corner of a hexagon)."""
    kind = str(node.get("kind", ""))
    x = float(node["x"]); y = float(node["y"])
    w = float(node["width"]); h = float(node["height"])
    cx, cy = x + w / 2, y + h / 2
    inset = 6
    if side == "right":
        port_x = x + w
        port_y = max(y + inset, min(y + h - inset, cy + port_off))
    elif side == "left":
        port_x = x
        port_y = max(y + inset, min(y + h - inset, cy + port_off))
    elif side == "top":
        port_x = max(x + inset, min(x + w - inset, cx + port_off))
        port_y = y
    else:
        port_x = max(x + inset, min(x + w - inset, cx + port_off))
        port_y = y + h
    if kind in _RECT_KINDS:
        return intersect_outline(node, (port_x, port_y), scale)
    return (port_x, port_y)


def _route_edge(
    source: dict[str, Any],
    target: dict[str, Any],
    scale: int,
    obstacles: list[tuple[int, int, int, int]] | None = None,
    src_off: float = 0.0,
    tgt_off: float = 0.0,
    src_side: str = "right",
    tgt_side: str = "left",
    soft_obstacles: list[tuple[int, int, int, int]] | None = None,
    claimed_h_lanes: list[tuple[float, float, float]] | None = None,
    claimed_v_lanes: list[tuple[float, float, float]] | None = None,
) -> list[Point]:
    start = _exit_point(source, src_side, src_off, scale)
    end = _exit_point(target, tgt_side, tgt_off, scale)
    src_h = src_side in ("left", "right")
    tgt_h = tgt_side in ("left", "right")

    primary = _build_route(start, end, src_h, tgt_h)
    margin = s(12, scale)
    obstacles = obstacles or []
    soft_obstacles = soft_obstacles or []
    claimed_h_lanes = claimed_h_lanes or []
    claimed_v_lanes = claimed_v_lanes or []

    if not _polyline_hits_any(primary, obstacles, margin):
        # Even when the primary L-route is "clear" of nodes/clusters, it
        # might still run on top of a previously-claimed parallel lane.
        # Only nudge when the primary is exactly straight or the dominant
        # axial run sits on a claimed lane.
        nudged = _nudge_primary_off_claimed_lanes(
            primary, claimed_h_lanes, claimed_v_lanes, scale,
            obstacles, margin,
        )
        return nudged

    # Channel offset = perpendicular shift of the detour lane per edge,
    # so multiple edges that detour around the same obstacle band toward
    # the same target side don't collapse into one corridor (dagre-style
    # channel routing). The strongest signal is tgt_off (target port
    # index) since fan-in is what makes lanes overlap.
    channel_off = tgt_off + 0.5 * src_off
    # Build the actual blocker set from the L/S polyline that just failed,
    # not from the diagonal start→end. The polyline can pierce a node
    # whose bbox the diagonal misses (e.g. when the bend's horizontal
    # arm crosses a node sitting at the same y as the source).
    polyline_blockers = [
        box for box in obstacles
        if _polyline_hits_any(primary, [box], margin)
    ]
    detour = _detour_with_ports(
        start, end, src_side, tgt_side,
        polyline_blockers if polyline_blockers else obstacles,
        margin, scale, channel_off,
        soft_obstacles=soft_obstacles,
        claimed_h_lanes=claimed_h_lanes,
        claimed_v_lanes=claimed_v_lanes,
        pre_filtered=bool(polyline_blockers),
        all_obstacles=obstacles,
    )
    if detour and not _polyline_hits_any(detour, obstacles, margin):
        return detour
    return primary


def _lane_occupied(
    coord: float,
    range_lo: float,
    range_hi: float,
    claimed: list[tuple[float, float, float]],
    min_separation: float,
) -> bool:
    """Return True if any claimed lane on the same axis sits within
    `min_separation` of `coord` AND its range overlaps [range_lo, range_hi].
    Explicit "is this strip already used" predicate that the routing code
    asks before committing to a bend coordinate."""
    for lo, hi, c in claimed:
        if abs(c - coord) >= min_separation:
            continue
        if hi < range_lo or lo > range_hi:
            continue
        return True
    return False


def _find_free_lane(
    coord: float,
    range_lo: float,
    range_hi: float,
    claimed: list[tuple[float, float, float]],
    min_separation: float,
    step: float,
    bias: int,
) -> float:
    """Starting from `coord`, search outward for a coordinate that is at
    least `min_separation` away from every claimed lane that overlaps
    the [range_lo, range_hi]. `bias` (+1 or -1) is the preferred
    direction; if that side stays occupied for many steps the other side
    is tried too. Pure local optimization — no global re-layout."""
    if not _lane_occupied(coord, range_lo, range_hi, claimed, min_separation):
        return coord
    for k in range(1, 24):
        for sign in (bias, -bias):
            cand = coord + sign * step * k
            if not _lane_occupied(cand, range_lo, range_hi, claimed, min_separation):
                return cand
    return coord


def _nudge_primary_off_claimed_lanes(
    polyline: list[Point],
    claimed_h: list[tuple[float, float, float]],
    claimed_v: list[tuple[float, float, float]],
    scale: int,
    obstacles: list[tuple[int, int, int, int]],
    margin: int,
) -> list[Point]:
    """If the primary route's middle horizontal/vertical sits on a claimed
    lane, shift the bend point to a free coordinate. Only applies to
    routes shaped [start, mid, mid, end] (S-shape) or [start, mid, end]
    (L-shape) — anything fancier was already a detour."""
    if len(polyline) < 3:
        return polyline
    min_sep = s(30, scale)
    step = s(20, scale)
    if len(polyline) == 4:
        a, b, c, d = polyline
        # Horizontal: y stays constant on (a,b) and (c,d), middle vertical (b,c)
        if abs(a[1] - b[1]) < 1 and abs(c[1] - d[1]) < 1:
            # Middle is vertical at x = b[0] = c[0]; lane is along x.
            mid_x = b[0]
            range_lo = min(b[1], c[1])
            range_hi = max(b[1], c[1])
            new_x = _find_free_lane(mid_x, range_lo, range_hi, claimed_v, min_sep, step, +1)
            if new_x != mid_x:
                candidate = [a, (new_x, b[1]), (new_x, c[1]), d]
                if not _polyline_hits_any(candidate, obstacles, margin):
                    return candidate
        # Vertical: x stays constant on (a,b) and (c,d), middle horizontal (b,c)
        if abs(a[0] - b[0]) < 1 and abs(c[0] - d[0]) < 1:
            mid_y = b[1]
            range_lo = min(b[0], c[0])
            range_hi = max(b[0], c[0])
            new_y = _find_free_lane(mid_y, range_lo, range_hi, claimed_h, min_sep, step, +1)
            if new_y != mid_y:
                candidate = [a, (b[0], new_y), (c[0], new_y), d]
                if not _polyline_hits_any(candidate, obstacles, margin):
                    return candidate
    return polyline


def _build_route(start: Point, end: Point, src_h: bool, tgt_h: bool) -> list[Point]:
    if src_h and not tgt_h:
        # h-out then v-in: corner aligns with target's x and start's y
        if abs(start[0] - end[0]) < 4 or abs(start[1] - end[1]) < 4:
            return [start, end]
        return [start, (end[0], start[1]), end]
    if (not src_h) and tgt_h:
        if abs(start[0] - end[0]) < 4 or abs(start[1] - end[1]) < 4:
            return [start, end]
        return [start, (start[0], end[1]), end]
    if src_h and tgt_h:
        if abs(start[1] - end[1]) < 4:
            return [start, end]
        mid_x = (start[0] + end[0]) / 2
        return [start, (mid_x, start[1]), (mid_x, end[1]), end]
    if abs(start[0] - end[0]) < 4:
        return [start, end]
    mid_y = (start[1] + end[1]) / 2
    return [start, (start[0], mid_y), (end[0], mid_y), end]


def _detour_with_ports(
    start: Point,
    end: Point,
    src_side: str,
    tgt_side: str,
    obstacles: list[tuple[int, int, int, int]],
    margin: int,
    scale: int,
    channel_off: float = 0.0,
    soft_obstacles: list[tuple[int, int, int, int]] | None = None,
    claimed_h_lanes: list[tuple[float, float, float]] | None = None,
    claimed_v_lanes: list[tuple[float, float, float]] | None = None,
    pre_filtered: bool = False,
    all_obstacles: list[tuple[int, int, int, int]] | None = None,
) -> list[Point] | None:
    """When the primary L/S route hits a non-endpoint node, route AROUND
    the obstacle band. Detour direction is chosen by:
      1) shorter detour if one side is clearly closer (>1.5x ratio),
      2) otherwise prefer routing BELOW/RIGHT of the obstacles — empty
         space tends to live there in our top-anchored layouts and the
         path stays clear of cluster headers.
    `soft_obstacles` (source/target's own clusters) widen the union band
    so the detour lane is pushed past their borders too, but they aren't
    used for the hit-test — the polyline is allowed to traverse them.
    When `pre_filtered=True` the caller has already determined which
    obstacles must be detoured around (typically by polyline-hit test) so
    we skip the straight-line filter — that filter misses cases where the
    L/S polyline pierces a node whose bbox the diagonal start→end happens
    to miss."""
    if pre_filtered:
        blocking = [
            (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
            for box in obstacles
        ]
    else:
        blocking = [
            (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
            for box in obstacles
            if _segment_intersects_box(start, end, (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin))
        ]
    if not blocking:
        return None
    soft_obstacles = soft_obstacles or []
    soft_inflated = [
        (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
        for box in soft_obstacles
    ]
    union_x1 = min((b[0] for b in blocking + soft_inflated))
    union_y1 = min((b[1] for b in blocking + soft_inflated))
    union_x2 = max((b[2] for b in blocking + soft_inflated))
    union_y2 = max((b[3] for b in blocking + soft_inflated))
    gap = s(26, scale)
    ext = s(24, scale)

    src_h = src_side in ("left", "right")
    tgt_h = tgt_side in ("left", "right")
    horizontal = src_h or tgt_h or (abs(end[0] - start[0]) >= abs(end[1] - start[1]))
    claimed_h_lanes = claimed_h_lanes or []
    claimed_v_lanes = claimed_v_lanes or []
    min_sep = s(30, scale)
    lane_step = s(20, scale)

    # Map a signed channel_off to a strictly distinct nonnegative lane offset.
    # `abs(channel_off)` collapses +x and -x onto the same lane, which is the
    # bug that makes two edges (different sources, different targets) share a
    # corridor when they detour through the same band. Bias negatives further
    # out so every distinct channel_off value lands in its own lane.
    def _lane(off: float) -> float:
        sign_bias = s(12, scale) if off < 0 else 0
        return abs(off) + sign_bias

    # Inflated obstacle list for downstream hit-tests (segment-vs-box).
    # When the caller pre-filtered `obstacles` to a small subset, hit-test
    # MUST still run against the complete obstacle set so detours don't
    # silently hop over an unrelated cluster/node on the way around.
    hit_test_source = all_obstacles if all_obstacles is not None else obstacles
    obstacles_inflated = [
        (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
        for box in hit_test_source
    ]

    def _segment_clears_obstacles(a: Point, b: Point) -> bool:
        for box in obstacles_inflated:
            if _segment_intersects_box(a, b, box):
                return False
        return True

    def _walk_perpendicular(
        anchor: Point, lane_coord: float, init_offset: float, sign: int,
        axis_horizontal: bool,
    ) -> float:
        """Walk the perpendicular stub away from `anchor` until the
        stub segment from anchor to (lane on the other axis) clears every
        obstacle. axis_horizontal=True means the stub is VERTICAL (we move
        x). Returns the signed offset that produces a clean stub."""
        def _hits(off: float) -> bool:
            if axis_horizontal:
                x = anchor[0] + off
                return not _segment_clears_obstacles((x, anchor[1]), (x, lane_coord))
            y = anchor[1] + off
            return not _segment_clears_obstacles((anchor[0], y), (lane_coord, y))
        if not _hits(init_offset):
            return init_offset
        for k in range(1, 60):
            cand = init_offset + sign * lane_step * k
            if not _hits(cand):
                return cand
        return init_offset

    lane = _lane(channel_off)

    if horizontal:
        mid_y = (start[1] + end[1]) / 2
        above_seed = union_y1 - gap - lane
        below_seed = union_y2 + gap + lane
        # Try the closer side first, then the other, then a wide outward
        # walk on each side. The first candidate whose polyline clears all
        # obstacles wins; otherwise pick the one with the fewest hits.
        d_above = abs(mid_y - above_seed); d_below = abs(mid_y - below_seed)
        if d_above < d_below:
            ordered = [(above_seed, -1, "above"), (below_seed, +1, "below")]
        else:
            ordered = [(below_seed, +1, "below"), (above_seed, -1, "above")]

        best_poly: list[Point] | None = None
        best_hits = float("inf")
        x_lo = min(start[0], end[0]); x_hi = max(start[0], end[0])
        for seed_y, bias, _name in ordered:
            detour_y = _find_free_lane(seed_y, x_lo, x_hi, claimed_h_lanes, min_sep, lane_step, bias)
            # Try a few outward shifts of detour_y if needed.
            for extra in range(0, 8):
                cand_y = detour_y + bias * lane_step * extra
                src_offset, tgt_offset = 0.0, 0.0
                if src_side in ("left", "right"):
                    sign = 1 if src_side == "right" else -1
                    src_x_init = start[0] + sign * ext
                    y_lo = min(start[1], cand_y); y_hi = max(start[1], cand_y)
                    src_x = _find_free_lane(src_x_init, y_lo, y_hi, claimed_v_lanes, min_sep, lane_step, sign)
                    src_x = _walk_perpendicular(start, cand_y, src_x - start[0], sign, True) + start[0]
                    src_offset = src_x - start[0]
                if tgt_side in ("left", "right"):
                    sign = -1 if tgt_side == "left" else 1
                    tgt_x_init = end[0] + sign * ext
                    y_lo = min(cand_y, end[1]); y_hi = max(cand_y, end[1])
                    tgt_x = _find_free_lane(tgt_x_init, y_lo, y_hi, claimed_v_lanes, min_sep, lane_step, sign)
                    tgt_x = _walk_perpendicular(end, cand_y, tgt_x - end[0], sign, True) + end[0]
                    tgt_offset = tgt_x - end[0]
                poly = _h_detour(start, end, cand_y, src_side, tgt_side, src_offset, tgt_offset)
                hits = sum(1 for box in obstacles_inflated for a, b in zip(poly, poly[1:]) if _segment_intersects_box(a, b, box))
                if hits == 0:
                    return poly
                if hits < best_hits:
                    best_hits = hits
                    best_poly = poly
        return best_poly

    # Vertical detour (start/end on top/bottom-dominated geometry)
    mid_x = (start[0] + end[0]) / 2
    left_seed = union_x1 - gap - lane
    right_seed = union_x2 + gap + lane
    d_left = abs(mid_x - left_seed); d_right = abs(mid_x - right_seed)
    if d_left < d_right:
        ordered_v = [(left_seed, -1, "left"), (right_seed, +1, "right")]
    else:
        ordered_v = [(right_seed, +1, "right"), (left_seed, -1, "left")]

    best_poly = None
    best_hits = float("inf")
    y_lo = min(start[1], end[1]); y_hi = max(start[1], end[1])
    for seed_x, bias, _name in ordered_v:
        detour_x = _find_free_lane(seed_x, y_lo, y_hi, claimed_v_lanes, min_sep, lane_step, bias)
        for extra in range(0, 8):
            cand_x = detour_x + bias * lane_step * extra
            src_offset, tgt_offset = 0.0, 0.0
            if src_side in ("top", "bottom"):
                sign = 1 if src_side == "bottom" else -1
                src_y_init = start[1] + sign * ext
                x_lo = min(start[0], cand_x); x_hi = max(start[0], cand_x)
                src_y = _find_free_lane(src_y_init, x_lo, x_hi, claimed_h_lanes, min_sep, lane_step, sign)
                src_y = _walk_perpendicular(start, cand_x, src_y - start[1], sign, False) + start[1]
                src_offset = src_y - start[1]
            if tgt_side in ("top", "bottom"):
                sign = -1 if tgt_side == "top" else 1
                tgt_y_init = end[1] + sign * ext
                x_lo = min(cand_x, end[0]); x_hi = max(cand_x, end[0])
                tgt_y = _find_free_lane(tgt_y_init, x_lo, x_hi, claimed_h_lanes, min_sep, lane_step, sign)
                tgt_y = _walk_perpendicular(end, cand_x, tgt_y - end[1], sign, False) + end[1]
                tgt_offset = tgt_y - end[1]
            poly = _v_detour(start, end, cand_x, src_side, tgt_side, src_offset, tgt_offset)
            hits = sum(1 for box in obstacles_inflated for a, b in zip(poly, poly[1:]) if _segment_intersects_box(a, b, box))
            if hits == 0:
                return poly
            if hits < best_hits:
                best_hits = hits
                best_poly = poly
    return best_poly


def _h_detour(
    start: Point, end: Point, detour_y: float,
    src_side: str, tgt_side: str,
    src_offset: float, tgt_offset: float,
) -> list[Point]:
    pts: list[Point] = [start]
    if src_side in ("left", "right"):
        # Stub x = start.x + src_offset (signed; may be shifted off
        # cluster borders by the caller).
        pts.append((start[0] + src_offset, start[1]))
        pts.append((start[0] + src_offset, detour_y))
    else:
        # Source vertical — go straight to detour_y at start.x
        pts.append((start[0], detour_y))
    if tgt_side in ("left", "right"):
        pts.append((end[0] + tgt_offset, detour_y))
        pts.append((end[0] + tgt_offset, end[1]))
    else:
        pts.append((end[0], detour_y))
    pts.append(end)
    return pts


def _v_detour(
    start: Point, end: Point, detour_x: float,
    src_side: str, tgt_side: str,
    src_offset: float, tgt_offset: float,
) -> list[Point]:
    pts: list[Point] = [start]
    if src_side in ("top", "bottom"):
        pts.append((start[0], start[1] + src_offset))
        pts.append((detour_x, start[1] + src_offset))
    else:
        pts.append((detour_x, start[1]))
    if tgt_side in ("top", "bottom"):
        pts.append((detour_x, end[1] + tgt_offset))
        pts.append((end[0], end[1] + tgt_offset))
    else:
        pts.append((detour_x, end[1]))
    pts.append(end)
    return pts


def _polyline_hits_any(polyline: list[Point], obstacles: list[tuple[int, int, int, int]], margin: int) -> bool:
    if not obstacles:
        return False
    for a, b in zip(polyline, polyline[1:]):
        for box in obstacles:
            inflated = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
            if _segment_intersects_box(a, b, inflated):
                return True
    return False


def _segment_intersects_box(a: Point, b: Point, box: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = box
    if max(a[0], b[0]) < x1 or min(a[0], b[0]) > x2:
        return False
    if max(a[1], b[1]) < y1 or min(a[1], b[1]) > y2:
        return False
    if x1 <= a[0] <= x2 and y1 <= a[1] <= y2:
        return True
    if x1 <= b[0] <= x2 and y1 <= b[1] <= y2:
        return True
    edges = [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]
    for p, q in edges:
        if _segments_cross(a, b, p, q):
            return True
    return False


def _segments_cross(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    def ccw(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def _center(node: dict[str, Any]) -> Point:
    return (float(node["x"]) + float(node["width"]) / 2, float(node["y"]) + float(node["height"]) / 2)


# ---------------------------------------------------------------------------
# Edge labels — white pill at polyline midpoint
# ---------------------------------------------------------------------------


def _crossings_on_polyline(polyline: list[Point], others: list[list[Point]]) -> list[Point]:
    """Compute the 2D intersection points where this polyline crosses any
    of the other polylines (one entry per crossing). The label routine
    uses these to push the pill off the crossing so neither edge is
    visually broken by the badge."""
    pts: list[Point] = []
    for a, b in zip(polyline, polyline[1:]):
        for other in others:
            for c, d in zip(other, other[1:]):
                if _segments_cross(a, b, c, d):
                    p = _segment_intersection(a, b, c, d)
                    if p:
                        pts.append(p)
    return pts


def _segment_intersection(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    x1, y1 = a; x2, y2 = b; x3, y3 = c; x4, y4 = d
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-6:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _draw_edge_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    polyline: list[Point],
    color: tuple[int, int, int],
    scale: int,
    node_boxes: list[tuple[int, int, int, int]] | None = None,
    crossings: list[Point] | None = None,
    placed_pills: list[tuple[float, float, float, float]] | None = None,
) -> tuple[float, float, float, float] | None:
    if len(polyline) < 2:
        return None
    font = scaled_font(13, scale, bold=True)
    # Use the actual glyph bbox (left/top/right/bottom) so we can position
    # the text by its visible silhouette, not by the bbox of an empty
    # baseline-anchored draw which would push the text downward.
    bbox = draw.textbbox((0, 0), label, font=font)
    glyph_w = bbox[2] - bbox[0]
    glyph_h = bbox[3] - bbox[1]
    pad_x = s(8, scale)
    pad_y = s(5, scale)
    half_w = glyph_w / 2 + pad_x
    half_h = glyph_h / 2 + pad_y

    anchor = _pick_label_anchor(
        polyline, half_w, half_h, node_boxes or [], crossings or [], placed_pills or []
    )
    box = (
        int(anchor[0] - half_w),
        int(anchor[1] - half_h),
        int(anchor[0] + half_w),
        int(anchor[1] + half_h),
    )
    draw.rounded_rectangle(box, radius=s(7, scale), fill=(255, 255, 255), outline=color, width=max(1, s(1, scale)))
    text_x = box[0] + ((box[2] - box[0]) - glyph_w) / 2 - bbox[0]
    text_y = box[1] + ((box[3] - box[1]) - glyph_h) / 2 - bbox[1]
    draw.text((text_x, text_y), label, font=font, fill=color)
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def _pick_label_anchor(
    polyline: list[Point],
    half_w: float,
    half_h: float,
    node_boxes: list[tuple[int, int, int, int]],
    crossings: list[Point],
    placed_pills: list[tuple[float, float, float, float]],
) -> Point:
    midpoint, _ = path_midpoint(polyline)
    samples = _sample_along_polyline(polyline, count=31)
    if not samples:
        return midpoint
    end_clear = max(half_w, half_h) * 1.6
    start_pt, end_pt = polyline[0], polyline[-1]
    mid_index = len(samples) // 2
    order = [mid_index]
    for offset in range(1, len(samples)):
        if mid_index - offset >= 0:
            order.append(mid_index - offset)
        if mid_index + offset < len(samples):
            order.append(mid_index + offset)

    def _too_close_to_end(anchor: Point) -> bool:
        return (
            math.hypot(anchor[0] - start_pt[0], anchor[1] - start_pt[1]) < end_clear
            or math.hypot(anchor[0] - end_pt[0], anchor[1] - end_pt[1]) < end_clear
        )

    def _ok(anchor: Point, allow_crossing: bool = False, allow_pill: bool = False) -> bool:
        if _too_close_to_end(anchor):
            return False
        pill = (anchor[0] - half_w, anchor[1] - half_h, anchor[0] + half_w, anchor[1] + half_h)
        if any(_box_overlaps(pill, b) for b in node_boxes):
            return False
        if not allow_crossing:
            for cx, cy in crossings:
                if pill[0] <= cx <= pill[2] and pill[1] <= cy <= pill[3]:
                    return False
        if not allow_pill:
            for prev in placed_pills:
                if not (pill[2] <= prev[0] or pill[0] >= prev[2] or pill[3] <= prev[1] or pill[1] >= prev[3]):
                    return False
        return True

    for idx in order:
        if _ok(samples[idx]):
            return samples[idx]
    for idx in order:
        if _ok(samples[idx], allow_pill=True):
            return samples[idx]
    for idx in order:
        if _ok(samples[idx], allow_crossing=True, allow_pill=True):
            return samples[idx]
    return midpoint


def _sample_along_polyline(polyline: list[Point], count: int) -> list[Point]:
    if len(polyline) < 2 or count < 2:
        return list(polyline)
    segs = [(a, b, math.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(polyline, polyline[1:])]
    total = sum(length for _, _, length in segs)
    if total <= 0:
        return [polyline[0]]
    samples: list[Point] = []
    for i in range(count):
        target = total * (i / (count - 1))
        travelled = 0.0
        for a, b, length in segs:
            if travelled + length >= target or (a, b, length) is segs[-1]:
                ratio = (target - travelled) / length if length > 0 else 0.0
                samples.append((a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio))
                break
            travelled += length
    return samples


def _box_overlaps(a: tuple[float, float, float, float], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])
