from datetime import datetime, timedelta, timezone

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.analysis import compute_training, detect_quality_blocks, build_last_key_session
from backend.db import get_user_by_athlete_id, upsert_user
from backend.multi_distance import predict_all_distances
from backend.settings import settings
from backend.strava_auth import refresh_access_token_if_needed


ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=settings.APP_SESSION_SECRET)


@app.get("/health")
def health():
    return {"status": "ok"}


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

    data = response.json()
    athlete = data["athlete"]

    upsert_user(
        strava_athlete_id=athlete["id"],
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=data["expires_at"],
        username=athlete.get("username"),
        firstname=athlete.get("firstname"),
        lastname=athlete.get("lastname"),
    )

    request.session["athlete_id"] = athlete["id"]

    return RedirectResponse("/api/analysis")


@app.get("/api/analysis")
def analysis(request: Request):

    athlete_id = request.session.get("athlete_id")

    if not athlete_id:
        return RedirectResponse("/login")

    user = get_user_by_athlete_id(athlete_id)

    if not user:
        return {"error": "user_not_found"}

    acts = []

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

    quality_blocks = detect_quality_blocks(
        runs,
        goal_time="3:30",
        race_type="marathon",
    )

    goal_pace_block_km = sum(b.get("km", 0) for b in quality_blocks)

    last_key_session = build_last_key_session(runs, quality_blocks)

    all_predictions = predict_all_distances(
        avg_week_km=avg_week,
        long_run_km=long_km,
        goal_blocks_km=goal_pace_block_km,
    )

    result = {
        "race": {
            "type": "marathon",
            "name": "Maratón de Zaragoza",
            "date": "2026-04-12",
            "goal_time": "3:30",
        },
        "status": {
            "readiness": "on_track",
            "readiness_label": "En línea con el objetivo",
            "specificity": "high",
        },
        "training": {
            "km_last_7_days": km_7,
            "weekly_average_km": avg_week,
            "long_run_km": long_km,
            "quality_blocks_count": len(quality_blocks),
            "goal_pace_block_km": goal_pace_block_km,
            "quality_blocks": quality_blocks,
        },
        "last_key_session": last_key_session,
        "prediction": {
            "predicted_time": "3:25"
        },
        "coach": {
            "positive": "Acumulas km recientes cerca del ritmo objetivo.",
            "limiter": "Te falta algo de volumen semanal.",
            "next_focus": "Mantén una tirada larga sólida y bloques de ritmo objetivo.",
        },
        "all_predictions": all_predictions,
    }

    return result


@app.get("/api/bootstrap")
def bootstrap(request: Request):
    return analysis(request)


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

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
    </head>
    <body>
        <h1>SecondCoach</h1>

        <h2>{race["name"]}</h2>
        <p>Goal: {race["goal_time"]}</p>

        <h2>Predicción</h2>
        <p>{prediction["predicted_time"]}</p>

        <h2>Estado</h2>
        <p>{status["readiness_label"]}</p>

        <h2>Entrenamiento</h2>
        <p>Km últimos 7 días: {training["km_last_7_days"]}</p>
        <p>Promedio semanal: {training["weekly_average_km"]}</p>
        <p>Tirada larga: {training["long_run_km"]} km</p>

        <h2>Coach</h2>
        <p>{coach["positive"]}</p>
        <p>{coach["limiter"]}</p>
        <p>{coach["next_focus"]}</p>
    </body>
    </html>
    """

    return HTMLResponse(html)