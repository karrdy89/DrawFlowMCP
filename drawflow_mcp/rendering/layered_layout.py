"""Compound Sugiyama layout backed by grandalf.

Graphviz's ``cluster`` attribute and ELK's hierarchical layouts both treat
each cluster as an *opaque box* in the global layered pass and lay the
children out *inside* that box independently. We do the same here:

  1. For each cluster, run Sugiyama on its members + the edges entirely
     inside the cluster. The result is a self-contained block of nodes
     with cluster-local coordinates.
  2. For nodes not in any cluster, do the same as one extra block.
  3. Run a second Sugiyama on a *meta graph* whose vertices are the
     blocks (cluster boxes + free-node group) and whose edges are the
     original cross-cluster edges projected onto block ids. This
     decides where each block sits relative to the others.
  4. Stamp the children's local coordinates back into world space using
     each block's chosen position.
  5. Compute each cluster's bbox from its children + our padding.

Why compound instead of one big Sugiyama: when every cluster member goes
through the global layered pass together, members from different clusters
end up sharing ranks and the cluster boxes overlap. With compound layout
the cluster boxes never overlap because they are themselves the vertices
in the global pass.
"""
from __future__ import annotations

from typing import Any

from grandalf.graphs import Edge, Graph, Vertex
from grandalf.layouts import SugiyamaLayout

from .shapes import intrinsic_size


# Tunables — match the visual density of the previous hand-rolled layout.
CANVAS_LEFT = 60
CANVAS_TOP = 130
CONTAINER_HEADER_PAD = 84
CONTAINER_SIDE_PAD = 28
CONTAINER_BOTTOM_PAD = 32
CLUSTER_GAP = 110     # gap between two cluster blocks in the meta graph
NODE_XSPACE = 170     # extra horizontal margin between nodes in same rank
NODE_YSPACE = 130     # extra vertical margin between ranks
META_XSPACE = 200     # extra horizontal margin between cluster blocks
META_YSPACE = 150     # extra vertical margin between cluster blocks
FREE_GROUP_ID = "__free__"


class _NodeView:
    """grandalf reads ``view.w``/``view.h`` and writes back ``view.xy``."""

    __slots__ = ("w", "h", "xy")

    def __init__(self, w: float, h: float) -> None:
        self.w = w
        self.h = h
        self.xy: tuple[float, float] | None = None


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def layout_nodes(diagram: dict[str, Any], graph_output: dict[str, Any]) -> list[dict[str, Any]]:
    direction = str(diagram.get("direction", "LR"))
    horizontal = direction in ("LR", "RL")

    nodes = [_prepare_node(node) for node in diagram["nodes"]]
    cluster_specs = diagram.get("clusters") or []
    _apply_cluster_membership(nodes, cluster_specs)
    cluster_nodes = _cluster_container_nodes(cluster_specs)

    # 1) Group nodes by their (possibly absent) parent cluster.
    by_id = {n["id"]: n for n in nodes}
    blocks: list[_Block] = []
    block_for_node: dict[str, str] = {}
    for cluster in cluster_specs:
        members = [by_id[m] for m in cluster.get("nodes", []) if m in by_id]
        if not members:
            continue
        block = _build_block(cluster["id"], members, diagram["edges"], horizontal)
        blocks.append(block)
        for m in members:
            block_for_node[m["id"]] = cluster["id"]
    free_members = [n for n in nodes if n["id"] not in block_for_node]
    if free_members:
        block = _build_block(FREE_GROUP_ID, free_members, diagram["edges"], horizontal)
        blocks.append(block)
        for m in free_members:
            block_for_node[m["id"]] = FREE_GROUP_ID

    # 2) Run Sugiyama inside each block.
    for block in blocks:
        _layout_block(block)
        # If the user asked for LR/RL we fed grandalf swapped axes; flip back.
        _finalize_block_axes(block, horizontal)
        block.compute_size()

    # 3) Build a meta graph of blocks connected by cross-block edges.
    block_pos = _layout_meta_graph(blocks, diagram["edges"], block_for_node, horizontal)

    # 4) Stamp world coordinates back into our internal node dicts.
    for block in blocks:
        ox, oy = block_pos[block.id]
        for node, (lx, ly) in block.children_xy.items():
            world = by_id[node]
            world["x"] = int(round(ox + lx))
            world["y"] = int(round(oy + ly))

    # Place container bboxes from member positions *before* shifting, so the
    # canvas-origin shift moves containers and members together — otherwise
    # the cluster header strip ends up above the title bar.
    all_nodes = nodes + cluster_nodes
    _position_clusters(all_nodes)
    _shift_all_to_origin(all_nodes)
    return all_nodes


