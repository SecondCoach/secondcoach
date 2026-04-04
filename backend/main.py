import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from backend.views.share_renderers import _render_share_png, _render_share_story_png
from backend.views.share_helpers import _share_colors_from_payload
from backend.analysis_payload import build_analysis_payload_from_runs
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from backend.activity_details import enrich_runs_with_activity_details
from backend.db import get_user_by_athlete_id, init_db, upsert_user
from backend.plan_validator import validate_plan

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secondcoach")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me")

STRAVA_OAUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ATHLETE_URL = "https://www.strava.com/api/v3/athlete"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


class ValidatePlanRequest(BaseModel):
    plan_text: str | None = None
    plan: str | None = None
    objective: str | None = None
    goal_time: str | None = None
    race_date: str | None = None


class RaceDateRequest(BaseModel):
    race_date: str | None = None


app = FastAPI(title="SecondCoach MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

if os.path.isdir(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.on_event("startup")
def startup_event() -> None:
    init_db()



def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default



def fetch_athlete_profile(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(STRAVA_ATHLETE_URL, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_recent_runs(access_token: str, per_page: int = 200) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    after_ts = int(time.time()) - (84 * 24 * 3600)

    runs: list[dict[str, Any]] = []
    page = 1

    while True:
        params = {
            "per_page": per_page,
            "page": page,
            "after": after_ts,
        }
        response = requests.get(
            STRAVA_ACTIVITIES_URL,
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        activities = response.json() or []
        if not activities:
            break

        for activity in activities:
            if str(activity.get("type", "")).lower() != "run":
                continue
            runs.append(activity)

        if len(activities) < per_page:
            break

        page += 1

    return runs


def _safe_enrich_runs_with_activity_details(
    access_token: str,
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        enriched_candidates = enrich_runs_with_activity_details(runs, headers)

        if not enriched_candidates:
            return runs

        enriched_by_id = {
            int(item.get("id")): item
            for item in enriched_candidates
            if item.get("id") is not None
        }

        merged_runs: list[dict[str, Any]] = []
        for run in runs:
            run_id = run.get("id")
            if run_id is not None and int(run_id) in enriched_by_id:
                merged_runs.append(enriched_by_id[int(run_id)])
            else:
                merged_runs.append(run)

        return merged_runs

    except Exception:
        logger.exception("No se pudieron enriquecer los runs con activity details")
        return runs


def _upsert_user_compatible(
    athlete_id: int | str | None,
    first_name: str | None,
    last_name: str | None,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: int | float | None,
    race_date: str | None = None,
    goal_time: str | None = None,
    objective: str | None = None,
) -> None:
    if athlete_id is None:
        raise ValueError("athlete_id is required")

    athlete_id_int = int(athlete_id)
    expires_at_int = int(expires_at) if expires_at is not None else None

    upsert_user(
        athlete_id_int,
        access_token or "",
        refresh_token,
        expires_at_int,
    )


def refresh_access_token_if_needed(user: dict[str, Any]) -> str:
    access_token = user.get("access_token")
    refresh_token = user.get("refresh_token")
    expires_at = _safe_int(user.get("expires_at"), 0)

    if access_token and expires_at > int(time.time()) + 120:
        return access_token

    if not refresh_token:
        return access_token or ""

    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    new_access_token = data.get("access_token")
    new_refresh_token = data.get("refresh_token", refresh_token)
    new_expires_at = data.get("expires_at", expires_at)

    _upsert_user_compatible(
        athlete_id=user.get("strava_athlete_id") or user.get("athlete_id"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_at=new_expires_at,
        race_date=user.get("race_date"),
        goal_time=user.get("goal_time"),
        objective=user.get("objective"),
    )

    return new_access_token


def build_analysis_payload(
    access_token: str,
    user: dict[str, Any] | None = None,
    objective_override: str | None = None,
) -> dict[str, Any]:
    user = user or {}

    base_runs = fetch_recent_runs(access_token)
    runs = _safe_enrich_runs_with_activity_details(access_token, base_runs)

    return build_analysis_payload_from_runs(
        runs=runs,
        user=user,
        objective_override=objective_override,
    )

def render_dashboard_html(data: dict[str, Any] | None = None) -> str:
    if not data or not data.get("one_line"):
        return """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>SecondCoach</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body style="margin:0;background:#0b1020;color:white;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:720px;margin:60px auto;padding:24px;text-align:center;">
    <h1 style="margin-bottom:12px;">SecondCoach</h1>
    <p style="opacity:.8;margin-bottom:24px;">Conecta Strava para ver tu lectura.</p>
    <a href="/login" style="display:inline-block;padding:12px 20px;background:#FC4C02;color:white;border-radius:10px;text-decoration:none;font-weight:600;">Conectar Strava</a>
  </div>
</body>
</html>"""

    one = data.get("one_line") or {}
    coach = data.get("coach") or {}
    status = data.get("status") or {}
    last_key_session = data.get("last_key_session") or {}
    chip = str(one.get("chip") or "")
    headline = str(one.get("headline") or "")
    subline = str(one.get("subline") or "")
    action = str(one.get("action") or "")
    objective = str(data.get("objective") or "")
    short_goal_product_evidence = data.get("short_goal_product_evidence") or []

    _bg_color, _card_color, chip_color = _share_colors_from_payload(data)

    training = data.get("training") or {}
    fatigue = data.get("fatigue") or {}
    weekly_km_raw = training.get("weekly_average_km")
    long_run_km_raw = training.get("long_run_km")
    weekly_km = str(int(round(float(weekly_km_raw)))) if weekly_km_raw not in (None, "") else "-"
    long_run_km = str(int(round(float(long_run_km_raw)))) if long_run_km_raw not in (None, "") else "-"
    km7 = training.get("km_last_7_days", 0) or 0
    avg_week = training.get("weekly_average_km", 0) or 0
    fatigue_label = str(fatigue.get("label") or "")
    load_ratio = (km7 / avg_week) if avg_week else 0
    coach_next_focus = str(coach.get("next_focus") or "")
    coach_summary = str(coach.get("summary") or "")
    status_label = str(status.get("status_label") or "")
    status_goal = str(status.get("goal") or "")
    status_prediction = str(status.get("prediction") or "")

    def _format_dashboard_date(value: Any) -> str:
        raw = str(value or "").strip()
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            year, month, day = raw[:10].split("-")
            return f"{day}-{month}-{year}"
        return raw

    if objective in {"10k", "5k"} and short_goal_product_evidence:
        evidence_items = short_goal_product_evidence
        if chip == "POR DETRÁS":
            now_actions = [
                "Tu nivel actual no sostiene ese objetivo",
                "Te falta ritmo útil cerca del objetivo",
                "O ajustas objetivo o subes nivel",
            ]
        elif chip == "EN OBJETIVO":
            now_actions = [
                "No necesitas más volumen por inercia",
                "Ahora toca repetir calidad con continuidad",
                "Protege el ritmo útil antes que sumar kilómetros",
            ]
        else:
            now_actions = [
                "Sostén la consistencia sin vaciarte",
                "Mete una sesión rápida bien hecha esta semana",
                "Evita convertir un objetivo corto en volumen sin más",
            ]
    elif fatigue_label == "Alta" or load_ratio >= 1.15:
        evidence_items = [
            f"Esta semana llevas {km7} km",
            f"Tu media habitual está en {avg_week} km/semana",
            "Estás por encima de tu carga normal",
        ]
        now_actions = [
            "No subas más carga esta semana",
            "Ahora toca asimilar, no sumar por sumar",
            "Mantén una sola sesión útil y llega fresco",
        ]
    elif chip == "POR DETRÁS":
        evidence_items = [
            f"Tu volumen actual está en {weekly_km} km/semana",
            f"Tu tirada larga está en {long_run_km} km",
            "Hoy tu objetivo y tu nivel no encajan",
        ]
        now_actions = [
            "Tu nivel actual no sostiene ese objetivo",
            "Te falta trabajo útil, no solo sumar",
            "O bajas objetivo o subes nivel",
        ]
    elif chip == "EN OBJETIVO":
        evidence_items = [
            f"Estás en {weekly_km} km/semana",
            f"Tu tirada larga está en {long_run_km} km",
            "Ya hay trabajo a ritmo objetivo",
        ]
        now_actions = [
            "No necesitas más volumen",
            "El límite está en sostener el ritmo objetivo",
            "Repite una sesión clara de ritmo esta semana",
        ]
    else:
        evidence_items = [
            f"Estás en {weekly_km} km/semana",
            f"Tu tirada larga está en {long_run_km} km",
            "Necesitas más continuidad útil",
        ]
        now_actions = [
            "Sostén la consistencia esta semana",
            "Haz una sesión útil, no solo sumar",
            "Evita picos de carga innecesarios",
        ]

    now_primary = coach_next_focus or action or "Sostén una semana útil y sin ruido."
    now_support = ""
    if action and action != now_primary:
        now_support = action
    elif coach_summary and coach_summary != now_primary:
        now_support = coach_summary
    if len(now_support) > 140:
        now_support = now_support[:137].rstrip() + "..."

    if fatigue_label == "Alta":
        trend_headline = "Hoy pesa más cómo estás asimilando."
        trend_body = "La lectura de hoy parece más condicionada por la carga reciente que por una mejora clara."
    elif chip == "POR DELANTE":
        trend_headline = "La lectura de hoy va en buena dirección."
        trend_body = "Hoy tu nivel parece ir por delante de lo que exige tu objetivo."
    elif chip == "EN OBJETIVO":
        trend_headline = "La lectura de hoy se sostiene."
        trend_body = "Ahora mismo la señal encaja con el objetivo que estás buscando."
    elif chip == "CERCA":
        trend_headline = "La lectura mejora, pero aún no se consolida."
        trend_body = "Hay señal útil, pero todavía hace falta repetir semanas buenas sin romper la continuidad."
    elif chip == "POR DETRÁS":
        trend_headline = "La lectura aún no está donde quieres."
        trend_body = "Todavía falta que tu entrenamiento sostenga mejor el nivel que estás buscando."
    else:
        trend_headline = "Todavía no hay una dirección clara."
        trend_body = "A día de hoy hay señal, pero no lo bastante limpia como para leer más que una tendencia prudente."

    if status_goal and status_prediction:
        trend_body = f"{trend_body} Hoy la lectura va de {status_prediction} frente a un objetivo de {status_goal}."
    elif status_label:
        trend_body = f"{trend_body} Estado actual: {status_label}."

    session_headline = "Todavía no hay una sesión que cambie la lectura."
    session_body = "Cuando aparezca una sesión realmente importante, la verás aquí con fecha y por qué pesa ahora."
    if last_key_session:
        session_type = str(last_key_session.get("type") or "sesión clave")
        session_date = _format_dashboard_date(last_key_session.get("date"))
        session_distance = last_key_session.get("distance_km")
        distance_text = f" de {session_distance} km" if session_distance not in (None, "") else ""
        session_headline = "Esta es la sesión que más pesa ahora."
        session_body = f"{session_type.capitalize()}{distance_text} el {session_date}. Es la sesión que más está inclinando tu lectura a día de hoy."

    evidence_html = "".join(
        [
            f"<div style='padding:16px;border-radius:16px;background:#0f172a;border:1px solid #25304d;'><div style='font-size:17px;line-height:1.55;font-weight:600;'>{item}</div></div>"
            for item in evidence_items
        ]
    )

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>SecondCoach</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body style="margin:0;background:#0b1020;color:white;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:760px;margin:40px auto;padding:24px;box-sizing:border-box;">

    <div style="background:linear-gradient(180deg,#141d35 0%,#121a30 100%);border:1px solid #31405f;border-radius:22px;padding:28px 26px 24px 26px;margin-bottom:22px;box-shadow:0 18px 40px rgba(0,0,0,.22);">
      <div style="margin-bottom:14px;">
        <span style="display:inline-block;padding:8px 13px;border-radius:999px;background:{chip_color};color:white;font-size:12px;font-weight:800;letter-spacing:.02em;">
          {chip}
        </span>
      </div>

      <h1 style="font-size:40px;line-height:1.06;margin:0 0 12px 0;max-width:11ch;">
        {headline}
      </h1>

      <p style="font-size:18px;line-height:1.5;opacity:.84;margin:0 0 18px 0;max-width:42ch;">
        {subline}
      </p>

      <p style="font-size:21px;line-height:1.42;font-weight:800;margin:0;max-width:34ch;">
        {action}
      </p>
    </div>

    <div style="background:#121a30;border:1px solid #32415f;border-radius:20px;padding:22px 24px;margin-bottom:20px;box-shadow:0 10px 24px rgba(0,0,0,.12);">
      <div style="font-size:13px;opacity:.65;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">Qué haría ahora</div>
      <h2 style="font-size:30px;line-height:1.16;margin:0 0 8px 0;max-width:22ch;">{now_primary}</h2>
      <p style="font-size:16px;line-height:1.55;opacity:.8;margin:0;max-width:46ch;">{now_support}</p>
    </div>

    <div style="background:#121a30;border:1px solid #25304d;border-radius:18px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:13px;opacity:.65;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">Lo que veo</div>
      <div style="display:grid;gap:10px;">
        {evidence_html}
      </div>
    </div>

    <div style="background:#121a30;border:1px solid #25304d;border-radius:18px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:13px;opacity:.65;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">Tu tendencia</div>
      <h2 style="font-size:28px;line-height:1.18;margin:0 0 10px 0;">{trend_headline}</h2>
      <p style="font-size:17px;line-height:1.6;opacity:.88;margin:0;">{trend_body}</p>
    </div>

    <div style="background:#121a30;border:1px solid #25304d;border-radius:18px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:13px;opacity:.65;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">La sesión que más pesa ahora</div>
      <h2 style="font-size:26px;line-height:1.2;margin:0 0 10px 0;max-width:24ch;">{session_headline}</h2>
      <p style="font-size:17px;line-height:1.6;opacity:.88;margin:0;">{session_body}</p>
    </div>

    <div style="background:#121a30;border:1px solid #25304d;border-radius:18px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:13px;opacity:.65;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">Compartir</div>
      <p style="font-size:17px;line-height:1.6;opacity:.84;margin:0 0 16px 0;max-width:40ch;">Si esta lectura explica bien dónde estás, compártela en el formato vertical que mejor encaja con el producto.</p>
      <a href="/share_story" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#FC4C02;color:white;text-decoration:none;font-weight:700;">Compartir</a>
    </div>

    <div style="background:#121a30;border:1px solid #25304d;border-radius:18px;padding:20px 24px;">
      <div style="font-size:13px;opacity:.65;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px;">Ver plan / qué cambiaría esta semana</div>
      <p style="font-size:17px;line-height:1.6;opacity:.84;margin:0 0 16px 0;max-width:42ch;">Si quieres bajar esta lectura a decisiones concretas, aquí es donde la convertimos en semana real.</p>
      <a href="/plan" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#0f172a;border:1px solid #25304d;color:white;text-decoration:none;font-weight:700;">Analizar mi semana</a>
    </div>

  </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        athlete_id = request.session.get("athlete_id")
        if not athlete_id:
            return HTMLResponse(render_dashboard_html())

        user = get_user_by_athlete_id(athlete_id)
        if not user:
            return HTMLResponse(render_dashboard_html({"error": "user_not_found"}))

        access_token = refresh_access_token_if_needed(user)
        objective_override = request.query_params.get("objective")
        goal_time_override = request.query_params.get("goal_time")
        data = build_analysis_payload(access_token, user={**user, "goal_time": goal_time_override or user.get("goal_time")}, objective_override=objective_override)
        return HTMLResponse(render_dashboard_html(data))
    except Exception:
        logger.exception("Error renderizando dashboard principal")
        return HTMLResponse(render_dashboard_html({"error": "analysis_error"}))


@app.get("/dashboard")
async def dashboard():
    return RedirectResponse("/", status_code=302)


@app.get("/login")
async def login():
    if not STRAVA_CLIENT_ID or not STRAVA_REDIRECT_URI:
        return HTMLResponse("Faltan variables de entorno de Strava", status_code=500)

    params = {
        "client_id": STRAVA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": STRAVA_REDIRECT_URI,
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    return RedirectResponse(f"{STRAVA_OAUTH_URL}?{query}")


@app.get("/callback")
@app.get("/auth/strava/callback")
async def auth_callback(code: str, request: Request):
    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_at = data.get("expires_at")

    athlete = fetch_athlete_profile(access_token)
    athlete_id = athlete.get("id")

    existing_user = get_user_by_athlete_id(athlete_id) or {}

    _upsert_user_compatible(
        athlete_id=athlete_id,
        first_name=athlete.get("firstname"),
        last_name=athlete.get("lastname"),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        race_date=existing_user.get("race_date"),
        goal_time=existing_user.get("goal_time") or "3:30",
        objective=existing_user.get("objective") or "Maratón",
    )

    request.session["athlete_id"] = athlete_id
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


@app.get("/api/analysis")
async def analysis(request: Request):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return {"error": "no_session"}

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return {"error": "user_not_found", "athlete_id": athlete_id}

    access_token = refresh_access_token_if_needed(user)
    objective_override = request.query_params.get("objective")
    goal_time_override = request.query_params.get("goal_time")
    return build_analysis_payload(access_token, user={**user, "goal_time": goal_time_override or user.get("goal_time")}, objective_override=objective_override)


@app.post("/api/validate")
async def validate(request: Request, payload: ValidatePlanRequest):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return {"error": "no_session"}

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return {"error": "user_not_found", "athlete_id": athlete_id}

    access_token = refresh_access_token_if_needed(user)
    analysis_payload = build_analysis_payload(access_token, user=user)

    plan_text = payload.plan_text or payload.plan or ""
    objective = payload.objective or user.get("objective") or "Maratón"
    race_date = payload.race_date or user.get("race_date")

    validation = validate_plan(
        plan_text=plan_text,
        objective=objective,
        training=analysis_payload.get("training") or {},
        fatigue=analysis_payload.get("fatigue") or {},
        race_date=race_date,
    )

    return validation


@app.post("/api/race-date")
async def update_race_date(request: Request, payload: RaceDateRequest):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return {"error": "no_session"}

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return {"error": "user_not_found", "athlete_id": athlete_id}

    _upsert_user_compatible(
        athlete_id=user.get("strava_athlete_id") or user.get("athlete_id"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        access_token=user.get("access_token"),
        refresh_token=user.get("refresh_token"),
        expires_at=user.get("expires_at"),
        race_date=payload.race_date,
        goal_time=user.get("goal_time"),
        objective=user.get("objective"),
    )

    return {"ok": True, "race_date": payload.race_date}


@app.get("/plan", response_class=HTMLResponse)
async def plan_page(request: Request):
    return HTMLResponse(
        """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>SecondCoach — Analizar mi semana</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { margin:0; background:#0b1020; color:white; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    .wrap { max-width:880px; margin:0 auto; padding:28px 20px 48px; box-sizing:border-box; }
    .hero h1 { margin:0 0 10px 0; font-size:34px; line-height:1.1; }
    .hero p { margin:0 0 18px 0; font-size:18px; line-height:1.45; opacity:.86; }
    .card { background:#121a30; border:1px solid #25304d; border-radius:18px; padding:20px; margin-bottom:18px; box-sizing:border-box; }
    .label { font-size:12px; letter-spacing:.04em; text-transform:uppercase; opacity:.65; margin-bottom:10px; }
    textarea { width:100%; min-height:220px; background:#0f172a; color:white; border:1px solid #334155; border-radius:14px; padding:14px; box-sizing:border-box; font-size:16px; line-height:1.5; resize:vertical; }
    button { margin-top:14px; border:0; border-radius:12px; background:#FC4C02; color:white; padding:12px 18px; font-size:16px; font-weight:700; cursor:pointer; }
    .resultTitle { margin:0 0 8px 0; font-size:24px; line-height:1.2; }
    .resultText { margin:0; font-size:17px; line-height:1.6; opacity:.92; }
    .list { margin:0; padding-left:18px; font-size:16px; line-height:1.7; opacity:.92; }
    .weekRow { display:grid; grid-template-columns:130px 1fr; gap:12px; padding:10px 0; border-top:1px solid #25304d; }
    .weekRow:first-child { border-top:0; padding-top:0; }
    .dayName { font-weight:700; opacity:.95; }
    .dayText { opacity:.9; line-height:1.5; }
    .muted { opacity:.7; }
  </style>
</head>
<body>
  <div class="wrap">
<div style="display:flex;gap:12px;flex-wrap:wrap;margin:0 0 18px 0;">
  <a href="/" style="display:inline-block;padding:10px 14px;border-radius:12px;background:#0f172a;border:1px solid #25304d;color:white;text-decoration:none;font-weight:700;">Dashboard</a>
  <a href="/share_story" style="display:inline-block;padding:10px 14px;border-radius:12px;background:#0f172a;border:1px solid #25304d;color:white;text-decoration:none;font-weight:700;">Compartir</a>
</div>
    <div class="hero">
      <h1>Analizar mi semana</h1>
      <p>Pega tu semana y SecondCoach te dirá si ahora mismo tiene sentido para ti, qué pesa de verdad y qué cambiaría.</p>
    </div>

    <div class="card">
      <div class="label">Tu semana</div>
      <textarea id="planText" placeholder="Lunes descanso
Martes series 6x1000
Miércoles 45 min suave
Jueves ritmo controlado
Viernes descanso
Sábado 50 min suave
Domingo tirada larga"></textarea>
      <button onclick="analyze()">Analizar mi semana</button>
    </div>

    <div id="humanResult">
      <div class="card">
        <div class="label">Lectura</div>
        <p class="resultText muted">Todavía no has analizado ninguna semana.</p>
      </div>
    </div>
  </div>

<script>
function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;");
}

function renderList(title, items) {
  if (!items || !items.length) return "";
  var html = '<div class="card"><div class="label">' + escapeHtml(title) + '</div><ul class="list">';
  for (var i = 0; i < items.length; i += 1) {
    html += '<li>' + escapeHtml(items[i]) + '</li>';
  }
  html += '</ul></div>';
  return html;
}

function renderWeek(week) {
  if (!week) return "";
  var ordered = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "notas"];
  var html = '<div class="card"><div class="label">Semana propuesta</div>';
  for (var i = 0; i < ordered.length; i += 1) {
    var key = ordered[i];
    if (!(key in week)) continue;
    if (key === "notas") {
      var notes = week[key] || [];
      if (notes.length) {
        html += '<div style="margin-top:10px"><div class="label" style="margin-bottom:8px">Notas</div><ul class="list">';
        for (var j = 0; j < notes.length; j += 1) {
          html += '<li>' + escapeHtml(notes[j]) + '</li>';
        }
        html += '</ul></div>';
      }
      continue;
    }
    html += '<div class="weekRow"><div class="dayName">' + escapeHtml(key) + '</div><div class="dayText">' + escapeHtml(week[key]) + '</div></div>';
  }
  html += '</div>';
  return html;
}

async function analyze() {
  var text = document.getElementById("planText").value.trim();
  var result = document.getElementById("humanResult");

  if (!text) {
    result.innerHTML = '<div class="card"><div class="label">Lectura</div><p class="resultText">Antes de analizar nada, pega una semana escrita día por día.</p></div>';
    return;
  }

  result.innerHTML = '<div class="card"><div class="label">Lectura</div><p class="resultText">Analizando tu semana...</p></div>';

  var res = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_text: text })
  });

  var data = await res.json();

  if (data.error === "no_session") {
    result.innerHTML = '<div class="card"><div class="label">Lectura</div><p class="resultText">Necesitas iniciar sesión con Strava para analizar tu semana con tu contexto real.</p></div>';
    return;
  }

  if (data.error) {
    result.innerHTML = '<div class="card"><div class="label">Lectura</div><p class="resultText">No he podido analizar la semana ahora mismo.</p></div>';
    return;
  }

  var html = '<div class="card"><div class="label">Estado</div><h2 class="resultTitle">' + escapeHtml(data.estado || data.summary || "Lectura de la semana") + '</h2>';
  if (data.foco) {
    html += '<p class="resultText" style="margin-bottom:10px"><strong>Lo que pesa ahora:</strong> ' + escapeHtml(data.foco) + '</p>';
  }
  if (data.decision) {
    html += '<p class="resultText"><strong>Qué haría ahora:</strong> ' + escapeHtml(data.decision) + '</p>';
  }
  html += '</div>';
  html += renderList("Lo mejor de la semana", data.positives || []);
  html += renderList("Lo que me hace dudar", data.reasons || []);
  html += renderList("Qué cambiaría", data.actions || data.recommended_changes || []);
  if (data.proposed_week_summary) {
    html += '<div class="card"><div class="label">Resumen de la semana propuesta</div><p class="resultText">' + escapeHtml(data.proposed_week_summary) + '</p></div>';
  }
  html += renderWeek(data.proposed_week || {});
  result.innerHTML = html;
}
</script>
</body>
</html>
"""
    )



def render_share_html(data: dict[str, Any]) -> str:
    one = data.get("one_line") or {}
    headline = one.get("headline", "")
    subline = one.get("subline", "")
    action = one.get("action", "")
    chip = one.get("chip", "SECONDCOACH")
    bg_color, card_color, accent_color = _share_colors_from_payload(data)

    logo_html = ""
    if os.path.exists(os.path.join(ASSETS_DIR, "icon.png")):
        logo_html = """
        <div class="brandRow">
          <img src="/assets/icon.png" alt="SecondCoach" class="brandLogo" />
          <div class="brand">SecondCoach</div>
        </div>
        """
    else:
        logo_html = '<div class="brand">SecondCoach</div>'


    nav_html = """
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:28px;">
          <a href="/" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#0f172a;border:1px solid #25304d;color:white;text-decoration:none;font-weight:700;font-size:18px;">Volver al dashboard</a>
          <a href="/share_story" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#FC4C02;color:white;text-decoration:none;font-weight:700;font-size:18px;">Ver versión story</a>
        </div>
    """
    return f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SecondCoach</title>
<style>
body {{
    margin: 0;
    min-height: 100vh;
    background: {bg_color};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 8px;
    box-sizing: border-box;
}}
.card {{
    width: min(1580px, 100%);
    padding: 74px 86px 78px 86px;
    border-radius: 34px;
    background: {card_color};
    border: 1px solid #22345f;
    box-sizing: border-box;
}}
.badge {{
    display: inline-block;
    padding: 14px 34px;
    border-radius: 999px;
    background: {accent_color};
    color: white;
    font-weight: 800;
    font-size: 24px;
    margin-bottom: 38px;
}}
.headline {{
    font-size: 96px;
    line-height: 1.06;
    font-weight: 800;
    margin-bottom: 34px;
    max-width: 1280px;
}}
.subline {{
    font-size: 34px;
    line-height: 1.38;
    color: #c8d2ea;
    margin-bottom: 32px;
    max-width: 1120px;
}}
.action {{
    font-size: 44px;
    line-height: 1.32;
    font-weight: 800;
    margin-bottom: 64px;
    max-width: 1120px;
}}
.brand {{
    font-size: 28px;
    color: #FC4C02;
    font-weight: 800;
}}
.brandRow {{
    display: flex;
    align-items: center;
    gap: 18px;
}}
.brandLogo {{
    width: 116px;
    height: 116px;
    object-fit: contain;
    flex: 0 0 auto;
}}
</style>
</head>
<body>
<div class="card">
  <div class="badge">{chip}</div>
  <div class="headline">{headline}</div>
  <div class="subline">{subline}</div>
  <div class="action">{action}</div>
  {logo_html}
  {nav_html}
</div>
</body>
</html>
"""


def render_share_story_html(data: dict[str, Any]) -> str:
    one = data.get("one_line") or {}
    headline = one.get("headline", "")
    subline = one.get("subline", "")
    action = one.get("action", "")
    chip = one.get("chip", "SECONDCOACH")
    bg_color, card_color, accent_color = _share_colors_from_payload(data)

    logo_html = ""
    if os.path.exists(os.path.join(ASSETS_DIR, "icon.png")):
        logo_html = """
        <div class="brandRow">
          <img src="/assets/icon.png" alt="SecondCoach" class="brandLogo" />
          <div class="brand">SecondCoach</div>
        </div>
        """
    else:
        logo_html = '<div class="brand">SecondCoach</div>'


    nav_html = """
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:28px;">
          <a href="/" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#0f172a;border:1px solid #25304d;color:white;text-decoration:none;font-weight:700;font-size:18px;">Volver al dashboard</a>
        </div>
    """
    return f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SecondCoach Story</title>
<style>
body {{
    margin: 0;
    min-height: 100vh;
    background: linear-gradient(180deg, {bg_color} 0%, #020816 100%);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 18px;
    box-sizing: border-box;
}}
.story {{
    width: min(420px, 100%);
    min-height: 84vh;
    background: {card_color};
    border: 1px solid #22345f;
    border-radius: 34px;
    box-sizing: border-box;
    padding: 34px 30px 34px 30px;
    display: flex;
    flex-direction: column;
}}
.badge {{
    display: inline-block;
    align-self: flex-start;
    padding: 12px 24px;
    border-radius: 999px;
    background: {accent_color};
    color: white;
    font-weight: 800;
    font-size: 18px;
    margin-bottom: 28px;
}}
.headline {{
    font-size: 52px;
    line-height: 1.05;
    font-weight: 800;
    margin-bottom: 26px;
}}
.subline {{
    font-size: 24px;
    line-height: 1.35;
    color: #c8d2ea;
    margin-bottom: 28px;
}}
.action {{
    font-size: 28px;
    line-height: 1.28;
    font-weight: 800;
    margin-bottom: auto;
}}
.brand {{
    font-size: 24px;
    color: #FC4C02;
    font-weight: 800;
}}
.brandRow {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 28px;
}}
.brandLogo {{
    width: 92px;
    height: 92px;
    object-fit: contain;
    flex: 0 0 auto;
}}
</style>
</head>
<body>
<div class="story">
  <div class="badge">{chip}</div>
  <div class="headline">{headline}</div>
  <div class="subline">{subline}</div>
  <div class="action">{action}</div>
  {logo_html}
  {nav_html}
</div>
</body>
</html>
"""

@app.get("/share", response_class=HTMLResponse)
async def share(request: Request):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return HTMLResponse("<h1>No session</h1>", status_code=400)

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return HTMLResponse("<h1>User not found</h1>", status_code=404)

    access_token = refresh_access_token_if_needed(user)
    goal_time_override = request.query_params.get("goal_time")
    user_override = {**user, "goal_time": goal_time_override or user.get("goal_time")}
    data = build_analysis_payload(access_token, user=user_override)
    return HTMLResponse(render_share_html(data))


@app.get("/share.png")
async def share_png(request: Request):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return Response(status_code=400)

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return Response(status_code=404)

    access_token = refresh_access_token_if_needed(user)
    goal_time_override = request.query_params.get("goal_time")
    user_override = {**user, "goal_time": goal_time_override or user.get("goal_time")}
    data = build_analysis_payload(access_token, user=user_override)
    png_bytes = _render_share_png(data)

    return Response(content=png_bytes, media_type="image/png")


@app.get("/share_story", response_class=HTMLResponse)
async def share_story(request: Request):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return HTMLResponse("<h1>No session</h1>", status_code=400)

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return HTMLResponse("<h1>User not found</h1>", status_code=404)

    access_token = refresh_access_token_if_needed(user)
    goal_time_override = request.query_params.get("goal_time")
    user_override = {**user, "goal_time": goal_time_override or user.get("goal_time")}
    data = build_analysis_payload(access_token, user=user_override)
    return HTMLResponse(render_share_story_html(data))


@app.get("/share_story.png")
async def share_story_png(request: Request):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return Response(status_code=400)

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return Response(status_code=404)

    access_token = refresh_access_token_if_needed(user)
    goal_time_override = request.query_params.get("goal_time")
    user_override = {**user, "goal_time": goal_time_override or user.get("goal_time")}
    data = build_analysis_payload(access_token, user=user_override)
    png_bytes = _render_share_story_png(data)

    return Response(content=png_bytes, media_type="image/png")


@app.get("/health")
async def health():
    return {"ok": True}
