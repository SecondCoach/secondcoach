import io
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw, ImageFont

from backend.db import get_user_by_athlete_id
from backend.strava_auth import refresh_access_token_if_needed

router = APIRouter()

ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
LAPS_URL_TEMPLATE = "https://www.strava.com/api/v3/activities/{activity_id}/laps"


def _load_font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _compute_training(runs: list[dict]) -> tuple[float, float, float]:
    now = datetime.now(timezone.utc)
    last_7_cutoff = now - timedelta(days=7)
    last_28_cutoff = now - timedelta(days=28)

    km_last_7_days = 0.0
    km_last_28_days = 0.0
    long_run_km = 0.0

    for run in runs:
        distance_km = float(run.get("distance", 0.0)) / 1000.0
        start_date = _parse_datetime(run.get("start_date"))

        if distance_km > long_run_km:
            long_run_km = distance_km

        if start_date:
            if start_date >= last_7_cutoff:
                km_last_7_days += distance_km
            if start_date >= last_28_cutoff:
                km_last_28_days += distance_km

    weekly_average_km = km_last_28_days / 4.0
    return round(km_last_7_days, 1), round(weekly_average_km, 1), round(long_run_km, 1)


def _seconds_from_hms(hms: str) -> int:
    parts = hms.split(":")
    if len(parts) != 2:
        return 0
    minutes = int(parts[0])
    seconds = int(parts[1])
    return minutes * 60 + seconds


def _goal_pace_window(goal_time: str) -> tuple[float, float]:
    # Para 3:30 -> 4:45–5:05 /km
    if goal_time == "3:30":
        return 285.0, 305.0
    # fallback prudente
    return 285.0, 305.0


def _detect_goal_pace_block_km_from_laps(runs: list[dict], headers: dict, goal_time: str) -> float:
    low_sec_per_km, high_sec_per_km = _goal_pace_window(goal_time)
    total_km = 0.0

    for run in runs[:60]:
        activity_id = run.get("id")
        if not activity_id:
            continue

        try:
            resp = requests.get(
                LAPS_URL_TEMPLATE.format(activity_id=activity_id),
                headers=headers,
                timeout=20,
            )
            if resp.status_code != 200:
                continue

            laps = resp.json()
            if not isinstance(laps, list):
                continue

            for lap in laps:
                dist_m = float(lap.get("distance", 0.0))
                moving_s = float(lap.get("moving_time", 0.0))

                if dist_m < 900 or moving_s <= 0:
                    continue

                pace_sec_per_km = moving_s / (dist_m / 1000.0)

                if low_sec_per_km <= pace_sec_per_km <= high_sec_per_km:
                    total_km += dist_m / 1000.0

        except Exception:
            continue

    return round(total_km, 1)


def _safe_probability(goal_pace_block_km: float, avg_week: float, long_km: float) -> int:
    score = 45

    score += min(20, int(goal_pace_block_km / 3))
    score += min(15, int(avg_week / 5))
    score += min(15, int(long_km / 2))

    return max(35, min(95, score))


def _guess_goal_time(user: dict) -> str:
    return user.get("goal_time") or "3:30"


def _guess_predicted_time(
    avg_week: float,
    long_km: float,
    goal_pace_block_km: float,
    goal_time: str,
) -> str:
    if goal_time == "3:30":
        if goal_pace_block_km >= 50 and avg_week >= 50 and long_km >= 24:
            return "3:27"
        if goal_pace_block_km >= 35 and avg_week >= 42 and long_km >= 22:
            return "3:30"
        if avg_week >= 38 and long_km >= 20:
            return "3:34"
        return "3:39"
    return goal_time


def _generate_share_card(goal_time: str, predicted_time: str, probability: int) -> Image.Image:
    width = 1200
    height = 630

    bg = (15, 15, 15)
    white = (255, 255, 255)
    soft = (190, 190, 190)
    green = (0, 220, 120)
    orange = (255, 106, 0)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    font_title = _load_font(68)
    font_label = _load_font(42)
    font_big = _load_font(118)
    font_mid = _load_font(52)
    font_small = _load_font(30)

    draw.text((70, 60), f"¿Estoy listo para {goal_time}?", fill=white, font=font_title)
    draw.text((70, 170), "SecondCoach dice:", fill=soft, font=font_label)
    draw.text((70, 250), predicted_time, fill=green, font=font_big)
    draw.text((70, 410), f"{probability}% de probabilidad", fill=white, font=font_mid)

    draw.rounded_rectangle((70, 515, 540, 585), radius=18, fill=(28, 28, 28))
    draw.text((95, 533), "Analiza tu objetivo en", fill=white, font=font_small)
    draw.text((370, 533), "SecondCoach", fill=orange, font=font_small)

    draw.text((70, 595), "secondcoach.onrender.com", fill=soft, font=font_small)

    return img


@router.get("/share/{athlete_id}.png")
def share_public_card(athlete_id: int):
    user: Optional[dict] = get_user_by_athlete_id(athlete_id)

    if not user:
        return HTMLResponse("<h1>Runner no encontrado</h1>", status_code=404)

    try:
        user = refresh_access_token_if_needed(user)
        headers = {"Authorization": f"Bearer {user['access_token']}"}

        response = requests.get(
            ACTIVITIES_URL,
            headers=headers,
            params={"per_page": 200},
            timeout=30,
        )
        response.raise_for_status()

        acts = response.json()
        if not isinstance(acts, list):
            return HTMLResponse("<h1>Respuesta inesperada de Strava</h1>", status_code=502)

        runs = [a for a in acts if a.get("type") == "Run"]

        km_7, avg_week, long_km = _compute_training(runs)
        goal_time = _guess_goal_time(user)

        # Si falla el análisis fino de laps, no rompemos la tarjeta.
        try:
            goal_pace_block_km = _detect_goal_pace_block_km_from_laps(runs, headers, goal_time)
        except Exception:
            goal_pace_block_km = 0.0

        predicted_time = _guess_predicted_time(avg_week, long_km, goal_pace_block_km, goal_time)
        probability = _safe_probability(goal_pace_block_km, avg_week, long_km)

        img = _generate_share_card(goal_time, predicted_time, probability)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        return Response(content=buffer.getvalue(), media_type="image/png")

    except requests.RequestException:
        return HTMLResponse("<h1>Error leyendo datos de Strava</h1>", status_code=502)
    except Exception:
        return HTMLResponse("<h1>Error generando la tarjeta</h1>", status_code=500)