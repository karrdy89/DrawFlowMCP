"""Scene builders: turn a validated GraphDocument into render input."""
from __future__ import annotations

from typing import Any

from .models import GraphDocument


def diagram_to_internal(diagram: GraphDocument) -> dict[str, Any]:
    """Flatten Pydantic models into JSON-friendly dicts and assign refs."""
    nodes: list[dict[str, Any]] = []
    for index, node in enumerate(diagram.nodes):
        data = node.model_dump(mode="json")
        data["ref"] = f"N{index + 1}"
        nodes.append(data)
    edges: list[dict[str, Any]] = []
    for index, edge in enumerate(diagram.edges):
        data = edge.model_dump(mode="json")
        data["ref"] = f"E{index + 1}"
        edges.append(data)
    return {
        "version": diagram.version,
        "title": diagram.title,
        "description": diagram.description,
        "type": diagram.type,
        "direction": diagram.direction,
        "theme": diagram.theme,
        "layout": diagram.layout,
        "nodes": nodes,
        "edges": edges,
        "clusters": [cluster.model_dump(mode="json") for cluster in diagram.clusters],
        "specs": [spec.model_dump(mode="json") for spec in diagram.specs],
        "metadata": diagram.metadata,
    }


def graph_scene(
    diagram: dict[str, Any],
    graph_output: dict[str, Any],
) -> dict[str, Any]:
    """Bundle the diagram + canvas options into the shape ``render_graph_png``
    expects. Layout/positioning is no longer pre-computed here — Mermaid
    handles it once Kroki receives the converted source.
    """
    return {
        "role": "graph",
        "title": diagram["title"],
        "description": diagram.get("description", ""),
        "canvas": {
            "width": graph_output["width"],
            "height": graph_output["height"],
            "scale": graph_output["scale"],
            "transparentBackground": graph_output.get("transparentBackground", False),
        },
        "diagram": diagram,
    }


def details_scene(diagram: dict[str, Any], details_output: dict[str, Any]) -> dict[str, Any]:
    """Build the section/card structure used by the details renderer."""
    node_cards = [
        {
            "title": f"{node['ref']}  {node['label']}",
            "subtitle": f"id={node['id']} | kind={node['kind']}",
            "body": node.get("detail") or "No detail provided.",
        }
        for node in diagram["nodes"]
    ]
    edge_cards = [
        {
            "title": f"{edge['ref']}  {edge['source']} -> {edge['target']}",
            "subtitle": _edge_subtitle(edge),
            "body": edge.get("detail") or "No detail provided.",
        }
        for edge in diagram["edges"]
    ]
    spec_cards = [
        {
            "title": spec.get("title") or f"{spec['targetType']} detail",
            "subtitle": f"target={spec.get('targetId') or '(diagram)'}",
            "body": spec.get("markdown") or "No detail provided.",
        }
        for spec in diagram.get("specs", [])
    ]
    cluster_cards = [
        {
            "title": f"C{index + 1}  {cluster['label']}",
            "subtitle": f"id={cluster['id']} | nodes={', '.join(cluster.get('nodes', []))}",
            "body": cluster.get("detail") or cluster.get("summary") or "No detail provided.",
        }
        for index, cluster in enumerate(diagram.get("clusters", []))
    ]
    sections = [
        {"title": "Nodes", "cards": node_cards},
        {"title": "Edges", "cards": edge_cards},
    ]
    if cluster_cards:
        sections.insert(1, {"title": "Clusters", "cards": cluster_cards})
    if spec_cards:
        sections.append({"title": "Additional Details", "cards": spec_cards})
    return {
        "role": "details",
        "title": f"{diagram['title']} - Details",
        "description": diagram.get("description", ""),
        "canvas": {
            "width": details_output["width"],
            "maxHeight": details_output["maxHeight"],
            "scale": details_output["scale"],
            "autoGrow": details_output.get("autoGrow", False),
        },
        "sections": sections,
    }


def _edge_subtitle(edge: dict[str, Any]) -> str:
    arrow = edge.get("arrow") or {}
    style = edge.get("style") or {}
    parts = [
        f"id={edge['id']}",
        f"label={edge.get('label') or '(none)'}",
        f"kind={edge['kind']}",
        f"arrow={arrow.get('start', 'none')}->{arrow.get('end', 'classic')}",
    ]
    if style.get("lineStyle") or style.get("strokeColor") or style.get("strokeWidth"):
        descriptors: list[str] = []
        if style.get("lineStyle"):
            descriptors.append(f"line={style['lineStyle']}")
        if style.get("strokeColor"):
            descriptors.append(f"color={style['strokeColor']}")
        if style.get("strokeWidth"):
            descriptors.append(f"width={style['strokeWidth']}")
        parts.append("style=" + ",".join(descriptors))
    return " | ".join(parts)
