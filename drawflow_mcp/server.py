"""Unified FastMCP server: tool RPC + download HTTP routes on one transport.

Replaces the previous split (`mcp_stdio.py` for tools + `http_server.py` for
downloads). The download routes are mounted via `@mcp.custom_route` so the
single FastMCP HTTP server hosts both the MCP protocol endpoint and the
download endpoints.

Usage:
  python -m drawflow_mcp.server --transport http --host 0.0.0.0 --port 8765
  python -m drawflow_mcp.server --transport stdio   # tools only, no downloads

When transport is HTTP/SSE and DRAWFLOW_PUBLIC_BASE_URL is unset, the server
infers it from --host/--port so generated download URLs match the bind
address. For stdio mode the env var is required (the server has no HTTP
listener of its own — operators run a separate download proxy).
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import sys
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from . import __version__, config
from .errors import DrawFlowError
from .pipeline import create_diagram_png as create_links
from .pipeline import get_drawflow_skill as get_skill_link


ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


mcp = FastMCP(
    name="drawflow-mcp",
    version=__version__,
    instructions=(
        "Render DrawFlow Graph DSL documents into two PNG files: a concise graph image "
        "and a details image. Every returned download URL points to exactly one PNG file. "
        "Agents should first call get_drawflow_skill, read the returned Markdown skill, "
        "and then call create_diagram_png with a complete GraphDocument."
    ),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool
def get_drawflow_skill(version: str = "latest", client: str = "codex") -> dict[str, Any]:
    """Return the DrawFlow skill URL; the URL serves raw SKILL.md Markdown text."""
    return get_skill_link(version=version, client=client)


@mcp.tool
def create_diagram_png(
    diagram: dict[str, Any],
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render graph/details PNG links. First call get_drawflow_skill and read the skill for DSL and visual-label rules."""
    try:
        return create_links(diagram=diagram, output=output)
    except DrawFlowError as exc:
        return {
            "isError": True,
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }


# ---------------------------------------------------------------------------
# Download routes (HTTP transports only — ignored when running over stdio)
# ---------------------------------------------------------------------------


@mcp.custom_route("/downloads/skills/drawflow/{version}/SKILL.md", methods=["GET"])
async def serve_skill(request: Request) -> Response:
    version = request.path_params.get("version", "latest")
    path = config.skill_path(version)
    if not path.exists():
        return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)
    data = path.read_bytes()
    return Response(
        content=data,
        status_code=HTTPStatus.OK,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=300",
            "X-DrawFlow-Version": __version__,
        },
    )


@mcp.custom_route("/downloads/diagrams/{filename}", methods=["GET"])
async def serve_png(request: Request) -> Response:
    filename = request.path_params.get("filename", "")
    if not filename.endswith(".png"):
        return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)
    artifact_id = filename[: -len(".png")]
    if not ARTIFACT_ID_PATTERN.match(artifact_id):
        return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)
    file_path = (config.artifact_dir() / filename).resolve()
    if not _is_relative_to(file_path, config.artifact_dir()) or not file_path.exists():
        return PlainTextResponse("not found", status_code=HTTPStatus.NOT_FOUND)
    return Response(
        content=file_path.read_bytes(),
        status_code=HTTPStatus.OK,
        media_type=mimetypes.types_map.get(".png", "image/png"),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=86400",
        },
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> Response:
    return PlainTextResponse(
        f"drawflow-mcp {__version__} ok",
        status_code=HTTPStatus.OK,
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="DrawFlow unified MCP + download server")
    parser.add_argument("--transport", default=os.environ.get("DRAWFLOW_TRANSPORT", "http"),
                        choices=["http", "sse", "streamable-http", "stdio"],
                        help="MCP transport (default: http)")
    parser.add_argument("--host", default=os.environ.get("DRAWFLOW_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DRAWFLOW_PORT", "8765")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
        return

    # Auto-derive the public base URL from the bind address if the operator
    # didn't pin it. The download routes live on the SAME server, so URLs
    # the tools hand back must point at this host:port.
    if not os.environ.get("DRAWFLOW_PUBLIC_BASE_URL"):
        host_for_url = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        os.environ["DRAWFLOW_PUBLIC_BASE_URL"] = f"http://{host_for_url}:{args.port}"

    mcp.run(
        transport=args.transport,
        host=args.host,
        port=args.port,
        show_banner=False,
    )


if __name__ == "__main__":
    main()
