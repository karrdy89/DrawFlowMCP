# DrawFlow Diagram Skill

Use this skill when you need to create an architecture diagram, flowchart, or system relationship map through the DrawFlow MCP server.

## Output Contract

Call `create_diagram_png` once with one complete `GraphDocument`. The server returns two PNG download links:

- `graph` — concise architecture image (nodes, edges, arrows, short labels, clusters).
- `details` — readable detail image with full node/edge descriptions.

Each download URL points to exactly one PNG file. There are no ZIP, SVG, JSON, PDF, or `.drawio` outputs.

### Tool call signature

```jsonc
// Tool name: create_diagram_png
// Arguments (the GraphDocument is passed under "diagram", NOT at the top level):
{
  "diagram": { /* GraphDocument — see "GraphDocument Shape" below */ },
  "output": {                                            // optional
    "graph":   { "width": 2200, "height": 1300, "scale": 1 },
    "details": {
      "width": 1500,
      "maxHeight": 7000,                                 // 800 ≤ value ≤ 24000
      "scale": 1,
      "layout": "cards",
      "autoGrow": false                                  // see below
    }
  }
}
```

When `output.details.autoGrow` is `true`, the details canvas grows tall enough to fit every card (no truncation) — `maxHeight` becomes a *minimum* instead of a hard cap. Use this when the diagram has rich `detail` prose and you don't want to retry-with-bigger-maxHeight. There is still a 24000-logical-px absolute ceiling.

### Tool result shape

```jsonc
{
  "status": "ready",                            // or absent on isError
  "downloads": [
    { "role": "graph",   "artifactId": "dg_…", "format": "png", "url": "http://…/dg_….png", "contentType": "image/png", "image": { "width": 2200, "height": 1300, "scale": 1 } },
    { "role": "details", "artifactId": "dg_…", "format": "png", "url": "http://…/dg_….png", "contentType": "image/png", "image": { "width": 1500, "height": 7000, "scale": 1 } }
  ],
  "warnings": [ /* e.g. details-truncation notice; non-fatal */ ]
}
```

Pick the URL by role (`r["role"] == "graph"` / `"details"`); do not assume order. If the call fails, the result is `{"isError": true, "code": "...", "message": "...", "details": [...]}` instead.

If you get a `details PNG was truncated` warning, either pass `output.details.autoGrow: true` and retry (preferred — the canvas grows to fit), or raise `output.details.maxHeight` (e.g., `8000`–`12000`) and retry.

## How the rendering works (so you can author for it)

DrawFlow renders through a custom **Pillow + grandalf** pipeline (compound Sugiyama layout, port-based orthogonal edge routing, channel/lane allocation, crossing-edge color retinting). That has implications for what to expect:

- Layout, port assignment, edge routing, label placement, and cluster boxes are decided by the renderer. You don't position nodes yourself.
- Direction options (`LR`, `RL`, `TB`, `BT`) decide the rank flow.
- Edge `kind` controls line style and the default color (sync/data solid, async/control/dependency dashed; see palette below). You may override the line color for a specific edge with `style.strokeColor` (hex like `#cc3344`); this is honored and the crossing-color retint pass leaves user-pinned colors alone.
- Node `kind` controls shape (cylinder for database, hexagon for gateway, rhombus for decision, parallelogram for queue, rounded ellipse for actor, trapezoid for external, etc.).
- `position` and `waypoints` fields are accepted by the schema but ignored — the renderer always lays out the graph itself.

## Authoring Pattern

Think in this temporary pattern, then emit the final JSON:

```text
add_node(id="web", label="Web App", kind="service")
node_spec(id="web", summary="User UI", detail="Accepts user traffic and owns the browser session.")

add_node(id="api", label="API Gateway", kind="gateway")
node_spec(id="api", summary="Auth + routing", detail="Terminates public API traffic and enforces auth.")

add_edge(id="web_to_api", source="web", target="api", label="HTTPS", kind="sync")
edge_spec(id="web_to_api", detail="Public request path carrying the user JWT.")

add_cluster(id="ingress", label="Ingress", nodes=["web", "api"])
cluster_spec(id="ingress", summary="External entry path", detail="Browser-facing components.")
```

Submit one `GraphDocument` per tool call.

## Authoring Workflow

When the user asks for an architecture diagram, build an end-to-end flow rather than just listing modules:

1. Identify the diagram boundary and the **primary scenario** (one). Other scenarios become detail prose, not extra branches.
2. Add external actors/systems that initiate or consume the flow.
3. Add entry points (gateways, MCP tools, HTTP routes, CLIs, queues, schedulers).
4. Add application components that own meaningful behavior — not every helper.
5. Add validation/contract layers when they affect the interface or correctness.
6. Add data stores, artifact stores, caches, queues, and generated outputs.
7. Add edges in execution order so a reader can follow the request from start to finish.
8. Put protocols/transports in edge `label`. Put detailed behavior in edge `detail`.
9. Use node `summary` for the one-line graph-only responsibility, and full `detail` for the details PNG.
10. Review as a reader: every node should answer "what is this?", every edge "what moves here?".

## Density Budget

The renderer can fit any size graph but readability degrades fast past ~12 nodes. Target:

- **8–12 foreground nodes** for one diagram. Up to 16 only when the system genuinely has that many distinct, equally important roles.
- **≤ ~20 edges**. If you have more, you are probably modeling helper calls — drop them.
- If the user's description has more, pick the primary scenario and write the rest into `detail` prose. Do not add a node just to mention something.
- Drop "monitor" / "watcher" / "lambda triggered by" helpers when their only job is to forward a signal — fold them into the upstream node's `detail`.

## Cluster Rules

Clusters mark architectural regions. The layout engine places nodes inside their cluster's box; edges crossing cluster boundaries cost more in the layout, so cluster choice strongly affects the final picture.

- 3–5 clusters per diagram, 2–5 nodes each is the sweet spot.
- Clusters are **flat** — no nesting.
- A node belongs to at most one cluster. Nodes not listed in any cluster sit at the root level.
- Single-node clusters work but read as small boxes; only use them to mark a real boundary like "External Systems".

**Cluster cohesion rule.** A cluster is a region in the diagram, not a category in your head. Two nodes belong in the same cluster only when they sit next to each other in the data flow AND share a region. Counter-examples that look tempting but produce bad layouts:

- ❌ Putting customer-facing actor + admin user + on-call engineer in one "External Actors" cluster. They connect to opposite ends of the graph; clustering them forces long crossing edges.
- ❌ Putting an internal reader (admin dashboard) in the same cluster as third-party systems (Stripe, email, pager). They're all "downstream" but they don't sit next to each other.
- ✅ Leave actors at their natural starting position — uncluster them if they don't share a flow neighbour. Root-level nodes are fine.

## Returned Values and Back-Edges

If a response returns to the original actor, **do not** draw a back-edge unless the return path itself changes the architecture's shape. Back-edges (e.g., `email_provider → customer_app`) cause long lines that cross the rest of the diagram.

Instead:
- Represent the returned artifact as a `document` node placed near the producer (e.g., `Invoice Email` after `Email Provider`), or
- Describe the return path in the producer node's `detail`.

Reserve actual back-edges for cases where the return is a meaningful feedback loop (e.g., the actor gets a webhook callback that changes downstream system state).