# ---------------------------------------------------------------------------
# Block: cluster-local Sugiyama result
# ---------------------------------------------------------------------------


class _Block:
    """A laid-out group of nodes — either a cluster's children or the
    free-node group. Carries local coordinates relative to the block's
    own (0, 0) corner plus the block's overall size.
    """

    __slots__ = ("id", "members", "vertices", "edges", "children_xy", "width", "height")

    def __init__(self, id: str, members: list[dict[str, Any]]) -> None:
        self.id = id
        self.members = members
        self.vertices: dict[str, Vertex] = {}
        self.edges: list[Edge] = []
        self.children_xy: dict[str, tuple[float, float]] = {}
        self.width = 0.0
        self.height = 0.0

    def compute_size(self) -> None:
        if not self.children_xy:
            self.width = 200.0
            self.height = 120.0
            return
        right = max(lx + self._member(node).get("width", 0) for node, (lx, _) in self.children_xy.items())
        bottom = max(ly + self._member(node).get("height", 0) for node, (_, ly) in self.children_xy.items())
        self.width = float(right)
        self.height = float(bottom)

    def _member(self, node_id: str) -> dict[str, Any]:
        return next(m for m in self.members if m["id"] == node_id)


def _build_block(block_id: str, members: list[dict[str, Any]], all_edges: list[dict[str, Any]], horizontal: bool) -> _Block:
    block = _Block(block_id, members)
    member_ids = {m["id"] for m in members}
    for member in members:
        v = Vertex(member["id"])
        # grandalf reserves room around each vertex according to view.w/h;
        # for LR/RL we feed it swapped axes since Sugiyama natively lays
        # out top-to-bottom and we'll flip back in _finalize_block_axes.
        if horizontal:
            v.view = _NodeView(member["height"], member["width"])
        else:
            v.view = _NodeView(member["width"], member["height"])
        block.vertices[member["id"]] = v
    for edge in all_edges:
        if edge["source"] in member_ids and edge["target"] in member_ids:
            block.edges.append(Edge(block.vertices[edge["source"]], block.vertices[edge["target"]]))
    return block


def _layout_block(block: _Block) -> None:
    if not block.vertices:
        return
    graph = Graph(list(block.vertices.values()), block.edges)
    next_origin = 0.0
    for component in graph.C:
        sug = SugiyamaLayout(component)
        sug.xspace = NODE_XSPACE
        sug.yspace = NODE_YSPACE
        sug.init_all()
        sug.draw()
        # Stamp the component's vertex coordinates with a y offset so
        # multiple disconnected components stack within the block.
        component_max_y = 0.0
        for vertex in component.sV:
            if not hasattr(vertex, "data") or vertex.view.xy is None:
                continue
            cx, cy = vertex.view.xy
            block.children_xy[vertex.data] = (cx, cy + next_origin)
            component_max_y = max(component_max_y, cy + next_origin + vertex.view.h / 2)
        next_origin = component_max_y + 60.0


