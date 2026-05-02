# DrawFlow MCP

[English](README.md) · [한국어](README.ko.md)

**Plug-in architecture-diagram generation for agents.** DrawFlow MCP exposes a single MCP tool that turns a declarative graph document into a clean, ready-to-share architecture PNG plus a markdown-rendered details sheet. The authoring rules, layout engine, edge router, and download endpoints all ship in one server — point your agent at it and ask for a diagram.

![KEDA autoscaling architecture](artifacts/e2e_keda_autogrow_graph.png)

## Why

LLMs can describe systems in prose all day, but turning that into a readable diagram still means hand-drawing in draw.io / Excalidraw / Mermaid, fiddling with positions, and exporting. DrawFlow MCP closes that loop:

- **One tool call, two PNGs.** Pass a `GraphDocument`; get a concise architecture image and a long-form details image.
- **The skill is bundled.** Agents can `GET` the authoring guide (`SKILL.md`) from the same server they call — density budgets, cluster cohesion rules, line-type semantics, character limits — so they author for the renderer instead of guessing.
- **Layout is automatic.** Compound Sugiyama (grandalf) handles ranks and clusters; an in-house orthogonal router with port-aware exit/entry points, per-edge channel allocation, obstacle-avoiding bends, and crossing-edge color retinting handles the wiring. No coordinates, no waypoints — just nodes, edges, and clusters.
- **Markdown details, capped or auto-grown.** Per-node and per-edge prose renders into a stacked card layout. Set `output.details.autoGrow=true` and the canvas grows to fit instead of truncating.
- **Single-process or split.** Run HTTP transport for one server that hosts both the MCP endpoint and the download routes, or stdio transport when you'd rather wire it into a Codex/IDE config.

## What's in the Box

- **MCP server** — `drawflow_mcp.server`, FastMCP-based, supports `http`, `streamable-http`, `sse`, and `stdio` transports.
- **Two tools** —
  - `get_drawflow_skill` returns the `SKILL.md` content inline (plus a download URL and SHA-256 for verification).
  - `create_diagram_png` accepts a `drawflow.graph/v1` document and returns two PNG download URLs.
- **Bundled skill** — `skills/drawflow/SKILL.md` is the authoring contract: tool input shape, density budget, cluster rules, line types, label limits, return shape, and `autoGrow` workaround for long detail prose.
- **Layout + render pipeline** — Pillow-based renderer with grandalf Sugiyama layout, port-routed orthogonal edges, lane-claim accumulator that prevents overlapping parallel runs, and CJK font support out of the box.
- **Download endpoints** — `/downloads/skills/drawflow/{version}/SKILL.md` serves the authoring contract; `/downloads/diagrams/{artifactId}.png` serves the rendered PNG. Artifact ids are 80-bit random hex, so URL enumeration isn't a concern.

## Requirements

- Python 3.11+
- `uv`

## Quickstart

```powershell
uv sync
uv run python -m drawflow_mcp.server --transport http --host 127.0.0.1 --port 8765
```

That's it. The server now hosts:

| Endpoint | Purpose |
|---|---|
| `http://127.0.0.1:8765/mcp/`                                          | MCP RPC (streamable-http transport) |
| `http://127.0.0.1:8765/downloads/skills/drawflow/<version>/SKILL.md`  | Authoring guide for agents |
| `http://127.0.0.1:8765/downloads/diagrams/<artifactId>.png`           | Rendered PNG (graph or details) |
| `http://127.0.0.1:8765/health`                                        | Liveness check |

`DRAWFLOW_PUBLIC_BASE_URL` is auto-derived from `--host`/`--port`. Pin it explicitly when reverse-proxying.

### Stdio transport

For tools that spawn the server over stdio (Codex, IDEs):

```powershell
$env:DRAWFLOW_PUBLIC_BASE_URL = "http://127.0.0.1:8765"
uv run python -m drawflow_mcp.server --transport stdio
```

In stdio mode the server has no HTTP listener of its own, so download URLs must point at a separately-running HTTP instance that shares the artifact directory.

## Connecting an Agent

Any MCP-aware client can mount the server. A minimal Codex / Claude-Desktop-style config:

```toml
[mcp_servers.drawflow]
command = "uv"
args = ["run", "python", "-m", "drawflow_mcp.server", "--transport", "stdio"]
env = { DRAWFLOW_PUBLIC_BASE_URL = "http://127.0.0.1:8765" }
```

Once mounted, the agent's playbook is:

1. Call `get_drawflow_skill` and read `skill.markdown` from the response (the authoring contract is inlined; `skill.downloadUrl` is also returned for clients that prefer fetching the file).
2. Author a `GraphDocument` per the skill (3–5 clusters, 8–12 foreground nodes, line types matching the relationship's nature, short labels, full prose under `detail`).
3. Call `create_diagram_png` with `{"diagram": GraphDocument, "output": {...}}`.
4. Hand the two URLs to the user.

## Tools

### `get_drawflow_skill`

```jsonc
// Arguments
{ "version": "latest", "client": "codex" }

// Result
{
  "skill": {
    "name": "drawflow-diagram",
    "version": "0.1.0",
    "downloadUrl": "http://.../downloads/skills/drawflow/0.1.0/SKILL.md",
    "sha256": "...",
    "markdown": "# DrawFlow Diagram Skill\n\nUse this skill when ..."  // full SKILL.md inline
  },
  "usage": "Use this skill to create DrawFlow Graph DSL, then call create_diagram_png."
}
```

The `markdown` field carries the full `SKILL.md` text inline, so an agent can read it without a separate HTTP fetch. The `downloadUrl` is still there for clients that prefer a streamed `text/markdown` response or want to verify against `sha256`.

### `create_diagram_png`

```jsonc
// Arguments
{
  "diagram": { /* drawflow.graph/v1 GraphDocument */ },
  "output": {
    "graph":   { "width": 2200, "height": 1300, "scale": 1 },
    "details": { "width": 1500, "maxHeight": 7000, "scale": 1, "autoGrow": true }
  }
}

// Result
{
  "status": "ready",
  "downloads": [
    { "role": "graph",   "url": "http://.../dg_….png", "image": { "width": 2200, "height": 1300, "scale": 1 } },
    { "role": "details", "url": "http://.../dg_….png", "image": { "width": 1500, "height": 5260, "scale": 1 } }
  ],
  "warnings": []
}
```

The full schema, label/character limits, line-type table, cluster cohesion rule, and back-edge handling rule live in `skills/drawflow/SKILL.md` — that file *is* the authoring contract.

## Docker

```powershell
docker compose up --build drawflow
```

The published image bundles Noto CJK fonts so Korean / Japanese / Chinese text renders inside PNGs in Linux containers.

## Project Layout

```
drawflow_mcp/
  server.py              — unified FastMCP entry (tools + custom_route downloads)
  pipeline.py            — validate → layout → render → URL
  models/                — Pydantic GraphDocument / OutputSpec contracts
  rendering/
    layered_layout.py    — compound Sugiyama via grandalf
    graph.py             — orthogonal port routing, channel/lane allocation
    details.py           — markdown-aware card layout (with autoGrow)
    shapes.py, arrows.py, text.py, theme.py
skills/drawflow/SKILL.md — bundled authoring contract
docs/design.md           — architecture & rendering notes
```

## License

[MIT](LICENSE)
