# DrawFlow MCP

DrawFlow MCP is a FastMCP stdio server that lets an agent turn a declared graph into two PNG files:

- `graph`: concise architecture diagram with short node and edge labels.
- `details`: readable node and edge detail sheet with a safe Markdown subset.

The server does not generate `.drawio`, SVG, PDF, JSON downloads, or bulk archives. Each returned URL points to exactly one PNG file.

## Requirements

- Python 3.11+
- `uv`

## Install

```powershell
uv sync
```

## Run The Server (HTTP transport, single process)

The MCP tool RPC and the PNG/skill download endpoints are served by ONE
FastMCP server. `--host`/`--port` derive `DRAWFLOW_PUBLIC_BASE_URL`
automatically when it isn't pinned.

```powershell
uv run python -m drawflow_mcp.server --transport http --host 127.0.0.1 --port 8765
```

- MCP endpoint: `http://127.0.0.1:8765/mcp/`
- Skill download: `http://127.0.0.1:8765/downloads/skills/drawflow/<version>/SKILL.md`
- PNG download: `http://127.0.0.1:8765/downloads/diagrams/<artifactId>.png`
- Health: `http://127.0.0.1:8765/health`

Artifact ids are random 80-bit hex strings, so URL enumeration is infeasible — the server does not require a separate signing secret.

## Run The Server (stdio transport, no downloads)

For Codex / IDE integrations that spawn the server over stdio. In this
mode the server has no HTTP listener of its own, so download URLs must
point at a separately-running HTTP instance that shares the artifact dir.

```powershell
$env:DRAWFLOW_PUBLIC_BASE_URL = "http://127.0.0.1:8765"
uv run python -m drawflow_mcp.server --transport stdio
```

## Tools

- `get_drawflow_skill_link`: returns the `SKILL.md` download URL and SHA-256.
- `create_diagram_png_download_links`: accepts a complete `drawflow.graph/v1` document and returns two single-file PNG download URLs.

The skill URL serves raw Markdown text (`text/markdown`) and does not use an attachment header. PNG URLs are attachment-style single-file downloads.

## Functional Test

```powershell
uv run python scripts/mcp_functional_test.py
```

The functional test starts the unified FastMCP HTTP server, calls both tools through `fastmcp.Client`, renders module-level and function-level architecture diagrams, and downloads both PNG files from the same server's `/downloads/...` routes.

The current design notes are in `docs/design.md`.

## Docker

```powershell
docker compose up --build drawflow
```

The image includes Noto CJK fonts so Korean text can render inside PNGs in Linux containers.
