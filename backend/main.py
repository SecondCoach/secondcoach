from datetime import datetime, timedelta, timezone

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.activity_details import enrich_runs_with_activity_details
from backend.analysis import (
    build_last_key_session,
    compute_fatigue_signal,
    compute_goal_progress,
    compute_training,
    detect_quality_blocks,
    weeks_to_race,
)
from backend.db import get_user_by_athlete_id, init_db, upsert_user
from backend.multi_distance import predict_all_distances
from backend.public_page import router as public_router
from backend.settings import settings
from backend.share_card import render_share_card
from backend.share_story import render_story_card
from backend.strava_auth import refresh_access_token_if_needed

ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
CLIENT_ID = "208434"
CLIENT_SECRET = "9bfa526853eadc6cfd2381f859fee8fa99b6bf04"
REDIRECT_URI = "http://127.0.0.1:8000/callback"

def time_to_seconds(value: str | None) -> int | None:
    if not value:
        return None

    parts = [int(p) for p in value.split(":")]

    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s

    if len(parts) == 2:
        h, m = parts
        return h * 3600 + m * 60

    return None


def seconds_to_time(sec: int) -> str:
    if sec < 0:
        sec = 0

    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}"


def describe_session_type(session_type: str | None) -> str:
    mapping = {
        "marathon_specific": "tirada específica de maratón",
        "progressive_run": "tirada progresiva",
        "race_or_test": "competición o test",
        "long_run": "tirada larga",
        "aerobic_run": "rodaje aeróbico",
        "short_run": "rodaje corto",
    }
    return mapping.get(session_type or "", "sesión clave")


app = FastAPI()
app.mount("/static", StaticFiles(directory="backend/static"), name="static")
app.include_router(public_router)


@app.on_event("startup")
def on_startup():
    init_db()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.APP_SESSION_SECRET,
    same_site="lax",
    https_only=(settings.APP_ENV == "production"),
    max_age=60 * 60 * 24 * 14,
)


