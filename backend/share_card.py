from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
HEIGHT = 1080

BG = (6, 12, 22)
WHITE = (240, 240, 240)
GREY = (150, 160, 180)

GREEN = (34, 197, 94)
AMBER = (245, 158, 11)
RED = (239, 68, 68)

LOGO_CANDIDATES = [
    "backend/assets/secondcoach_logo.png",
    "backend/assets/logo.png",
    "backend/SecondCoach_logo.png",
    "SecondCoach_logo.png",
]


def load_font(size, bold=False):
    fonts = []
    if bold:
        fonts = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "DejaVuSans-Bold.ttf",
        ]
    else:
        fonts = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "DejaVuSans.ttf",
        ]

    for f in fonts:
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            continue

    return ImageFont.load_default()


def center(draw, text, y, font, color):
    box = draw.textbbox((0, 0), text, font=font)
    w = box[2] - box[0]
    x = (WIDTH - w) // 2
    draw.text((x, y), text, fill=color, font=font)


def load_logo():
    for candidate in LOGO_CANDIDATES:
        path = Path(candidate)
        if not path.exists():
            continue

        try:
            logo = Image.open(path).convert("RGBA")
        except Exception:
            continue

        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)

        return logo

    return None


def render_share_card(data):
    race = data["race"]
    pred = data["prediction"]
    status = data["status"]
    training = data["training"]

    predicted = pred["predicted_time"]
    goal = race["goal_time"]
    race_name = race["name"]

    minutes_vs_goal = int(pred.get("minutes_vs_goal", 0) or 0)
    if minutes_vs_goal < 0:
        delta_text = f"{abs(minutes_vs_goal)} min a favor del objetivo"
    elif minutes_vs_goal > 0:
        delta_text = f"{abs(minutes_vs_goal)} min por detrás del objetivo"
    else:
        delta_text = "En objetivo"

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

    draw.ellipse((-140, -120, 360, 380), fill=(10, 20, 36))
    draw.ellipse((760, -80, 1220, 340), fill=(8, 16, 30))
    draw.ellipse((140, 760, 980, 1380), fill=(8, 16, 28))

    big = load_font(160, True)
    mid = load_font(70, True)
    small = load_font(42)
    title_font = load_font(32, False)

    center(draw, "Predicción SecondCoach", 120, title_font, GREY)
    center(draw, predicted, 190, big, WHITE)

    subtitle = f"{race_name} · Objetivo {goal}"
    center(draw, subtitle, 395, small, GREY)

    center(draw, status_text, 520, mid, status_color)
    center(draw, delta_text, 620, small, GREY)

    draw.line((180, 710, WIDTH - 180, 710), fill=(28, 40, 62), width=3)

    metrics = f"{avg} km/sem · {long_run} km tirada larga · {mp} km MP"
    center(draw, metrics, 760, small, WHITE)

    logo = load_logo()
    if logo is not None:
        max_w = 220
        scale = max_w / logo.width
        new_h = max(1, int(logo.height * scale))
        logo = logo.resize((max_w, new_h), Image.LANCZOS)

        img_rgba = img.convert("RGBA")
        x = (WIDTH - max_w) // 2
        y = 850
        img_rgba.alpha_composite(logo, (x, y))
        img = img_rgba.convert("RGB")

    buffer = BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()