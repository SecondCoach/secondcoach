import io
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont
from starlette.middleware.sessions import SessionMiddleware

from backend.cache import get_cache, set_cache
from backend.db import get_user_by_athlete_id, init_db, upsert_user
from backend.settings import settings
from backend.strava_auth import refresh_access_token_if_needed
from backend.strava_segments import detect_goal_pace_lap_blocks, total_block_km

from backend.share_public import router as share_public_router

app = FastAPI()
app.include_router(share_public_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.APP_SESSION_SECRET)

init_db()

ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

DISTANCES = {
    "10k": 10.0,
    "half": 21.097,
    "marathon": 42.195,
}

RACE_NAMES = {
    "10k": "10K",
    "half": "Media Maratón",
    "marathon": "Maratón de Zaragoza",
}


def _to_minutes(t: str) -> int:
    parts = t.split(":")
    if len(parts) != 2:
        raise ValueError(f"Formato de tiempo no válido: {t}")
    h, m = parts
    return int(h) * 60 + int(m)


def _fmt(m: int) -> str:
    h = int(m // 60)
    mm = int(m % 60)
    return f"{h}:{mm:02d}"


def get_current_user(request: Request):
    session_user = request.session.get("user")

    if not session_user:
        return None

    athlete_id = session_user.get("strava_athlete_id")
    if not athlete_id:
        return None

    return get_user_by_athlete_id(athlete_id)


def detect_quality_blocks(runs):
    blocks = []

    for act in runs:
        distance_km = act.get("distance", 0) / 1000
        moving = act.get("moving_time", 0)

        if moving <= 0 or distance_km <= 0:
            continue

        pace = (moving / 60) / distance_km

        if distance_km >= 0.8 and pace < 5.0:
            blocks.append((distance_km, pace))

    return blocks


def compute_training(runs):
    now = datetime.now(timezone.utc)

    km_7 = sum(
        a.get("distance", 0)
        for a in runs
        if (now - datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))).days <= 7
    ) / 1000

    km_28 = sum(
        a.get("distance", 0)
        for a in runs
        if (now - datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))).days <= 28
    ) / 1000

    avg_week = round(km_28 / 4, 1) if km_28 else 0.0

    long_km = max(
        (
            a.get("distance", 0)
            for a in runs
            if (now - datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))).days <= 28
        ),
        default=0,
    ) / 1000

    return km_7, avg_week, long_km


def compute_prediction(distance, avg_week, long_km, quality_blocks):
    base_pb = _to_minutes("3:34")

    vol_bonus = max(0, avg_week - 40) * 0.35
    lr_bonus = max(0, long_km - 24) * 0.8

    quality_bonus = 0
    if quality_blocks:
        best_block = min(quality_blocks, key=lambda x: x[1])
        quality_bonus = max(0, 5 - best_block[1]) * 3

    pred_marathon = base_pb - vol_bonus - lr_bonus - quality_bonus

    ratio = distance / 42.195
    pred = pred_marathon * ratio

    low = int(round(pred - 3))
    high = int(round(pred + 4))

    return int(round(pred)), low, high


def get_cached_activities(user: dict, per_page: int = 20):
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    cache_key = f"activities_{user['strava_athlete_id']}_{per_page}"

    acts = get_cache(cache_key, ttl_seconds=600)
    if acts is not None:
        return acts, None

    response = requests.get(
        ACTIVITIES_URL,
        headers=headers,
        params={"per_page": per_page},
        timeout=30,
    )

    if response.status_code == 429:
        return None, "rate_limited"

    response.raise_for_status()
    acts = response.json()
    set_cache(cache_key, acts)
    return acts, None