def build_analysis_payload(user: dict, goal_time: str) -> dict:
    acts = []

    access_token = user.get("access_token")
    if access_token and access_token != "DUMMY":
        user = refresh_access_token_if_needed(user)

        headers = {"Authorization": f"Bearer {user['access_token']}"}
        after_ts = int((datetime.now(timezone.utc) - timedelta(days=84)).timestamp())

        response = requests.get(
            ACTIVITIES_URL,
            headers=headers,
            params={"per_page": 200, "after": after_ts},
            timeout=30,
        )

        try:
            payload = response.json()
        except Exception:
            payload = []

        if isinstance(payload, list):
            acts = payload

    runs = [a for a in acts if isinstance(a, dict) and a.get("type") == "Run"]

    km_7, avg_week, long_km = compute_training(runs)
    fatigue_signal = compute_fatigue_signal(runs)

    headers = {"Authorization": f"Bearer {user['access_token']}"}
    enriched_runs = enrich_runs_with_activity_details(
        runs,
        headers=headers,
        min_distance_km=18.0,
        max_candidates=12,
    )

    quality_blocks = detect_quality_blocks(
        enriched_runs,
        goal_time=goal_time,
    )

    goal_pace_block_km = sum(b.get("km", 0) for b in quality_blocks) if quality_blocks else 0
    last_key_session = build_last_key_session(enriched_runs, quality_blocks)

    all_predictions = predict_all_distances(
        avg_week_km=avg_week,
        long_run_km=long_km,
        goal_blocks_km=goal_pace_block_km,
    )

    predicted_time = all_predictions.get("marathon") or goal_time

    pred_sec = time_to_seconds(predicted_time)
    goal_sec = time_to_seconds(goal_time)

    spread_minutes = 6
    if avg_week < 45:
        spread_minutes += 2
    if goal_pace_block_km <= 0:
        spread_minutes += 2
    if long_km < 28:
        spread_minutes += 1

    if pred_sec is None:
        pred_sec = goal_sec if goal_sec is not None else 0
    if goal_sec is None:
        goal_sec = pred_sec

    spread_sec = spread_minutes * 60
    range_low = seconds_to_time(pred_sec - spread_sec)
    range_high = seconds_to_time(pred_sec + spread_sec)
    minutes_vs_goal = round((pred_sec - goal_sec) / 60)

    display_predictions = dict(all_predictions)
    display_predictions["marathon"] = predicted_time

    recent_block = quality_blocks[0] if quality_blocks else None
    session_type = (last_key_session or {}).get("type")
    session_label = describe_session_type(session_type)
    session_date = (last_key_session or {}).get("date")
    session_distance = (last_key_session or {}).get("distance_km")

    if recent_block and session_type == "marathon_specific":
        block_km = recent_block.get("km", 0)
        positive = (
            f"Tu última sesión clave fue una {session_label} de {session_distance} km "
            f"el {session_date}, con {block_km} km a ritmo maratón."
        )
    elif recent_block:
        block_km = recent_block.get("km", 0)
        block_date = recent_block.get("activity_date")
        positive = (
            f"Has realizado un bloque reciente de {block_km} km a ritmo maratón "
            f"en tu tirada del {block_date}."
        )
    elif last_key_session:
        positive = (
            f"Tu última sesión clave fue una {session_label} de {session_distance} km "
            f"el {session_date}."
        )
    else:
        positive = "Tu volumen reciente es consistente, pero aún no aparecen sesiones específicas claras."

    if minutes_vs_goal <= -5:
        readiness = "ahead"
        readiness_label = "Por delante del objetivo"
    elif minutes_vs_goal >= 5:
        readiness = "behind"
        readiness_label = "Por detrás del objetivo"
    else:
        readiness = "on_track"
        readiness_label = "En línea con el objetivo"

    if session_type == "marathon_specific" and goal_pace_block_km >= 12:
        specificity = "high"
    elif goal_pace_block_km >= 6:
        specificity = "medium"
    else:
        specificity = "low"

    if minutes_vs_goal >= 10:
        limiter = (
            f"La predicción actual ({predicted_time}) está claramente por encima del objetivo "
            f"({goal_time}). Ahora mismo falta especificidad y/o volumen para sostener ese ritmo."
        )
    elif avg_week < 55:
        limiter = f"Tu volumen semanal medio aún es algo justo para consolidar tu objetivo de {goal_time}."
    else:
        limiter = "Tu volumen semanal es suficiente; ahora el foco está en mantener la especificidad."

    if minutes_vs_goal >= 10:
        next_focus = "Prioriza dos semanas muy sólidas: tirada larga estable y más minutos continuos a ritmo objetivo."
    elif session_type == "marathon_specific" and goal_pace_block_km >= 12:
        next_focus = "Mantén la especificidad: conserva la tirada larga y repite otro bloque de 8-10 km a ritmo maratón."
    elif goal_pace_block_km >= 12:
        next_focus = "Mantén una tirada larga sólida y repite un bloque de 8-10 km a ritmo maratón."
    else:
        next_focus = "Introduce progresivamente bloques más largos a ritmo maratón dentro de las tiradas largas."

    coach = {
        "positive": positive,
        "limiter": limiter,
        "next_focus": next_focus,
    }

    race_date = "2026-04-12"

    race = {
        "type": "marathon",
        "name": "Maratón de Zaragoza",
        "date": race_date,
        "goal_time": goal_time,
        "weeks_to_race": weeks_to_race(race_date),
    }

    training = {
        "km_last_7_days": km_7,
        "weekly_average_km": avg_week,
        "long_run_km": long_km,
        "quality_blocks_count": len(quality_blocks),
        "goal_pace_block_km": goal_pace_block_km,
        "goal_pace_block_count": len(quality_blocks),
        "quality_blocks": quality_blocks,
    }

    prediction = {
        "predicted_time": predicted_time,
        "range_low": range_low,
        "range_high": range_high,
        "minutes_vs_goal": minutes_vs_goal,
    }

    return {
        "race": race,
        "status": {
            "readiness": readiness,
            "readiness_label": readiness_label,
            "specificity": specificity,
        },
        "prediction": prediction,
        "training": training,
        "fatigue": fatigue_signal,
        "goal_progress": compute_goal_progress(race, prediction, training),
        "last_key_session": last_key_session,
        "coach": coach,
        "all_predictions": display_predictions,
    }


@app.get("/")
def root(request: Request):
    athlete_id = request.session.get("athlete_id")
    if athlete_id:
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")


@app.head("/")
def root_head():
    return Response(status_code=200)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/login")
def login():
    params = {
        "client_id": settings.STRAVA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.STRAVA_REDIRECT_URI,
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }

    query = "&".join([f"{k}={v}" for k, v in params.items()])
    url = f"{STRAVA_AUTHORIZE_URL}?{query}"

    return RedirectResponse(url)


