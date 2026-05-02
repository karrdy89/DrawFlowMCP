"""Theme — palette, fonts, kind→color mappings.

Single source of truth for the diagram look. The renderer never invents a
color or font itself; everything reads off this module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

from PIL import ImageFont


Color = tuple[int, int, int]


PALETTE: Final[dict[str, Color]] = {
    "background": (244, 247, 252),
    "panel": (255, 255, 255),
    "panel_outline": (220, 226, 236),
    "ink": (15, 23, 42),
    "muted": (71, 85, 105),
    "border": (30, 41, 59),
    "container_fill": (247, 250, 254),
    "container_border": (148, 163, 184),
    "container_label": (51, 65, 85),
    "ref_badge": (15, 23, 42),
    "ref_badge_text": (255, 255, 255),
    "container_ref_badge": (100, 116, 139),
}


NODE_FILLS: Final[dict[str, Color]] = {
    "service": (224, 234, 254),
    "database": (211, 244, 224),
    "queue": (253, 240, 184),
    "gateway": (255, 224, 195),
    "actor": (236, 222, 253),
    "external": (220, 228, 240),
    "decision": (252, 219, 219),
    "document": (215, 238, 252),
    "container": (247, 250, 254),
    "custom": (224, 234, 254),
}


# Edge defaults per kind. ``line`` is solid/dashed/dotted; ``width`` is the
# logical stroke width before scale; ``color`` is the canonical color.
EDGE_STYLES: Final[dict[str, dict[str, object]]] = {
    "sync":        {"color": (30, 41, 59),    "line": "solid",  "width": 3},
    "async":       {"color": (37, 99, 235),   "line": "dashed", "width": 3},
    "data":        {"color": (13, 148, 136),  "line": "solid",  "width": 4},
    "control":     {"color": (124, 58, 237),  "line": "dashed", "width": 3},
    "dependency":  {"color": (100, 116, 139), "line": "dotted", "width": 3},
    "inheritance": {"color": (190, 24, 93),   "line": "solid",  "width": 3},
    "custom":      {"color": (30, 41, 59),    "line": "solid",  "width": 3},
}


GRAPH_ANTIALIAS_FACTOR: Final[int] = 3
DETAILS_ANTIALIAS_FACTOR: Final[int] = 2


_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    preferred = "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf"
    for path in (preferred, *_FONT_CANDIDATES):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def scaled_font(size: int, scale: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return font(max(1, int(size * scale)), bold=bold)


def node_fill(kind: str) -> Color:
    return NODE_FILLS.get(kind, NODE_FILLS["service"])


def edge_defaults(kind: str) -> dict[str, object]:
    return EDGE_STYLES.get(kind, EDGE_STYLES["sync"])
