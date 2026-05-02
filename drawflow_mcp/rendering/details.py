"""Details PNG renderer: cards stacked into a tall, readable image."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..errors import RenderError
from . import markdown
from . import text as textlib
from .theme import (
    DETAILS_ANTIALIAS_FACTOR,
    PALETTE,
    scaled_font,
)


def s(value: int | float, scale: int) -> int:
    """Scale a logical pixel size to render-space pixels."""
    return max(1, int(round(float(value) * scale)))


def render_details_png(scene: dict[str, Any], output_path: Path) -> dict[str, int | bool]:
    try:
        return _render(scene, output_path)
    except Exception as exc:  # pragma: no cover - converted to tool error
        raise RenderError(f"Failed to render details PNG: {exc}") from exc


def _render(scene: dict[str, Any], output_path: Path) -> dict[str, int | bool]:
    width = int(scene["canvas"]["width"])
    output_scale = int(scene["canvas"].get("scale", 1))
    render_scale = max(output_scale, output_scale * DETAILS_ANTIALIAS_FACTOR)
    render_width = width * render_scale
    probe = Image.new("RGB", (render_width, 10), (255, 255, 255))
    probe_draw = ImageDraw.Draw(probe)
    card_width = render_width - s(96, render_scale)
    needed = _measure_total_height(probe_draw, scene, card_width, render_scale)
    auto_grow = bool(scene["canvas"].get("autoGrow", False))
    request_max = int(scene["canvas"].get("maxHeight", 4000)) * render_scale
    # `autoGrow=True` means: never truncate. `maxHeight` is treated as the
    # MINIMUM height (so the existing min-canvas semantics still hold), and
    # the canvas grows to fit `needed` even if that's bigger than maxHeight.
    if auto_grow:
        # Same absolute ceiling as the model's maxHeight upper bound so we
        # never produce a canvas wildly bigger than callers can opt into
        # explicitly. If even this isn't enough, the truncation banner kicks
        # back in.
        ceiling = 24000 * render_scale
        max_height = min(ceiling, max(request_max, needed))
    else:
        max_height = request_max
    height = max(min(needed, max_height), s(600, render_scale))
    truncated = needed > max_height

    image = Image.new("RGB", (render_width, height), PALETTE["background"])
    draw = ImageDraw.Draw(image)
    _draw_panel(draw, render_width, height, render_scale)
    _draw_header(draw, scene, render_width, render_scale)

    y = _header_bottom(render_scale)
    title_font = scaled_font(22, render_scale, bold=True)
    body_font = scaled_font(14, render_scale)
    muted_font = scaled_font(13, render_scale)
    card_x = s(48, render_scale)
    for section in scene["sections"]:
        if y + s(90, render_scale) > height:
            break
        draw.text((s(50, render_scale), y), section["title"], font=title_font, fill=PALETTE["ink"])
        y += s(42, render_scale)
        for card in section["cards"]:
            card_h = _card_height(draw, card, card_width, render_scale)
            if y + card_h + s(24, render_scale) > height:
                draw.text(
                    (s(50, render_scale), y),
                    "Truncated: increase details.maxHeight for the remaining items.",
                    font=body_font,
                    fill=(185, 28, 28),
                )
                truncated = True
                y = height
                break
            draw.rounded_rectangle(
                (card_x, y, card_x + card_width, y + card_h),
                radius=s(18, render_scale),
                fill=(248, 250, 252),
                outline=(203, 213, 225),
                width=s(1, render_scale),
            )
            draw.text(
                (s(70, render_scale), y + s(18, render_scale)),
                str(card.get("title", "")),
                font=scaled_font(18, render_scale, bold=True),
                fill=PALETTE["ink"],
            )
            if card.get("subtitle"):
                draw.text(
                    (s(70, render_scale), y + s(48, render_scale)),
                    str(card["subtitle"]),
                    font=muted_font,
                    fill=(13, 148, 136),
                )
            markdown.draw_markdown(
                draw,
                str(card.get("body", "")),
                s(70, render_scale),
                y + s(76, render_scale),
                card_width - s(44, render_scale),
                render_scale,
                PALETTE["muted"],
            )
            y += card_h + s(18, render_scale)
        y += s(18, render_scale)

    final_size = (width * output_scale, max(1, int(round(height / DETAILS_ANTIALIAS_FACTOR))))
    if image.size != final_size:
        image = image.resize(final_size, Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    logical_height = max(1, int(round(final_size[1] / output_scale)))
    return {"width": width, "height": logical_height, "scale": output_scale, "truncated": truncated}


def _measure_total_height(draw: ImageDraw.ImageDraw, scene: dict[str, Any], card_width: int, scale: int) -> int:
    y = _header_bottom(scale)
    for section in scene["sections"]:
        y += s(54, scale)
        for card in section["cards"]:
            y += _card_height(draw, card, card_width, scale) + s(18, scale)
    return y + s(48, scale)


def _header_bottom(scale: int) -> int:
    return s(150, scale)


def _card_height(draw: ImageDraw.ImageDraw, card: dict[str, str], width: int, scale: int) -> int:
    title_font = scaled_font(18, scale, bold=True)
    text_width = width - s(44, scale)
    title_lines = textlib.wrap(draw, str(card.get("title", "")), title_font, text_width)
    return s(66, scale) + len(title_lines) * s(26, scale) + markdown.measure_height(draw, str(card.get("body", "")), text_width, scale)


def _draw_panel(draw: ImageDraw.ImageDraw, width: int, height: int, scale: int) -> None:
    margin = s(24, scale)
    draw.rounded_rectangle(
        (margin, margin, width - margin, height - margin),
        radius=s(28, scale),
        fill=PALETTE["panel"],
        outline=PALETTE["panel_outline"],
        width=s(2, scale),
    )


def _draw_header(draw: ImageDraw.ImageDraw, scene: dict[str, Any], width: int, scale: int) -> None:
    title_font = scaled_font(30, scale, bold=True)
    body_font = scaled_font(14, scale)
    draw.text((s(48, scale), s(42, scale)), str(scene["title"]), font=title_font, fill=PALETTE["ink"])
    description = str(scene.get("description") or "")
    if description:
        textlib.draw_wrapped_block(
            draw,
            description,
            s(50, scale),
            s(92, scale),
            width - s(100, scale),
            body_font,
            PALETTE["muted"],
        )