@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse(url="/login", status_code=302)

    token_response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )

    data = token_response.json() if token_response.content else {}

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_at = data.get("expires_at")
    athlete = data.get("athlete") or {}
    athlete_id = athlete.get("id")

    if not access_token or not athlete_id:
        return HTMLResponse(
            f"""
            <h1>Error en callback Strava</h1>
            <p>La respuesta del token no incluye los datos esperados.</p>
            <pre>{data}</pre>
            <p><a href="/login">Volver a intentar</a></p>
            """,
            status_code=400,
        )

    upsert_user(
        strava_athlete_id=athlete_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    request.session["access_token"] = access_token
    request.session["athlete_id"] = athlete_id

    return RedirectResponse(url="/dashboard", status_code=302)
@app.get("/api/analysis")
def analysis(request: Request):
    athlete_id = request.session.get("athlete_id")

    if not athlete_id:
        return RedirectResponse("/login")

    user = get_user_by_athlete_id(athlete_id)

    if not user:
        return {"error": "user_not_found", "athlete_id": athlete_id}

    goal_time = request.session.get("goal_time", settings.DEFAULT_GOAL_TIME)
    return build_analysis_payload(user, goal_time)


@app.get("/api/bootstrap")
def bootstrap(request: Request):
    return analysis(request)


@app.get("/share.png")
def share_png(request: Request):
    data = analysis(request)

    if isinstance(data, RedirectResponse):
        return data

    return Response(content=render_share_card(data), media_type="image/png")


@app.get("/share/{athlete_id}.png")
def share_png_public(athlete_id: int):
    user = get_user_by_athlete_id(athlete_id)

    if not user:
        return Response(status_code=404)

    data = build_analysis_payload(user, settings.DEFAULT_GOAL_TIME)
    return Response(content=render_share_card(data), media_type="image/png")


@app.get("/story.png")
def story_png(request: Request):
    data = analysis(request)

    if isinstance(data, RedirectResponse):
        return data

    return Response(content=render_story_card(data), media_type="image/png")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    data = analysis(request)

    if isinstance(data, RedirectResponse):
        return data

    race = data["race"]
    status = data["status"]
    prediction = data["prediction"]
    training = data["training"]
    coach = data["coach"]
    preds = data.get("all_predictions", {})
    last_key_session = data.get("last_key_session")

    last_key_html = ""
    if last_key_session:
        last_key_html = f"""
            <div class="card">
                <div class="small">Última sesión clave</div>
                <div class="metric">{describe_session_type(last_key_session.get("type"))}</div>
                <div class="small">{last_key_session.get("date")} · {last_key_session.get("distance_km")} km</div>
            </div>
        """

    weeks_html = ""
    if race.get("weeks_to_race") is not None:
        weeks_html = f"""<div class="small">⏳ {race["weeks_to_race"]} semanas para la carrera</div>"""

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                text-align: center;
                padding: 40px;
                margin: 0;
            }}
            h1 {{
                font-size: 46px;
                margin-bottom: 24px;
            }}
            .container {{
                max-width: 700px;
                margin: auto;
            }}
            .card {{
                background: #1e293b;
                border-radius: 12px;
                padding: 24px;
                margin: 20px auto;
            }}
            .metric {{
                font-size: 30px;
                margin: 8px 0;
            }}
            .small {{
                font-size: 18px;
                opacity: 0.8;
            }}
            .green {{
                color: #22c55e;
            }}
            p {{
                font-size: 18px;
                line-height: 1.5;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>SecondCoach</h1>

            <div class="card">
                <div class="small">Objetivo</div>
                <div class="metric">{race["name"]}</div>
                <div class="small">Goal time</div>
                <div class="metric">{race["goal_time"]}</div>
                {weeks_html}
            </div>

            <div class="card">
                <div class="small">Predicción actual</div>
                <div class="metric green">{prediction["predicted_time"]}</div>
                <div class="small">rango {prediction["range_low"]} – {prediction["range_high"]}</div>
            </div>

            <div class="card">
                <div class="small">Estado</div>
                <div class="metric">{status["readiness_label"]}</div>
            </div>

            {last_key_html}

            <div class="card">
                <div class="small">Entrenamiento reciente</div>

                <div class="small">Km últimos 7 días</div>
                <div class="metric">{training["km_last_7_days"]}</div>

                <div class="small">Promedio semanal</div>
                <div class="metric">{training["weekly_average_km"]}</div>

                <div class="small">Tirada larga</div>
                <div class="metric">{training["long_run_km"]} km</div>
            </div>

            <div class="card">
                <div class="small">Predicciones</div>
                <div class="metric">5K — {preds.get("5k")}</div>
                <div class="metric">10K — {preds.get("10k")}</div>
                <div class="metric">Media — {preds.get("half")}</div>
                <div class="metric">Maratón — {preds.get("marathon")}</div>
            </div>

            <div class="card">
                <div class="small">Coach</div>
                <p><b>👍 Positivo:</b> {coach["positive"]}</p>
                <p><b>⚠️ Limitante:</b> {coach["limiter"]}</p>
                <p><b>➡️ Próximo foco:</b> {coach["next_focus"]}</p>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html)
