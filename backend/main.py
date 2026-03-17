from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64

import requests
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
from backend.db import get_user_by_athlete_id, save_user
from backend.goal_store import get_user_goal, save_user_goal

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "backend" / "assets"

CLIENT_ID = "TU_CLIENT_ID_REAL"
CLIENT_SECRET = "TU_CLIENT_SECRET_REAL"
REDIRECT_URI = "https://secondcoach.onrender.com/callback"

STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ATHLETE_URL = "https://www.strava.com/api/v3/athlete"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

DEFAULT_RACE = {
    "type": "marathon",
    "name": "Maratón objetivo",
    "date": "2026-04-12",
    "goal_time": "3:30",
}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key="change-this-session-secret",
    same_site="lax",
    https_only=False,
)


def get_logo_data_uri() -> str:
    logo_path = ASSETS_DIR / "icon.png"
    if not logo_path.exists():
        return ""
    encoded = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def exchange_code_for_token(code: str) -> dict:
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    return response.json()


def refresh_access_token_if_needed(user: dict | None) -> dict | None:
    if not user:
        return None

    expires_at = user.get("expires_at")
    if not expires_at:
        return user

    try:
        expires_dt = datetime.fromtimestamp(int(expires_at), tz=timezone.utc)
    except Exception:
        return user

    if expires_dt > datetime.now(timezone.utc) + timedelta(minutes=5):
        return user

    refresh_token = user.get("refresh_token")
    if not refresh_token:
        return user

    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    token_json = response.json()

    access_token = token_json.get("access_token")
    new_refresh_token = token_json.get("refresh_token", refresh_token)
    new_expires_at = token_json.get("expires_at", expires_at)
    athlete = token_json.get("athlete", {})
    athlete_id = athlete.get("id") or user.get("strava_athlete_id")

    if access_token and athlete_id:
        save_user(
            strava_athlete_id=athlete_id,
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_at=new_expires_at,
        )
        user = get_user_by_athlete_id(athlete_id)

    return user


def get_current_access_token(request: Request) -> str | None:
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return None

    user = get_user_by_athlete_id(athlete_id)
    user = refresh_access_token_if_needed(user)
    if not user:
        return None

    access_token = user.get("access_token")
    if access_token:
        request.session["access_token"] = access_token
    return access_token


def get_current_race(request: Request) -> dict:
    athlete_id = request.session.get("athlete_id")
    if athlete_id:
        goal = get_user_goal(athlete_id)
        if goal:
            return {
                "type": goal.get("race_type") or DEFAULT_RACE["type"],
                "name": goal.get("race_name") or DEFAULT_RACE["name"],
                "date": goal.get("race_date") or DEFAULT_RACE["date"],
                "goal_time": goal.get("goal_time") or DEFAULT_RACE["goal_time"],
            }
    return DEFAULT_RACE


