import logging
import os
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from backend.views.share_helpers import _compact_goal_context_from_payload, _share_colors_from_payload

logger = logging.getLogger("secondcoach")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.png")

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[str] = []

    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue

    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        trial = f"{current} {word}"
        bbox = draw.textbbox((0, 0), trial, font=font)
        trial_width = bbox[2] - bbox[0]
        if trial_width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def _load_logo_image(size: int) -> Image.Image | None:
    if not os.path.exists(ICON_PATH):
        return None

    try:
        logo = Image.open(ICON_PATH).convert("RGBA")
        logo.thumbnail((size, size), Image.LANCZOS)
        return logo
    except Exception:
        logger.exception("No se pudo cargar el logo")
        return None


def _draw_story_gradient(width: int, height: int, start_hex: str, end_hex: str) -> Image.Image:
    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    start = _hex_to_rgb(value=start_hex)
    end = _hex_to_rgb(value=end_hex)

    img = Image.new("RGB", (width, height), start_hex)
    px = img.load()

    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(start[0] + (end[0] - start[0]) * ratio)
        g = int(start[1] + (end[1] - start[1]) * ratio)
        b = int(start[2] + (end[2] - start[2]) * ratio)
        for x in range(width):
            px[x, y] = (r, g, b)

    return img


def _render_share_png(data: dict[str, Any]) -> bytes:
    one_line = data.get("one_line") or {}
    headline = str(one_line.get("headline") or "")
    subline = str(one_line.get("subline") or "")
    action = str(one_line.get("action") or "")
    chip = str(one_line.get("chip") or "SECONDCOACH")
    compact_goal_context = _compact_goal_context_from_payload(data)

    # =========================
    # MOTIVO VISUAL (AUTO)
    # =========================
    def _chip_reason(chip: str) -> str:
        c = chip.upper()
        if c == "FATIGA ALTA": return "Carga reciente demasiado alta"
        if c == "POR DETRÁS": return "Tu nivel actual está por debajo del objetivo"
        if c == "CERCA": return "Falta continuidad o especificidad"
        if c == "EN OBJETIVO": return "Trabajo específico suficiente"
        if c == "POR DELANTE": return "Tu nivel actual está por encima del objetivo"
        return ""

    short_goal_product_evidence = data.get("short_goal_product_evidence") or []
    reason_text = str(short_goal_product_evidence[0]) if short_goal_product_evidence else _chip_reason(chip)

    bg_color, card_color, accent_color = _share_colors_from_payload(data)

    width = 1080
    height = 1350
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # barra superior de estado
    draw.rectangle([0, 0, width, 18], fill=accent_color)

    card_margin_x = 70
    card_top = 100
    card_bottom = 1250
    card_radius = 34

    draw.rounded_rectangle(
        [card_margin_x, card_top, width - card_margin_x, card_bottom],
        radius=card_radius,
        fill=card_color,
        outline="#22345f",
        width=2,
    )

    inner_left = card_margin_x + 64
    inner_right = width - card_margin_x - 64
    inner_width = inner_right - inner_left

    chip_font = _load_font(30, bold=True)
    chip_bbox = draw.textbbox((0, 0), chip, font=chip_font)
    chip_w = chip_bbox[2] - chip_bbox[0]
    chip_h = chip_bbox[3] - chip_bbox[1]
    chip_x = inner_left
    chip_y = card_top + 42

    draw.rounded_rectangle(
        [chip_x, chip_y, chip_x + chip_w + 60, chip_y + chip_h + 26],
        radius=24,
        fill=accent_color,
    )
    draw.text((chip_x + 30, chip_y + 12), chip, font=chip_font, fill="white")

    headline_font = _load_font(72, bold=True)
    context_font = _load_font(28, bold=False)
    reason_font = _load_font(32, bold=True)
    subline_font = _load_font(36, bold=False)
    action_font = _load_font(40, bold=True)
    brand_font = _load_font(34, bold=True)

    y = chip_y + chip_h + 88

    if compact_goal_context:
        context_lines = _wrap_text(draw, compact_goal_context, context_font, inner_width)
        for line in context_lines:
            draw.text((inner_left, y), line, font=context_font, fill="#c8d2ea")
            bbox = draw.textbbox((inner_left, y), line, font=context_font)
            y += (bbox[3] - bbox[1]) + 6
        y += 26

    if reason_text:
        reason_lines = _wrap_text(draw, reason_text, reason_font, inner_width)
        for line in reason_lines:
            draw.text((inner_left, y), line, font=reason_font, fill="#9fb3ff")
            bbox = draw.textbbox((inner_left, y), line, font=reason_font)
            y += (bbox[3] - bbox[1]) + 6
        y += 24

    for block_text, font, fill, gap_after, line_gap in [
        (headline, headline_font, "white", 40, 8),
        (subline, subline_font, "#c8d2ea", 46, 8),
        (action, action_font, "white", 0, 8),
    ]:
        lines = _wrap_text(draw, block_text, font, inner_width)
        for line in lines:
            draw.text((inner_left, y), line, font=font, fill=fill)
            bbox = draw.textbbox((inner_left, y), line, font=font)
            y += (bbox[3] - bbox[1]) + line_gap
        y += gap_after

    logo = _load_logo_image(176)
    footer_y = card_bottom - 108
    text_x = inner_left

    if logo is not None:
        logo_y = footer_y - 30
        img.paste(logo, (inner_left, logo_y), logo)
        text_x = inner_left + logo.width + 32

    draw.text(
        (text_x, footer_y + 42),
        "SecondCoach",
        font=brand_font,
        fill="#FC4C02",
    )

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_share_story_png(data: dict[str, Any]) -> bytes:
    one_line = data.get("one_line") or {}
    headline = str(one_line.get("headline") or "")
    subline = str(one_line.get("subline") or "")
    action = str(one_line.get("action") or "")
    chip = str(one_line.get("chip") or "SECONDCOACH")
    compact_goal_context = _compact_goal_context_from_payload(data)

    def _chip_reason(chip: str) -> str:
        c = chip.upper()
        if c == "FATIGA ALTA": return "Carga reciente demasiado alta"
        if c == "POR DETRÁS": return "Tu nivel actual está por debajo del objetivo"
        if c == "CERCA": return "Falta continuidad o especificidad"
        if c == "EN OBJETIVO": return "Trabajo específico suficiente"
        if c == "POR DELANTE": return "Tu nivel actual está por encima del objetivo"
        return ""

    short_goal_product_evidence = data.get("short_goal_product_evidence") or []
    reason_text = str(short_goal_product_evidence[0]) if short_goal_product_evidence else _chip_reason(chip)

    bg_color, card_color, accent_color = _share_colors_from_payload(data)

    width = 1080
    height = 1920
    img = _draw_story_gradient(width, height, bg_color, "#020816")
    draw = ImageDraw.Draw(img)

    # barra superior de estado
    draw.rectangle([0, 0, width, 14], fill=accent_color)

    card_left = 64
    card_top = 180
    card_right = width - 64
    card_bottom = height - 320
    draw.rounded_rectangle(
        [card_left, card_top, card_right, card_bottom],
        radius=42,
        fill=card_color,
        outline="#22345f",
        width=2,
    )

    inner_left = card_left + 72
    inner_right = card_right - 72
    inner_width = inner_right - inner_left

    chip_font = _load_font(34, bold=True)
    chip_bbox = draw.textbbox((0, 0), chip, font=chip_font)
    chip_w = chip_bbox[2] - chip_bbox[0]
    chip_h = chip_bbox[3] - chip_bbox[1]
    chip_x = inner_left
    chip_y = card_top + 54

    draw.rounded_rectangle(
        [chip_x, chip_y, chip_x + chip_w + 72, chip_y + chip_h + 30],
        radius=28,
        fill=accent_color,
    )
    draw.text((chip_x + 36, chip_y + 14), chip, font=chip_font, fill="white")

    headline_font = _load_font(86, bold=True)
    context_font = _load_font(30, bold=False)
    reason_font = _load_font(36, bold=True)
    subline_font = _load_font(42, bold=False)
    action_font = _load_font(48, bold=True)
    evidence_font = _load_font(34, bold=False)
    brand_font = _load_font(40, bold=True)

    y = chip_y + chip_h + 108

    if compact_goal_context:
        context_lines = _wrap_text(draw, compact_goal_context, context_font, inner_width)
        for line in context_lines:
            draw.text((inner_left, y), line, font=context_font, fill="#c8d2ea")
            bbox = draw.textbbox((inner_left, y), line, font=context_font)
            y += (bbox[3] - bbox[1]) + 8
        y += 30

    if reason_text:
        reason_lines = _wrap_text(draw, reason_text, reason_font, inner_width)
        for line in reason_lines:
            draw.text((inner_left, y), line, font=reason_font, fill="#9fb3ff")
            bbox = draw.textbbox((inner_left, y), line, font=reason_font)
            y += (bbox[3] - bbox[1]) + 8
        y += 30

    for block_text, font, fill, gap_after, line_gap in [
        (headline, headline_font, "white", 58, 12),
        (subline, subline_font, "#c8d2ea", 66, 10),
        (action, action_font, "white", 0, 10),
    ]:
        lines = _wrap_text(draw, block_text, font, inner_width)
        for line in lines:
            draw.text((inner_left, y), line, font=font, fill=fill)
            bbox = draw.textbbox((inner_left, y), line, font=font)
            y += (bbox[3] - bbox[1]) + line_gap
        y += gap_after

    extra_evidence_text = str(short_goal_product_evidence[1]) if len(short_goal_product_evidence) > 1 else ""
    if extra_evidence_text:
        y += 28
        extra_lines = _wrap_text(draw, extra_evidence_text, evidence_font, inner_width)
        for line in extra_lines:
            draw.text((inner_left, y), line, font=evidence_font, fill="#9fb3ff")
            bbox = draw.textbbox((inner_left, y), line, font=evidence_font)
            y += (bbox[3] - bbox[1]) + 8

    logo = _load_logo_image(176)
    footer_y = card_bottom - 132
    text_x = inner_left

    if logo is not None:
        logo_y = footer_y - 30
        img.paste(logo, (inner_left, logo_y), logo)
        text_x = inner_left + logo.width + 24

    draw.text(
        (text_x, footer_y + 42),
        "SecondCoach",
        font=brand_font,
        fill="#FC4C02",
    )

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()

