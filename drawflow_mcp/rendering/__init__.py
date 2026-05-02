"""DrawFlow rendering surface.

Two functions are public:

- ``render_graph_png`` — turn a graph scene into a PNG via Kroki/Mermaid.
- ``render_details_png`` — turn the details scene (markdown cards) into a
  PNG via the in-process Pillow renderer (the details image is a list of
  Markdown cards, which Kroki has no opinion on).
"""
from __future__ import annotations

from .details import render_details_png
from .graph import render_graph_png

__all__ = [
    "render_graph_png",
    "render_details_png",
]