def get_common_analysis(request: Request, user: dict):
    acts, error = get_cached_activities(user, per_page=20)
    if error == "rate_limited":
        return None, "rate_limited"

    runs = [a for a in acts if a.get("type") == "Run"]

    km_7, avg_week, long_km = compute_training(runs)
    quality_blocks = detect_quality_blocks(runs)

    race_type = request.session.get("race_type", "marathon")
    goal_time = request.session.get("goal_time", "3:30")
    race_date = request.session.get("race_date", "2026-04-12")

    goal_h, goal_m = map(int, goal_time.split(":"))
    target_pace_sec = ((goal_h * 3600) + (goal_m * 60)) / 42.195

    lap_blocks = detect_goal_pace_lap_blocks(
        access_token=user["access_token"],
        runs=runs[:12],
        target_pace_sec=target_pace_sec,
        tolerance_sec=20,
        min_block_km=2.0,
    )
    lap_block_km = total_block_km(lap_blocks)

    distance = DISTANCES[race_type]
    pred, low, high = compute_prediction(distance, avg_week, long_km, quality_blocks)

    pace = pred / distance
    pace_min = int(pace)
    pace_sec = int((pace % 1) * 60)

    goal_min = _to_minutes(goal_time)
    diff = pred - goal_min

    target_weekly = 65 if race_type == "marathon" else 50 if race_type == "half" else 40
    target_long = 30 if race_type == "marathon" else 18 if race_type == "half" else 12

    if diff <= 0:
        coach_message = "Vas en línea con tu objetivo."
        readiness = "on_track"
        readiness_label = "En línea con el objetivo"
    elif diff <= 5:
        coach_message = "Estás cerca, pero aún falta consolidar."
        readiness = "close"
        readiness_label = "Cerca del objetivo"
    else:
        coach_message = "Aún falta carga para asegurar el objetivo."
        readiness = "needs_work"
        readiness_label = "Aún falta consolidar"

    if lap_block_km < 5:
        coach_detail = (
            f"Pocos km en bloques por series/laps cerca de ritmo maratón ({lap_block_km:.1f} km). "
            f"Intenta acumular 10–15 km/sem cerca de tu ritmo objetivo."
        )
        specificity = "low"
    elif lap_block_km < 12:
        coach_detail = (
            f"Buen progreso: {lap_block_km:.1f} km recientes en bloques por series/laps cerca de ritmo maratón."
        )
        specificity = "medium"
    else:
        coach_detail = (
            f"Excelente: {lap_block_km:.1f} km recientes en bloques por series/laps cerca de ritmo maratón, "
            f"indicador fuerte para el objetivo."
        )
        specificity = "high"

    if diff <= -3:
        probability = 82
    elif diff <= 0:
        probability = 72
    elif diff <= 5:
        probability = 58
    else:
        probability = 38

    if lap_block_km >= 40:
        probability = min(96, probability + 12)
    elif lap_block_km >= 20:
        probability = min(92, probability + 8)
    elif lap_block_km >= 10:
        probability = min(88, probability + 5)

    return {
        "runs": runs,
        "km_7": round(km_7, 1),
        "avg_week": round(avg_week, 1),
        "long_km": round(long_km, 1),
        "quality_blocks": quality_blocks,
        "lap_blocks": lap_blocks,
        "lap_block_km": lap_block_km,
        "race_type": race_type,
        "race_date": race_date,
        "goal_time": goal_time,
        "pred": pred,
        "low": low,
        "high": high,
        "pace_min": pace_min,
        "pace_sec": pace_sec,
        "pred_time": _fmt(pred),
        "diff": diff,
        "probability": probability,
        "coach_message": coach_message,
        "coach_detail": coach_detail,
        "readiness": readiness,
        "readiness_label": readiness_label,
        "specificity": specificity,
        "target_weekly": target_weekly,
        "target_long": target_long,
    }, None


@app.get("/login")
def login():
    url = (
        f"{STRAVA_AUTHORIZE_URL}"
        f"?client_id={settings.STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={settings.STRAVA_REDIRECT_URI}"
        f"&scope=read,activity:read_all"
    )
    return RedirectResponse(url)


@app.get("/callback")
def callback(request: Request, code: str):
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()

    athlete = token_data.get("athlete", {})
    athlete_id = athlete.get("id")

    if not athlete_id:
        return HTMLResponse("<h1>Error obteniendo athlete_id de Strava</h1>", status_code=400)

    upsert_user(
        strava_athlete_id=athlete_id,
        username=athlete.get("username"),
        firstname=athlete.get("firstname"),
        lastname=athlete.get("lastname"),
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
    )

    request.session["user"] = {
        "strava_athlete_id": athlete_id,
    }

    return RedirectResponse("/dashboard")