A `document` artifact node belongs in the **producer's cluster** when the producer has one, because the artifact is part of that subsystem's output. Use `data` for the producer→document edge (it's an artifact write), reserving `async` for transport-mediated message flow.

## Folding Helper Nodes

Helpers whose only role is "forward a signal" should be folded into their upstream node's `detail`, not drawn:

- DLQ depth watchers / lambda-triggered alerters → fold into the queue node.
- Outbound pager / paging service when its only job is to reach the on-call → put the page directly on the alert edge from the queue/job to the on-call actor.
- An external sink kept solely as a labeled hop adds another box without changing the architecture; fold it.

Keep the external service as its own node only when it owns state, makes routing decisions, or is independently failure-relevant (e.g., Stripe owns the invoice).

## Multiple Unrelated Actors

When the system genuinely has multiple actors that connect to different parts of the graph (e.g., end-customer, admin, on-call), put each at root level — do not bundle them into one actors cluster. Their natural starting positions are what makes the diagram readable.

## Direction Rules

- `LR` for service architecture and request/data pipelines.
- `TB` for procedural flowcharts, decision flows, build pipelines.
- `BT` / `RL` only when the user asks or domain convention demands.

## Label Rules

Short labels in the graph image — the renderer draws edge labels as a small pill near the line.

Hard limits enforced by the renderer (so write under, not at, the limit):

| field | soft target | hard cap |
|---|---|---|
| Node `label` | 1–4 words, ≤ 24 chars | wraps to 2 lines, then **silently dropped** (no ellipsis); node width caps at 260pt |
| Node `summary` | ≤ 24 chars | truncated with `…` at 42 chars |
| Cluster `label` | 1–3 words | no truncation; one line of header bar |
| Cluster `summary` | ≤ 32 chars | truncated with `…` at 54 chars |
| Edge `label` | ≤ 12 chars | not truncated, but the pill grows and crowds the line — keep it short |

The 24-char soft target for node `summary` matches the point where extra characters stop expanding the node's width — past 24 chars the text gets thinner relative to the box.

Long explanations live in `detail`, never in `label` or `summary`.

## Edge Style Rules — Pick the Right Line Type

Pick the line type that matches the relationship's nature. Color follows from the choice by default; you may pin a specific color per edge via `style.strokeColor` (the crossing-color retint pass leaves pinned colors alone).

| line type | use for |
|---|---|
| solid (thin) | Direct, synchronous calls where the caller waits for a response — RPC, HTTP request/response, blocking query. Also type or inheritance relationships when the diagram shows class structure. |
| dashed | Decoupled or eventual paths — events, queues, async messages, orchestration / dispatch / policy decisions, soft compile-or-deploy dependencies. Anything where the sender does not wait. |
| thick solid | Data or artifact movement — bulk data transfer, file/document flow, persisted writes whose payload itself is the point. |

Bidirectional relationships: just create two edges. The renderer assigns separate ports.

## Node Kinds

Pick the kind that matches the role. The renderer's shape and color follow.

- `service` — application service, worker, orchestrator (rectangle).
- `database` — relational store, document store, cache (cylinder).
- `queue` — buffered async / FIFO / pub-sub topic / DLQ (parallelogram).
- `gateway` — ingress, router, dispatcher (hexagon).
- `actor` — human, agent, external caller; the start of a flow (stadium).
- `external` — third-party system you do not own (trapezoid).
- `decision` — branching policy or routing choice (rhombus).
- `document` — generated file, response payload, schema artifact, email, invoice (inverted trapezoid).
- `custom` — fallback when none of the above fits.

`container` is reserved for the renderer; do not use it as a node kind. Use `clusters` instead.

## Detail Rules

Every important node and edge should have a useful `detail`. The details PNG is the place for prose.

Node `detail` should explain:
- Responsibility
- Important runtime behavior
- State ownership, if any
- Security or reliability notes

Edge `detail` should explain:
- What flows across the relationship
- Why the relationship exists
- Directionality
- Important guarantees, retries, or failure behavior

`detail` may use a safe Markdown subset (rendered in the details PNG):
- Headings: `#`, `##`, `###`
- Bullets and ordered lists
- Blockquotes
- Fenced code blocks
- Inline code, bold, italic, and links as readable text

No raw HTML, no remote images.

## GraphDocument Shape

```json
{
  "version": "drawflow.graph/v1",
  "title": "Example Architecture",
  "description": "Short description of the diagram.",
  "type": "architecture",
  "direction": "LR",
  "nodes": [
    {
      "id": "web",
      "label": "Web App",
      "kind": "service",
      "summary": "User UI",
      "detail": "Accepts user traffic and renders the client UI."
    }
  ],
  "clusters": [
    {
      "id": "ingress",
      "label": "Ingress",
      "summary": "public path",
      "nodes": ["web", "api"],
      "detail": "Groups the public-facing nodes in one visible boundary."
    }
  ],
  "edges": [
    {
      "id": "web_to_api",
      "source": "web",
      "target": "api",
      "label": "HTTPS",
      "kind": "sync",
      "detail": "Browser-originated API calls carrying authenticated user context.",
      "style": {"strokeColor": "#cc3344"}
    }
  ]
}
```

## Final Check

Before calling the tool:

- Foreground node count is ≤ ~12 unless the user's domain genuinely demands more.
- No back-edge to the originating actor unless the return changes architecture shape — return artifacts are `document` nodes instead.
- Every cluster is a region in the picture, not a category. Unrelated actors are root-level, not bundled.
- Every edge `source` and `target` matches an existing node id.
- Node ids and edge ids are unique.
- Graph labels are short; long explanations live in `detail`.
- Each node has a `kind` that matches its role.
- Cluster membership covers every node you want grouped (clusters are flat, no nesting).
- The request will produce exactly two PNG files: `graph` and `details`.
