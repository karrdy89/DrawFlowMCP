"""High-level entry points wired to the FastMCP tools.

This is the only module the MCP layer needs to call. It stitches together
validation, layout, scene building, rendering, and signed download URLs.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from . import __version__, config
from .errors import ArtifactStoreError, ValidationError
from .models import (
    CreateDiagramPngDownloadLinksResponse,
    GraphDocument,
    OutputSpec,
    SkillLinkResponse,
)
from .rendering import render_details_png, render_graph_png
from .scenes import details_scene, diagram_to_internal, graph_scene


def get_drawflow_skill_link(version: str = "latest", client: str = "codex") -> dict[str, Any]:
    path = config.skill_path(version)
    sha = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
    download_version = __version__ if version == "latest" else version
    response = SkillLinkResponse.model_validate({
        "skill": {
            "name": "drawflow-diagram",
            "version": __version__,
            "client": client,
            "downloadUrl": f"{config.public_base_url()}/downloads/skills/drawflow/{download_version}/SKILL.md",
            "sha256": sha,
            "expiresAt": None,
        },
        "usage": "Use this skill to create DrawFlow Graph DSL, then call create_diagram_png_download_links.",
    })
    return response.model_dump(mode="json")


def create_diagram_png_download_links(
    diagram: GraphDocument | dict[str, Any],
    output: OutputSpec | dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagram_model = _parse_diagram(diagram)
    output_model = _parse_output(output)
    _validate_limits(diagram_model, output_model)

    diagram_data = diagram_to_internal(diagram_model)
    output_data = output_model.model_dump(mode="json")
    warnings: list[str] = []

    graph_payload = graph_scene(diagram_data, output_data["graph"])
    details_payload = details_scene(diagram_data, output_data["details"])

    diagram_id = f"dg_{uuid.uuid4().hex[:20]}"
    artifact_dir = config.artifact_dir()
    graph_path = artifact_dir / f"{diagram_id}_graph.png"
    details_path = artifact_dir / f"{diagram_id}_details.png"

    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        graph_image = render_graph_png(graph_payload, graph_path)
        details_image = render_details_png(details_payload, details_path)
        if details_image.get("truncated"):
            warnings.append(
                "Details PNG was truncated because output.details.maxHeight was too small for all node and edge details."
            )
    except OSError as exc:
        raise ArtifactStoreError(f"Failed to write diagram artifacts: {exc}") from exc

    expires_epoch = int(time.time()) + config.ttl_seconds()
    expires_at = (
        datetime.fromtimestamp(expires_epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    response = CreateDiagramPngDownloadLinksResponse.model_validate({
        "diagramId": diagram_id,
        "status": "ready",
        "expiresAt": expires_at,
        "downloads": [
            _download_descriptor("graph", f"{diagram_id}_graph", expires_epoch, graph_image),
            _download_descriptor("details", f"{diagram_id}_details", expires_epoch, details_image),
        ],
        "warnings": warnings,
    })
    return response.model_dump(mode="json")


def _parse_diagram(value: GraphDocument | dict[str, Any]) -> GraphDocument:
    if isinstance(value, GraphDocument):
        return value
    try:
        return GraphDocument.model_validate(value)
    except PydanticValidationError as exc:
        raise ValidationError("Invalid GraphDocument", _pydantic_details(exc)) from exc


def _parse_output(value: OutputSpec | dict[str, Any] | None) -> OutputSpec:
    if isinstance(value, OutputSpec):
        return value
    try:
        return OutputSpec.model_validate(value or {})
    except PydanticValidationError as exc:
        raise ValidationError("Invalid output options", _pydantic_details(exc)) from exc


def _pydantic_details(exc: PydanticValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()))
        details.append({"path": f"$.{loc}" if loc else "$", "message": str(error.get("msg", "Invalid value"))})
    return details


def _validate_limits(diagram: GraphDocument, output: OutputSpec) -> None:
    rendered_node_count = len(diagram.nodes) + len(diagram.clusters)
    if rendered_node_count > config.max_nodes():
        raise ValidationError(
            f"node count exceeds {config.max_nodes()}",
            [{"path": "$.nodes", "message": "Too many nodes"}],
        )
    if len(diagram.edges) > config.max_edges():
        raise ValidationError(
            f"edge count exceeds {config.max_edges()}",
            [{"path": "$.edges", "message": "Too many edges"}],
        )
    for width, height, scale, path in [
        (output.graph.width, output.graph.height, output.graph.scale, "output.graph"),
        (output.details.width, output.details.maxHeight, output.details.scale, "output.details"),
    ]:
        if width * height * scale * scale > config.max_canvas_pixels():
            raise ValidationError(
                f"{path} exceeds max canvas pixels",
                [{"path": f"$.{path}", "message": "Canvas too large"}],
            )


def _download_descriptor(role: str, artifact_id: str, expires_epoch: int, canvas: dict[str, Any]) -> dict[str, Any]:
    url = f"{config.public_base_url()}/downloads/diagrams/{artifact_id}.png"
    return {
        "role": role,
        "artifactId": artifact_id,
        "format": "png",
        "url": url,
        "contentType": "image/png",
        "image": {
            "width": int(canvas["width"]),
            "height": int(canvas.get("height", canvas.get("maxHeight", 0))),
            "scale": int(canvas.get("scale", 1)),
        },
    }
