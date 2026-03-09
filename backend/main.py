from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

import requests

from backend.settings import settings
from backend.db import get_user_by_athlete_id, upsert_user
from backend.strava_auth import refresh_access_token_if_needed
from backend.analysis import compute_training, detect_quality_blocks
from backend.multi_distance import predict_all_distances

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


# ---------------------------
# STRAVA LOGIN
# ---------------------------

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


# ---------------------------
# ANALYSIS
# ---------------------------

@app.get("/api/analysis")
def analysis(request: Request):

    athlete_id = request.session.get("athlete_id")

    # modo local: permite probar sin OAuth
    if not athlete_id:
        athlete_id = 1388857

    user = get_user_by_athlete_id(athlete_id)

    if not user:
        return {"error": "user_not_found", "athlete_id": athlete_id}

    acts = []

    # solo intentamos refresh / llamada real si hay token válido
    access_token = user.get("access_token")
    if access_token and access_token != "DUMMY":
        user = refresh_access_token_if_needed(user)

        headers = {"Authorization": f"Bearer {user['access_token']}"}

        response = requests.get(
            ACTIVITIES_URL,
            headers=headers,
            params={"per_page": 200},
            timeout=30,
        )

        try:
            payload = response.json()
        except Exception:
            payload = []

        # Strava correcto: lista de actividades
        if isinstance(payload, list):
            acts = payload
        else:
            acts = []

    runs = [a for a in acts if isinstance(a, dict) and a.get("type") == "Run"]

    km_7, avg_week, long_km = compute_training(runs)

    quality_blocks = detect_quality_blocks(runs)

    goal_pace_block_km = sum(b.get("km", 0) for b in quality_blocks) if quality_blocks else 0

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
        "prediction": {
            "predicted_time": "3:25",
            "range_low": "3:22",
            "range_high": "3:29",
            "minutes_vs_goal": -5,
        },
        "training": {
            "km_last_7_days": km_7,
            "weekly_average_km": avg_week,
            "long_run_km": long_km,
            "quality_blocks_count": len(quality_blocks),
            "goal_pace_block_km": goal_pace_block_km,
            "goal_pace_block_count": len(quality_blocks),
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

from fastapi.responses import HTMLResponse


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    data = analysis(request)

    preds = data.get("all_predictions", {})

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
        <style>
            body {{
                font-family: Arial;
                background: #0f172a;
                color: white;
                text-align: center;
                padding: 40px;
            }}
            h1 {{
                font-size: 42px;
            }}
            .card {{
                background: #1e293b;
                border-radius: 12px;
                padding: 20px;
                margin: 20px auto;
                width: 320px;
            }}
            .metric {{
                font-size: 28px;
                margin: 10px 0;
            }}
        </style>
    </head>

    <body>

        <h1>SecondCoach</h1>

        <div class="card">
            <h2>Predicciones</h2>
            <div class="metric">5K: {preds.get("5k")}</div>
            <div class="metric">10K: {preds.get("10k")}</div>
            <div class="metric">Media: {preds.get("half")}</div>
            <div class="metric">Maratón: {preds.get("marathon")}</div>
        </div>

        <div class="card">
            <h2>Readiness</h2>
            <div class="metric">{data["status"]["readiness_label"]}</div>
        </div>

    </body>
    </html>
    """

    return HTMLResponse(html)

from fastapi.responses import HTMLResponse


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    data = analysis(request)
    preds = data.get("all_predictions", {})

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
        <style>
            body {{
                font-family: Arial;
                background: #0f172a;
                color: white;
                text-align: center;
                padding: 40px;
            }}
            .card {{
                background: #1e293b;
                border-radius: 12px;
                padding: 20px;
                margin: 20px auto;
                width: 320px;
            }}
            .metric {{
                font-size: 28px;
                margin: 10px 0;
            }}
        </style>
    </head>

    <body>

        <h1>SecondCoach</h1>

        <div class="card">
            <h2>Predicciones</h2>
            <div class="metric">5K: {preds.get("5k")}</div>
            <div class="metric">10K: {preds.get("10k")}</div>
            <div class="metric">Media: {preds.get("half")}</div>
            <div class="metric">Maratón: {preds.get("marathon")}</div>
        </div>

        <div class="card">
            <h2>Estado</h2>
            <div class="metric">{data["status"]["readiness_label"]}</div>
        </div>

    </body>
    </html>
    """

    return HTMLResponse(html)