def fetch_athlete(access_token: str) -> dict:
    response = requests.get(
        STRAVA_ATHLETE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    return response.json()


def fetch_activities(access_token: str, per_page: int = 60) -> list[dict]:
    response = requests.get(
        STRAVA_ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": per_page, "page": 1},
        timeout=30,
    )
    data = response.json()
    return data if isinstance(data, list) else []


def build_analysis_payload(request: Request) -> dict:
    access_token = get_current_access_token(request)
    if not access_token:
        return {"error": "not_authenticated"}

    athlete = fetch_athlete(access_token)
    activities = fetch_activities(access_token)
    activities = enrich_runs_with_activity_details(access_token, activities)

    race = get_current_race(request)

    training = compute_training(activities)
    quality_blocks = detect_quality_blocks(activities, race["goal_time"])
    fatigue = compute_fatigue_signal(activities)
    last_key_session = build_last_key_session(quality_blocks)
    weeks_left = weeks_to_race(race["date"])

    prediction = training.get("prediction", {})
    if not isinstance(prediction, dict):
        prediction = {}

    prediction = {
        "predicted_time": prediction.get("predicted_time", "—"),
        "range_low": prediction.get("range_low", "—"),
        "range_high": prediction.get("range_high", "—"),
        "minutes_vs_goal": prediction.get("minutes_vs_goal", 0),
    }

    progress = compute_goal_progress(race, prediction, training)
    status = {
        "readiness": progress.get("status", "unknown"),
        "readiness_label": progress.get("label", "Sin datos"),
        "main_lever": progress.get("main_lever", ""),
    }

    return {
        "athlete": athlete,
        "race": race,
        "status": status,
        "prediction": prediction,
        "training": training,
        "quality_blocks": quality_blocks,
        "fatigue": fatigue,
        "last_key_session": last_key_session,
        "weeks_to_race": weeks_left,
    }


def render_dashboard_html(data: dict) -> str:
    if data.get("error") == "not_authenticated":
        return """
        <!doctype html>
        <html lang="es">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>SecondCoach</title>
          <style>
            body { font-family: -apple-system,BlinkMacSystemFont,sans-serif; background:#f6f7fb; padding:24px; }
            .card { max-width:520px; margin:40px auto; background:#fff; border-radius:16px; padding:24px; box-shadow:0 10px 30px rgba(0,0,0,.08); text-align:center; }
            a { display:inline-block; margin-top:18px; background:#111827; color:#fff; padding:12px 18px; border-radius:12px; text-decoration:none; font-weight:700; }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>SecondCoach</h1>
            <p>Conecta tu cuenta de Strava para ver tu análisis.</p>
            <a href="/login">Conectar con Strava</a>
          </div>
        </body>
        </html>
        """

    logo = get_logo_data_uri()
    athlete = data.get("athlete", {})
    race = data.get("race", {})
    status = data.get("status", {})
    prediction = data.get("prediction", {})
    training = data.get("training", {})
    fatigue = data.get("fatigue", {})
    last_key_session = data.get("last_key_session", {})
    athlete_name = athlete.get("firstname", "Atleta")

    readiness = status.get("readiness_label", "Sin datos")
    main_lever = status.get("main_lever", "")
    predicted_time = prediction.get("predicted_time", "—")
    range_low = prediction.get("range_low", "—")
    range_high = prediction.get("range_high", "—")
    km_7 = training.get("km_last_7_days", "—")
    km_14 = training.get("km_last_14_days", "—")
    km_28 = training.get("km_last_28_days", "—")
    long_run = training.get("long_run_km", "—")
    fatigue_label = fatigue.get("signal_label", "Sin datos")
    fatigue_reason = fatigue.get("reason", "—")
    session_text = last_key_session.get("summary", "Sin sesión clave reciente.")

    return f"""
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>SecondCoach · Dashboard</title>
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, sans-serif;
          background: #f6f7fb;
          margin: 0;
          color: #111827;
        }}
        .wrap {{
          max-width: 860px;
          margin: 0 auto;
          padding: 20px;
        }}
        .header {{
          display: flex;
          gap: 16px;
          align-items: center;
          margin-bottom: 20px;
        }}
        .logo {{
          width: 64px;
          height: 64px;
          border-radius: 16px;
          object-fit: cover;
          background: white;
        }}
        h1 {{
          margin: 0;
          font-size: 28px;
        }}
        .sub {{
          color: #6b7280;
          margin-top: 4px;
        }}
        .grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 16px;
        }}
        .card {{
          background: white;
          border-radius: 18px;
          padding: 18px;
          box-shadow: 0 10px 24px rgba(0,0,0,0.06);
        }}
        .label {{
          color: #6b7280;
          font-size: 14px;
          margin-bottom: 8px;
        }}
        .value {{
          font-size: 28px;
          font-weight: 800;
        }}
        .small {{
          margin-top: 8px;
          color: #4b5563;
          font-size: 14px;
          line-height: 1.4;
        }}
        .section {{
          margin-top: 18px;
        }}
        .actions {{
          margin-top: 18px;
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }}
        .button {{
          display: inline-block;
          text-decoration: none;
          background: #111827;
          color: white;
          padding: 12px 16px;
          border-radius: 12px;
          font-weight: 700;
        }}
        .button.secondary {{
          background: #e5e7eb;
          color: #111827;
        }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="header">
          {"<img class='logo' src='" + logo + "' alt='SecondCoach' />" if logo else ""}
          <div>
            <h1>SecondCoach</h1>
            <div class="sub">{athlete_name}, este es tu estado real hoy.</div>
          </div>
        </div>

        <div class="grid">
          <div class="card">
            <div class="label">Objetivo</div>
            <div class="value">{race.get("goal_time", "—")}</div>
            <div class="small">{race.get("name", "—")} · {race.get("date", "—")}</div>
          </div>

          <div class="card">
            <div class="label">Estado</div>
            <div class="value">{readiness}</div>
            <div class="small">{main_lever}</div>
          </div>

          <div class="card">
            <div class="label">Predicción</div>
            <div class="value">{predicted_time}</div>
            <div class="small">Rango estimado: {range_low} – {range_high}</div>
          </div>

          <div class="card">
            <div class="label">Fatiga</div>
            <div class="value">{fatigue_label}</div>
            <div class="small">{fatigue_reason}</div>
          </div>

          <div class="card">
            <div class="label">Volumen 7 / 14 / 28 días</div>
            <div class="value">{km_7} / {km_14} / {km_28}</div>
            <div class="small">Kilómetros acumulados recientes.</div>
          </div>

          <div class="card">
            <div class="label">Tirada larga</div>
            <div class="value">{long_run}</div>
            <div class="small">Mayor salida larga detectada.</div>
          </div>
        </div>

        <div class="card section">
          <div class="label">Última sesión clave</div>
          <div class="small">{session_text}</div>
        </div>

        <div class="actions">
          <a class="button" href="/analysis">Ver análisis JSON</a>
          <a class="button secondary" href="/onboarding">Editar objetivo</a>
          <a class="button secondary" href="/login">Reconectar Strava</a>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/")
@app.head("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=307)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/login")
def login() -> RedirectResponse:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    return RedirectResponse(url=f"{STRAVA_AUTHORIZE_URL}?{query}", status_code=302)


@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")

    if not code:
        return RedirectResponse(url="/login", status_code=302)

    token_json = exchange_code_for_token(code)

    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")
    expires_at = token_json.get("expires_at")
    athlete = token_json.get("athlete")

    if not access_token or not athlete:
        return RedirectResponse(url="/login", status_code=302)

    athlete_id = athlete.get("id")
    if not athlete_id:
        return RedirectResponse(url="/login", status_code=302)

    save_user(
        strava_athlete_id=athlete_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    request.session["access_token"] = access_token
    request.session["athlete_id"] = athlete_id

    return RedirectResponse(url="/start", status_code=302)


@app.get("/api/analysis")
@app.get("/analysis")
def analysis(request: Request):
    return build_analysis_payload(request)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    data = build_analysis_payload(request)

    if data.get("error") == "not_authenticated":
        return RedirectResponse(url="/login", status_code=302)

    if "race" not in data:
        return RedirectResponse(url="/start", status_code=302)

    return render_dashboard_html(data)


@app.get("/start")
def start(request: Request):
    athlete_id = request.session.get("athlete_id")

    if not athlete_id:
        return RedirectResponse(url="/login", status_code=302)

    goal = get_user_goal(athlete_id)

    if not goal:
        return RedirectResponse(url="/onboarding", status_code=302)

    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding(request: Request):
    athlete_id = request.session.get("athlete_id")

    if not athlete_id:
        return RedirectResponse(url="/login", status_code=302)

    goal = get_user_goal(athlete_id)
    if goal:
        return RedirectResponse(url="/dashboard", status_code=302)

    return """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>SecondCoach · Objetivo</title>
      <style>
        body {
          font-family: -apple-system, BlinkMacSystemFont, sans-serif;
          background: #f6f7fb;
          margin: 0;
          padding: 24px;
          color: #111827;
        }
        .card {
          max-width: 520px;
          margin: 24px auto;
          background: #ffffff;
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 10px 30px rgba(0,0,0,0.08);
        }
        h1 {
          font-size: 28px;
          margin: 0 0 8px 0;
        }
        p {
          color: #4b5563;
          margin: 0 0 24px 0;
        }
        label {
          display: block;
          font-weight: 600;
          margin: 16px 0 8px 0;
        }
        input, select {
          width: 100%;
          padding: 14px;
          border: 1px solid #d1d5db;
          border-radius: 12px;
          font-size: 16px;
          box-sizing: border-box;
          background: #fff;
        }
        button {
          width: 100%;
          margin-top: 24px;
          padding: 14px;
          border: 0;
          border-radius: 12px;
          background: #111827;
          color: white;
          font-size: 16px;
          font-weight: 700;
          cursor: pointer;
        }
        .note {
          margin-top: 14px;
          font-size: 14px;
          color: #6b7280;
        }
        .error {
          color: #b91c1c;
          margin-top: 12px;
          display: none;
        }
      </style>
    </head>
    <body>
      <div class="card">
        <h1>¿Para qué carrera entrenas?</h1>
        <p>Cuéntanos tu objetivo y ajustaremos el análisis a tu realidad.</p>

        <form id="goal-form">
          <label for="race_type">Tipo de carrera</label>
          <select id="race_type" name="race_type" required>
            <option value="marathon">Maratón</option>
            <option value="half_marathon">Media maratón</option>
            <option value="other">Otro</option>
          </select>

          <label for="race_name">Nombre de la carrera</label>
          <input id="race_name" name="race_name" type="text" placeholder="Ej. Maratón de Zaragoza" required />

          <label for="race_date">Fecha</label>
          <input id="race_date" name="race_date" type="date" required />

          <label for="goal_time">Objetivo</label>
          <input id="goal_time" name="goal_time" type="text" placeholder="Ej. 3:30" required />

          <button type="submit">Guardar y continuar</button>
          <div id="error" class="error">No se pudo guardar. Inténtalo de nuevo.</div>
        </form>

        <div class="note">Dato → interpretación → decisión. Ese será el criterio de SecondCoach.</div>
      </div>

      <script>
        const form = document.getElementById("goal-form");
        const errorBox = document.getElementById("error");

        form.addEventListener("submit", async (e) => {
          e.preventDefault();
          errorBox.style.display = "none";

          const payload = {
            race_type: document.getElementById("race_type").value,
            race_name: document.getElementById("race_name").value,
            race_date: document.getElementById("race_date").value,
            goal_time: document.getElementById("goal_time").value
          };

          const response = await fetch("/api/goal", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          });

          const data = await response.json();

          if (!response.ok || data.error) {
            errorBox.style.display = "block";
            return;
          }

          window.location.href = "/dashboard";
        });
      </script>
    </body>
    </html>
    """


@app.post("/api/goal")
def api_save_goal(request: Request, payload: dict = Body(...)):
    athlete_id = request.session.get("athlete_id")

    if not athlete_id:
        return {"error": "not_authenticated"}

    save_user_goal(
        strava_athlete_id=athlete_id,
        race_type=payload.get("race_type"),
        race_name=payload.get("race_name"),
        race_date=payload.get("race_date"),
        goal_time=payload.get("goal_time"),
    )

    return {"status": "ok"}


@app.get("/api/goal")
def api_read_goal(request: Request):
    athlete_id = request.session.get("athlete_id")

    if not athlete_id:
        return {"error": "not_authenticated"}

    goal = get_user_goal(athlete_id)
    return goal or {}


@app.get("/p/{athlete_id}", response_class=HTMLResponse)
def public_page(athlete_id: int):
    return f"""
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>SecondCoach · Atleta</title>
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, sans-serif;
          background:#f6f7fb;
          margin:0;
          padding:24px;
          color:#111827;
        }}
        .card {{
          max-width:640px;
          margin:24px auto;
          background:#fff;
          border-radius:16px;
          padding:24px;
          box-shadow:0 10px 30px rgba(0,0,0,.08);
        }}
      </style>
    </head>
    <body>
      <div class="card">
        <h1>Perfil público del atleta {athlete_id}</h1>
        <p>Esta vista pública sigue disponible para compartir progreso desde SecondCoach.</p>
      </div>
    </body>
    </html>
    """


@app.get("/share/{athlete_id}.png")
def share_image(athlete_id: int):
    return Response(status_code=204)


@app.get("/marathon_pace")
def marathon_pace():
    return {"status": "ok"}