def _finalize_block_axes(block: _Block, horizontal: bool) -> None:
    """Sugiyama centers each component around (0, 0) and (for LR layouts) we
    swapped width/height going in — undo both so the block's local
    coordinates have a (0, 0) top-left corner with widths/heights matching
    the original node sizes.
    """
    if not block.children_xy:
        return
    fixed: dict[str, tuple[float, float]] = {}
    for node_id, (cx, cy) in block.children_xy.items():
        if horizontal:
            cx, cy = cy, cx
        member = next(m for m in block.members if m["id"] == node_id)
        x = cx - member["width"] / 2
        y = cy - member["height"] / 2
        fixed[node_id] = (x, y)
    min_x = min(x for x, _ in fixed.values())
    min_y = min(y for _, y in fixed.values())
    block.children_xy = {nid: (x - min_x, y - min_y) for nid, (x, y) in fixed.items()}


# ---------------------------------------------------------------------------
# Meta graph: blocks connected by cross-block edges
# ---------------------------------------------------------------------------


def _layout_meta_graph(
    blocks: list[_Block],
    edges: list[dict[str, Any]],
    block_for_node: dict[str, str],
    horizontal: bool,
) -> dict[str, tuple[float, float]]:
    """Lay the blocks themselves out via Sugiyama and return their
    top-left positions in world coordinates.
    """
    if not blocks:
        return {}

    # Each block becomes a vertex sized to its content + the cluster
    # padding (so the meta layout reserves room for the cluster header
    # and side margins).
    vertices: dict[str, Vertex] = {}
    block_size: dict[str, tuple[float, float]] = {}
    for block in blocks:
        # The vertex's view dictates how much room grandalf reserves around
        # the block in the meta layout. We over-size each block by
        # CLUSTER_GAP so neighbouring clusters end up with a visible gutter
        # between them — otherwise grandalf packs the cluster boxes so
        # tightly that they overlap.
        if block.id == FREE_GROUP_ID:
            outer_w = block.width + CLUSTER_GAP
            outer_h = block.height + CLUSTER_GAP
        else:
            outer_w = block.width + 2 * CONTAINER_SIDE_PAD + CLUSTER_GAP
            outer_h = block.height + CONTAINER_HEADER_PAD + CONTAINER_BOTTOM_PAD + CLUSTER_GAP
        block_size[block.id] = (outer_w, outer_h)
        v = Vertex(block.id)
        if horizontal:
            v.view = _NodeView(outer_h, outer_w)
        else:
            v.view = _NodeView(outer_w, outer_h)
        vertices[block.id] = v

    meta_edges: list[Edge] = []
    seen_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        sb = block_for_node.get(edge["source"])
        tb = block_for_node.get(edge["target"])
        if sb is None or tb is None or sb == tb:
            continue
        pair = (sb, tb)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        meta_edges.append(Edge(vertices[sb], vertices[tb]))

    if not meta_edges:
        # No edges between blocks — just stack them along the flow axis.
        positions: dict[str, tuple[float, float]] = {}
        cursor = 0.0
        for block in blocks:
            outer_w, outer_h = block_size[block.id]
            if horizontal:
                origin = _block_origin(block, cursor, 0.0)
                positions[block.id] = origin
                cursor += outer_w + CLUSTER_GAP
            else:
                origin = _block_origin(block, 0.0, cursor)
                positions[block.id] = origin
                cursor += outer_h + CLUSTER_GAP
        return positions

    graph = Graph(list(vertices.values()), meta_edges)
    centers: dict[str, tuple[float, float]] = {}
    next_y = 0.0
    for component in graph.C:
        sug = SugiyamaLayout(component)
        sug.xspace = META_XSPACE
        sug.yspace = META_YSPACE
        sug.init_all()
        sug.draw()
        component_bottom = next_y
        for vertex in component.sV:
            if not hasattr(vertex, "data") or vertex.view.xy is None:
                continue
            cx, cy = vertex.view.xy
            if horizontal:
                cx, cy = cy, cx
            centers[vertex.data] = (cx, cy + next_y)
            outer_w, outer_h = block_size[vertex.data]
            component_bottom = max(component_bottom, cy + next_y + outer_h / 2)
        next_y = component_bottom + CLUSTER_GAP

    # Convert centers → top-left origins, accounting for padding so the
    # block's children sit *inside* the cluster header strip.
    positions: dict[str, tuple[float, float]] = {}
    for block in blocks:
        outer_w, outer_h = block_size[block.id]
        cx, cy = centers.get(block.id, (0.0, 0.0))
        positions[block.id] = _block_origin(block, cx - outer_w / 2, cy - outer_h / 2)
    return positions