@app.get("/dashboard")
def dashboard(request: Request):
    user = get_current_user(request)

    if not user:
        return HTMLResponse("<a href='/login'>Login con Strava</a>")

    user = refresh_access_token_if_needed(user)

    analysis, error = get_common_analysis(request, user)
    if error == "rate_limited":
        return HTMLResponse(
            "<h1>Strava está limitando temporalmente las peticiones (429)</h1>"
            "<p>Espera unos minutos y recarga el dashboard.</p>",
            status_code=429,
        )

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial, sans-serif; background:#f5f5f5; padding:40px; }}
            .card {{ background:white; padding:30px; border-radius:12px; max-width:900px; }}
            .button {{
                display:inline-block;
                margin-top:16px;
                padding:12px 18px;
                border-radius:10px;
                text-decoration:none;
                background:#ff5a1f;
                color:white;
                font-weight:bold;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>SecondCoach</h1>

            <p>{RACE_NAMES[analysis["race_type"]]} · {analysis["race_date"]} · Objetivo {analysis["goal_time"]}</p>

            <h2>Predicción</h2>
            <p>{analysis["pred_time"]} (≈ {analysis["pace_min"]}:{analysis["pace_sec"]:02d}/km)</p>
            <p>Rango {_fmt(analysis["low"])} – {_fmt(analysis["high"])}</p>

            <h3>Entrenamiento</h3>
            <p>Últimos 7 días: {analysis["km_7"]:.1f} km</p>
            <p>Media semanal: {analysis["avg_week"]:.1f} km</p>
            <p>Tirada larga: {analysis["long_km"]:.1f} km</p>
            <p>Bloques de calidad detectados: {len(analysis["quality_blocks"])}</p>
            <p>Bloques por series/laps cerca de ritmo maratón: {len(analysis["lap_blocks"])}</p>

            <h3>Recomendación del coach</h3>
            <p>{analysis["coach_message"]}</p>
            <ul>
                <li>Media semanal actual: {analysis["avg_week"]:.1f} km. Objetivo recomendado: {analysis["target_weekly"]} km.</li>
                <li>Tirada larga actual: {analysis["long_km"]:.1f} km. Recomendación: {analysis["target_long"]} km.</li>
                <li>{analysis["coach_detail"]}</li>
            </ul>

            <a class="button" href="/share.png">Compartir predicción</a>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html)


@app.get("/share.png")
def share_png(request: Request):
    user = get_current_user(request)

    if not user:
        return HTMLResponse("<h1>No session in /share.png</h1>", status_code=401)

    user = refresh_access_token_if_needed(user)

    analysis, error = get_common_analysis(request, user)
    if error == "rate_limited":
        return HTMLResponse(
            "<h1>Strava está limitando temporalmente las peticiones (429)</h1>"
            "<p>Espera unos minutos y vuelve a generar la tarjeta.</p>",
            status_code=429,
        )

    img = Image.new("RGB", (1200, 630), "white")
    draw = ImageDraw.Draw(img)

    try:
        brand_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
        question_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 58)
        big_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 112)
        text_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
        strong_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 38)
        small_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except Exception:
        brand_font = ImageFont.load_default()
        question_font = ImageFont.load_default()
        big_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
        strong_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    draw.rounded_rectangle((30, 30, 1170, 600), radius=28, outline="#E8E8E8", width=3, fill="white")
    draw.rectangle((30, 30, 1170, 95), fill="#FC5200")

    draw.text((70, 45), "SecondCoach", fill="white", font=brand_font)

    draw.text(
        (70, 135),
        f"¿Estoy listo para {analysis['goal_time']}?",
        fill="black",
        font=question_font,
    )
    draw.text((70, 235), "SecondCoach dice:", fill="#444444", font=text_font)
    draw.text((70, 290), analysis["pred_time"], fill="black", font=big_font)

    draw.text(
        (430, 330),
        f"{analysis['probability']}%",
        fill="#FC5200",
        font=strong_font,
    )
    draw.text((430, 375), "probabilidad", fill="#666666", font=small_font)

    draw.text(
        (70, 470),
        f"{RACE_NAMES[analysis['race_type']]} · {analysis['race_date']}",
        fill="#444444",
        font=text_font,
    )
    draw.text((70, 525), "Analiza tu Strava en", fill="#777777", font=small_font)
    draw.text((70, 555), "secondcoach.onrender.com", fill="#FC5200", font=strong_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/dashboard")
def api_dashboard(request: Request):
    user = get_current_user(request)

    if not user:
        return {"error": "not_authenticated"}

    user = refresh_access_token_if_needed(user)

    analysis, error = get_common_analysis(request, user)
    if error == "rate_limited":
        return {"error": "strava_rate_limited"}

    return {
        "race": {
            "type": analysis["race_type"],
            "name": RACE_NAMES[analysis["race_type"]],
            "date": analysis["race_date"],
            "goal_time": analysis["goal_time"],
        },
        "prediction": {
            "predicted_time": analysis["pred_time"],
            "range_low": _fmt(analysis["low"]),
            "range_high": _fmt(analysis["high"]),
            "pace_per_km": f"{analysis['pace_min']}:{analysis['pace_sec']:02d}",
        },
        "training": {
            "km_last_7_days": analysis["km_7"],
            "weekly_average": analysis["avg_week"],
            "long_run": analysis["long_km"],
            "quality_blocks_count": len(analysis["quality_blocks"]),
            "goal_pace_lap_blocks_count": len(analysis["lap_blocks"]),
            "goal_pace_lap_blocks_km": analysis["lap_block_km"],
        },
        "coach": {
            "message": analysis["coach_message"],
            "detail": analysis["coach_detail"],
            "recommended_weekly_km": analysis["target_weekly"],
            "recommended_long_run_km": analysis["target_long"],
        },
    }


@app.get("/api/coach")
def api_coach(request: Request):
    user = get_current_user(request)

    if not user:
        return {"error": "not_authenticated"}

    user = refresh_access_token_if_needed(user)

    analysis, error = get_common_analysis(request, user)
    if error == "rate_limited":
        return {"error": "strava_rate_limited"}

    missing_weekly = max(0.0, round(analysis["target_weekly"] - analysis["avg_week"], 1))
    missing_long = max(0.0, round(analysis["target_long"] - analysis["long_km"], 1))

    if analysis["lap_block_km"] < 5:
        status = "yellow"
        summary = "Te falta más exposición a ritmo objetivo."
        explanation = (
            f"Llevas {analysis['lap_block_km']:.1f} km en bloques por series/laps cerca de ritmo maratón. "
            f"Para consolidar {analysis['goal_time']}, intenta acumular 10–15 km por semana cerca de tu ritmo objetivo."
        )
    elif analysis["lap_block_km"] < 12:
        status = "green"
        summary = "Vas construyendo bien el ritmo objetivo."
        explanation = (
            f"Ya acumulas {analysis['lap_block_km']:.1f} km recientes cerca del ritmo objetivo. "
            f"Estás en buena línea, aunque todavía puedes consolidarlo con más continuidad."
        )
    else:
        status = "green"
        summary = "Tu trabajo específico va en buena dirección."
        explanation = (
            f"Acumulas {analysis['lap_block_km']:.1f} km recientes en bloques por series/laps cerca del ritmo objetivo, "
            f"una señal fuerte de preparación para {analysis['goal_time']}."
        )

    return {
        "status": status,
        "summary": summary,
        "explanation": explanation,
        "metrics": {
            "weekly_average_km": analysis["avg_week"],
            "long_run_km": analysis["long_km"],
            "goal_pace_block_km": analysis["lap_block_km"],
            "goal_pace_block_count": len(analysis["lap_blocks"]),
            "km_last_7_days": analysis["km_7"],
        },
        "gaps": {
            "weekly_km_missing": missing_weekly,
            "long_run_km_missing": missing_long,
        },
        "next_steps": {
            "conservative": (
                f"Sube hacia {analysis['target_weekly']} km/sem de forma gradual y acerca la tirada larga a {analysis['target_long']} km."
            ),
            "aggressive": (
                "Mantén el volumen actual y añade un bloque semanal de 6–10 km cerca de ritmo objetivo."
            ),
        },
    }


@app.get("/api/analysis")
def api_analysis(request: Request):
    user = get_current_user(request)

    if not user:
        return {"error": "not_authenticated"}

    user = refresh_access_token_if_needed(user)

    analysis, error = get_common_analysis(request, user)
    if error == "rate_limited":
        return {"error": "strava_rate_limited"}

    return {
        "race": {
            "type": analysis["race_type"],
            "name": RACE_NAMES[analysis["race_type"]],
            "date": analysis["race_date"],
            "goal_time": analysis["goal_time"],
        },
        "status": {
            "readiness": analysis["readiness"],
            "readiness_label": analysis["readiness_label"],
            "specificity": analysis["specificity"],
        },
        "prediction": {
            "predicted_time": analysis["pred_time"],
            "range_low": _fmt(analysis["low"]),
            "range_high": _fmt(analysis["high"]),
            "minutes_vs_goal": analysis["diff"],
        },
        "training": {
            "km_last_7_days": analysis["km_7"],
            "weekly_average_km": analysis["avg_week"],
            "long_run_km": analysis["long_km"],
            "quality_blocks_count": len(analysis["quality_blocks"]),
            "goal_pace_block_km": analysis["lap_block_km"],
            "goal_pace_block_count": len(analysis["lap_blocks"]),
        },
        "coach": {
            "positive": (
                f"Acumulas {analysis['lap_block_km']:.1f} km recientes cerca del ritmo objetivo."
                if analysis["lap_block_km"] > 0
                else "Ya tienes base de entrenamiento para seguir construyendo."
            ),
            "limiter": (
                f"Te faltan {max(0, round(analysis['target_weekly'] - analysis['avg_week'], 1)):.1f} km/sem "
                "para llegar al volumen recomendado."
            ),
            "next_focus": (
                f"Acerca la tirada larga a {analysis['target_long']} km y mantén un bloque semanal de ritmo objetivo."
            ),
        },
    }


@app.get("/api/share")
def api_share(request: Request):
    user = get_current_user(request)

    if not user:
        return {"error": "not_authenticated"}

    race_type = request.session.get("race_type", "marathon")
    goal_time = request.session.get("goal_time", "3:30")
    race_date = request.session.get("race_date", "2026-04-12")

    base_url = str(request.base_url).rstrip("/")

    return {
        "race": {
            "type": race_type,
            "name": RACE_NAMES[race_type],
            "date": race_date,
            "goal_time": goal_time,
        },
        "share_image_url": f"{base_url}/share.png",
        "share_page_url": f"{base_url}/dashboard",
        "cta": "Comparte tu predicción de SecondCoach",
    }


@app.get("/api/bootstrap")
def api_bootstrap(request: Request):
    user = get_current_user(request)

    if not user:
        return {"error": "not_authenticated"}

    user = refresh_access_token_if_needed(user)

    analysis, error = get_common_analysis(request, user)
    if error == "rate_limited":
        return {"error": "strava_rate_limited"}

    base_url = str(request.base_url).rstrip("/")

    return {
        "race": {
            "type": analysis["race_type"],
            "name": RACE_NAMES[analysis["race_type"]],
            "date": analysis["race_date"],
            "goal_time": analysis["goal_time"],
        },
        "prediction": {
            "predicted_time": analysis["pred_time"],
            "range_low": _fmt(analysis["low"]),
            "range_high": _fmt(analysis["high"]),
            "pace_per_km": f"{analysis['pace_min']}:{analysis['pace_sec']:02d}",
            "minutes_vs_goal": analysis["diff"],
        },
        "training": {
            "km_last_7_days": analysis["km_7"],
            "weekly_average_km": analysis["avg_week"],
            "long_run_km": analysis["long_km"],
            "quality_blocks_count": len(analysis["quality_blocks"]),
            "goal_pace_block_count": len(analysis["lap_blocks"]),
            "goal_pace_block_km": analysis["lap_block_km"],
        },
        "coach": {
            "message": analysis["coach_message"],
            "detail": analysis["coach_detail"],
            "recommended_weekly_km": analysis["target_weekly"],
            "recommended_long_run_km": analysis["target_long"],
        },
        "status": {
            "readiness": analysis["readiness"],
            "readiness_label": analysis["readiness_label"],
            "specificity": analysis["specificity"],
        },
        "share": {
            "share_image_url": f"{base_url}/share.png",
            "share_page_url": f"{base_url}/dashboard",
            "cta": "Comparte tu predicción de SecondCoach",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/users")
def debug_users():
    from backend.db import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT strava_athlete_id FROM users").fetchall()
    return {"users": [r["strava_athlete_id"] for r in rows]}