from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1920

BG = (6, 12, 22)
WHITE = (240, 240, 240)
GREY = (150, 160, 180)
PANEL = (13, 22, 38)
PANEL_2 = (18, 28, 46)
GREEN = (34, 197, 94)
AMBER = (245, 158, 11)
RED = (239, 68, 68)

LOGO_CANDIDATES = [
    "backend/assets/logo.png",
    "backend/SecondCoach_logo.png",
    "SecondCoach_logo.png",
]


def load_font(size, bold=False):
    candidates = []
    if bold:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "DejaVuSans.ttf",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    return ImageFont.load_default()


def text_width(draw, text, font):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def center(draw, text, y, font, color):
    w = text_width(draw, text, font)
    x = (WIDTH - w) / 2
    draw.text((x, y), text, fill=color, font=font)


def center_multiline(draw, text, y, font, color, max_width, line_gap=10):
    words = text.split()
    lines = []
    line = ""

    for word in words:
        test = f"{line} {word}".strip()
        if text_width(draw, test, font) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word

    if line:
        lines.append(line)

    for item in lines:
        center(draw, item, y, font, color)
        y += font.size + line_gap

    return y


def load_logo():
    for candidate in LOGO_CANDIDATES:
        path = Path(candidate)
        if not path.exists():
            continue

        try:
            logo = Image.open(path).convert("RGBA")
        except Exception:
            continue

        pixels = logo.load()

        for y in range(logo.height):
            for x in range(logo.width):
                r, g, b, a = pixels[x, y]
                if a > 0 and r > 240 and g > 240 and b > 240:
                    pixels[x, y] = (255, 255, 255, 0)

        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)

        return logo

    return None


def metric_card(draw, x1, y1, x2, y2, title, value):
    draw.rounded_rectangle((x1, y1, x2, y2), radius=26, fill=PANEL_2)

    title_font = load_font(28, False)
    value_font = load_font(40, True)

    draw.text((x1 + 26, y1 + 24), title, fill=GREY, font=title_font)
    draw.text((x1 + 26, y1 + 84), value, fill=WHITE, font=value_font)


def render_story_card(data):
    race = data["race"]
    pred = data["prediction"]
    status = data["status"]
    training = data["training"]

    predicted = pred["predicted_time"]
    goal = race["goal_time"]
    race_name = race["name"]

    avg = round(float(training["weekly_average_km"]), 1)
    long_run = round(float(training["long_run_km"]), 1)
    mp = round(float(training["goal_pace_block_km"]), 1)

    readiness = status.get("readiness")

    if readiness == "ahead":
        status_text = "POR DELANTE"
        status_color = GREEN
    elif readiness == "behind":
        status_text = "EN RIESGO"
        status_color = RED
    else:
        status_text = "EN LÍNEA"
        status_color = AMBER

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    draw.ellipse((-140, -40, 500, 520), fill=(10, 18, 32))
    draw.ellipse((700, 0, 1240, 520), fill=(8, 16, 30))
    draw.ellipse((120, 1400, 980, 2260), fill=(9, 16, 28))

    draw.rounded_rectangle((54, 120, WIDTH - 54, 1130), radius=38, fill=PANEL)

    big = load_font(205, True)
    mid = load_font(90, True)
    small = load_font(56, False)

    center(draw, predicted, 230, big, WHITE)

    subtitle = f"{race_name} · Objetivo {goal}"
    center_multiline(draw, subtitle, 540, small, GREY, 860, line_gap=8)

    center(draw, status_text, 740, mid, status_color)

    draw.line((180, 890, WIDTH - 180, 890), fill=(32, 46, 70), width=3)

    y1 = 980
    y2 = 1160
    gap = 22
    total_w = WIDTH - 108
    card_w = int((total_w - gap * 2) / 3)

    x1 = 54
    x2 = x1 + card_w
    metric_card(draw, x1, y1, x2, y2, "Km/sem", f"{avg}")

    x1 = x2 + gap
    x2 = x1 + card_w
    metric_card(draw, x1, y1, x2, y2, "Tirada larga", f"{long_run} km")

    x1 = x2 + gap
    x2 = x1 + card_w
    metric_card(draw, x1, y1, x2, y2, "Ritmo obj.", f"{mp} km")

    logo = load_logo()
    if logo is not None:
        max_w = 170
        scale = max_w / logo.width
        new_h = max(1, int(logo.height * scale))
        logo = logo.resize((max_w, new_h), Image.LANCZOS)

        img_rgba = img.convert("RGBA")
        x = (WIDTH - max_w) // 2
        y = 1490
        img_rgba.alpha_composite(logo, (x, y))
        img = img_rgba.convert("RGB")

    buffer = BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()