def _block_origin(block: _Block, outer_x: float, outer_y: float) -> tuple[float, float]:
    """Convert a block's outer top-left to the inner content origin
    (where children's local (0,0) lands).

    The outer box is over-sized by CLUSTER_GAP (split equally on both
    sides) so neighbouring clusters get a visible gutter — we therefore
    inset by half the gap on the way in.
    """
    half_gap = CLUSTER_GAP / 2
    if block.id == FREE_GROUP_ID:
        return (outer_x + half_gap, outer_y + half_gap)
    return (outer_x + CONTAINER_SIDE_PAD + half_gap, outer_y + CONTAINER_HEADER_PAD + half_gap)


# ---------------------------------------------------------------------------
# Node + cluster prep
# ---------------------------------------------------------------------------


def _prepare_node(node: dict[str, Any]) -> dict[str, Any]:
    out = dict(node)
    default_w, default_h = intrinsic_size(out)
    size = out.get("size") or {}
    out["width"] = int(size.get("width", default_w))
    out["height"] = int(size.get("height", default_h))
    return out


def _apply_cluster_membership(nodes: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> None:
    by_id = {n["id"]: n for n in nodes}
    for cluster in clusters:
        for member_id in cluster.get("nodes", []):
            member = by_id.get(member_id)
            if member and not member.get("parent"):
                member["parent"] = cluster["id"]


def _cluster_container_nodes(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": cluster["id"],
            "label": cluster["label"],
            "kind": "container",
            "summary": cluster.get("summary", ""),
            "detail": cluster.get("detail", ""),
            "style": cluster.get("style", {}),
            "members": list(cluster.get("nodes", [])),
            "ref": f"C{index + 1}",
        }
        for index, cluster in enumerate(clusters)
    ]


def _shift_all_to_origin(nodes: list[dict[str, Any]]) -> None:
    """Shift everything so the *outermost* node (usually a container's
    top-left) sits at (CANVAS_LEFT, CANVAS_TOP). Members carry their
    container's _clusterZone, which we shift in lockstep.
    """
    placed = [n for n in nodes if "x" in n]
    if not placed:
        return
    min_x = min(int(n["x"]) for n in placed)
    min_y = min(int(n["y"]) for n in placed)
    dx = CANVAS_LEFT - min_x
    dy = CANVAS_TOP - min_y
    if dx == 0 and dy == 0:
        return
    for node in placed:
        node["x"] = int(node["x"]) + dx
        node["y"] = int(node["y"]) + dy
        zone = node.get("_clusterZone")
        if zone:
            zone["x"] = int(zone["x"]) + dx
            zone["y"] = int(zone["y"]) + dy


def _position_clusters(nodes: list[dict[str, Any]]) -> None:
    for container in [n for n in nodes if n.get("kind") == "container"]:
        members = [n for n in nodes if n.get("parent") == container["id"] and "x" in n]
        if not members:
            container["x"] = CANVAS_LEFT
            container["y"] = CANVAS_TOP
            container["width"] = 320
            container["height"] = 200
            continue
        min_x = min(int(m["x"]) for m in members) - CONTAINER_SIDE_PAD
        max_x = max(int(m["x"]) + int(m["width"]) for m in members) + CONTAINER_SIDE_PAD
        min_y = min(int(m["y"]) for m in members) - CONTAINER_HEADER_PAD
        max_y = max(int(m["y"]) + int(m["height"]) for m in members) + CONTAINER_BOTTOM_PAD
        container["x"] = int(min_x)
        container["y"] = int(min_y)
        container["width"] = int(max_x - min_x)
        container["height"] = int(max_y - min_y)
        zone = {
            "x": container["x"],
            "y": container["y"],
            "width": container["width"],
            "height": container["height"],
        }
        for member in members:
            member["_clusterZone"] = dict(zone)
