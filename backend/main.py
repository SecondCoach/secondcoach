from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
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

STRAVA_ACTIVITY_DETAIL_URL = "https://www.strava.com/api/v3/activities/{activity_id}"


def hydrate_runs_for_quality_blocks(runs: list[dict], access_token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {access_token}"}
    enriched_runs: list[dict] = []

    for run in runs:
        try:
            distance_m = float(run.get("distance") or 0)
        except (TypeError, ValueError):
            distance_m = 0.0

        if distance_m < 24000:
            enriched_runs.append(run)
            continue

        activity_id = run.get("id")
        if not activity_id:
            enriched_runs.append(run)
            continue

        try:
            detail_resp = requests.get(
                STRAVA_ACTIVITY_DETAIL_URL.format(activity_id=activity_id),
                headers=headers,
                params={"include_all_efforts": "false"},
                timeout=30,
            )
            detail_resp.raise_for_status()
            detail = detail_resp.json()
            enriched_runs.append(detail if isinstance(detail, dict) else run)
        except Exception:
            enriched_runs.append(run)

    return enriched_runs


def build_quality_debug(runs: list[dict]) -> list[dict]:
    debug = []

    for run in runs:
        if run.get("type") != "Run":
            continue

        try:
            distance_km = float(run.get("distance") or 0) / 1000.0
        except (TypeError, ValueError):
            distance_km = 0.0

        if distance_km < 24:
            continue

        splits = run.get("splits_metric")
        laps = run.get("laps")

        debug.append(
            {
                "activity_id": run.get("id"),
                "activity_name": run.get("name"),
                "activity_date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
                "total_run_km": round(distance_km, 1),
                "has_splits_metric": isinstance(splits, list) and len(splits) > 0,
                "splits_metric_count": len(splits) if isinstance(splits, list) else 0,
                "has_laps": isinstance(laps, list) and len(laps) > 0,
                "laps_count": len(laps) if isinstance(laps, list) else 0,
            }
        )

    debug.sort(key=lambda x: (x.get("activity_date", ""), x.get("total_run_km", 0)), reverse=True)
    return debug[:10]



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=settings.APP_SESSION_SECRET)


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
        return {"error": "user_not_found", "athlete_id": athlete_id}

    acts = []

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

        if isinstance(payload, list):
            acts = payload

    runs = [a for a in acts if isinstance(a, dict) and a.get("type") == "Run"]
    detailed_runs = hydrate_runs_for_quality_blocks(runs, user["access_token"])

    km_7, avg_week, long_km = compute_training(runs)
    quality_blocks = detect_quality_blocks(
        detailed_runs,
        goal_time=request.session.get("goal_time", "3:30"),
        race_type=request.session.get("race_type", "marathon"),
    )
    goal_pace_block_km = sum(b.get("km", 0) for b in quality_blocks) if quality_blocks else 0

    all_predictions = predict_all_distances(
        avg_week_km=avg_week,
        long_run_km=long_km,
        goal_blocks_km=goal_pace_block_km,
    )

    goal_time = "3:30"
    predicted_time = "3:25"

    pred_sec = time_to_seconds(predicted_time)
    goal_sec = time_to_seconds(goal_time)

    spread_minutes = 6
    if avg_week < 45:
        spread_minutes += 2
    if goal_pace_block_km <= 0:
        spread_minutes += 2
    if long_km < 28:
        spread_minutes += 1

    spread_sec = spread_minutes * 60
    range_low = seconds_to_time(pred_sec - spread_sec)
    range_high = seconds_to_time(pred_sec + spread_sec)

    if pred_sec is not None and goal_sec is not None:
        minutes_vs_goal = round((pred_sec - goal_sec) / 60)
    else:
        minutes_vs_goal = 0

    display_predictions = dict(all_predictions)
    display_predictions["marathon"] = predicted_time

    result = {
        "race": {
            "type": "marathon",
            "name": "Maratón de Zaragoza",
            "date": "2026-04-12",
            "goal_time": goal_time,
        },
        "status": {
            "readiness": "on_track",
            "readiness_label": "En línea con el objetivo",
            "specificity": "high",
        },
        "prediction": {
            "predicted_time": predicted_time,
            "range_low": range_low,
            "range_high": range_high,
            "minutes_vs_goal": minutes_vs_goal,
        },
        "training": {
            "km_last_7_days": km_7,
            "weekly_average_km": avg_week,
            "long_run_km": long_km,
            "quality_blocks_count": len(quality_blocks),
            "goal_pace_block_km": goal_pace_block_km,
            "goal_pace_block_count": len(quality_blocks),
            "quality_blocks": quality_blocks,
        },
        "coach": {
            "positive": "Acumulas km recientes cerca del ritmo objetivo.",
            "limiter": "Te falta algo de volumen semanal.",
            "next_focus": "Mantén una tirada larga sólida y bloques de ritmo objetivo.",
        },
        "all_predictions": display_predictions,
        "quality_debug": build_quality_debug(detailed_runs),
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
    preds = data.get("all_predictions", {})

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