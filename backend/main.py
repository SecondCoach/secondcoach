import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from backend.activity_details import enrich_runs_with_activity_details
from backend.analysis import (
    build_coach,
    build_last_key_session,
    compute_fatigue_signal,
    compute_prediction,
    compute_training,
    detect_quality_blocks,
)
from backend.db import get_user_by_athlete_id, init_db, upsert_user
from backend.plan_validator import validate_plan

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secondcoach")

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


@app.on_event("startup")
def startup_event() -> None:
    init_db()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_time_to_seconds(time_str: str | None) -> int | None:
    if not time_str:
        return None

    raw = str(time_str).strip()
    if not raw:
        return None

    parts = raw.split(":")
    try:
        if len(parts) == 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            return hours * 3600 + minutes * 60
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return None

    return None


def _format_goal_time(goal_time: str | None) -> str | None:
    if not goal_time:
        return None
    raw = str(goal_time).strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    if len(parts) == 3:
        return f"{parts[0]}:{parts[1]}:{parts[2]}"
    return raw


def _extract_delta_minutes(prediction: dict[str, Any], goal_time: str | None) -> int | None:
    direct = prediction.get("minutes_vs_goal")
    if direct is not None:
        return _safe_int(direct)

    predicted_time = prediction.get("predicted_time")
    predicted_seconds = _parse_time_to_seconds(predicted_time)
    goal_seconds = _parse_time_to_seconds(goal_time)

    if predicted_seconds is None or goal_seconds is None:
        return None

    return round((predicted_seconds - goal_seconds) / 60)


def _build_status_block(goal_time: str | None, prediction: dict[str, Any]) -> dict[str, Any]:
    predicted_time = prediction.get("predicted_time")
    delta_minutes = _extract_delta_minutes(prediction, goal_time)

    if delta_minutes is None:
        status_label = "sin suficiente señal"
    elif delta_minutes <= -3:
        status_label = "por delante"
    elif delta_minutes <= 2:
        status_label = "en objetivo"
    elif delta_minutes <= 10:
        status_label = "ligeramente por detrás"
    else:
        status_label = "claramente por detrás"

    return {
        "goal": _format_goal_time(goal_time),
        "prediction": predicted_time,
        "delta_minutes": delta_minutes,
        "status_label": status_label,
    }


def _extract_long_run_km(last_key_session: dict[str, Any] | None) -> float:
    if not last_key_session:
        return 0.0

    for key in ("distance_km", "distance", "km"):
        if key in last_key_session:
            return _safe_float(last_key_session.get(key), 0.0)

    return 0.0


def _derive_product_direction(
    prediction: dict[str, Any],
    training: dict[str, Any],
    fatigue: dict[str, Any],
    quality_blocks: list[dict[str, Any]],
    last_key_session: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    weekly_km = _safe_float(
        training.get("km_last_7_days", training.get("km_last_7", training.get("weekly_average_km", 0.0))),
        0.0,
    )
    weekly_avg_km = _safe_float(training.get("weekly_average_km"), weekly_km)
    long_run_km = _extract_long_run_km(last_key_session)
    long_run_share = (long_run_km / weekly_km) if weekly_km > 0 else 0.0

    debug = prediction.get("debug", {}) or {}
    specificity_km = _safe_float(debug.get("specificity_km"), 0.0)
    avg_block_km = _safe_float(debug.get("avg_block_km"), 0.0)
    fatigue_label = str(
        fatigue.get("label") or debug.get("fatigue_label") or ""
    ).strip().lower()

    delta_minutes = prediction.get("minutes_vs_goal")
    if delta_minutes is None:
        delta_minutes = 0
    delta_minutes = _safe_int(delta_minutes, 0)

    block_count = len(quality_blocks or [])

    if long_run_share >= 0.50:
        primary_insight = (
            "Tu principal limitación ahora no parece ser falta de ambición, "
            "sino cómo se concentra la carga semanal: la tirada larga pesa demasiado "
            "dentro del total reciente."
        )
        next_action = {
            "focus": "distribución de carga",
            "why": "Ahora mismo una parte excesiva del estrés semanal cae en una sola sesión, y eso limita la calidad global que puedes absorber.",
            "impact": "alto",
        }
        adjustment_hint = {
            "current_issue": "La tirada larga concentra demasiado porcentaje del volumen semanal.",
            "proposed_change": "Redistribuir parte del volumen hacia otro rodaje útil o una sesión controlada entre semana.",
            "expected_effect": "Más estabilidad, mejor asimilación y mejor calidad específica sin aumentar demasiado el riesgo.",
        }
        return primary_insight, next_action, adjustment_hint

    if delta_minutes > 2 and weekly_avg_km < 45:
        primary_insight = (
            "Lo que más te limita ahora es el volumen útil sostenido: el objetivo no está lejos, "
            "pero te falta un poco más de base semanal para acercarte con margen."
        )
        next_action = {
            "focus": "volumen semanal útil",
            "why": "Con el nivel actual ya hay señal suficiente para competir bien, pero el margen hacia el objetivo mejora si sube un poco la carga estable.",
            "impact": "alto",
        }
        adjustment_hint = {
            "current_issue": "El volumen medio semanal sigue algo corto para consolidar el objetivo.",
            "proposed_change": "Añadir km fáciles o útiles fuera de la tirada larga, sin convertir cada día en una sesión exigente.",
            "expected_effect": "Más resistencia específica y menor dependencia de una sola sesión clave.",
        }
        return primary_insight, next_action, adjustment_hint

    if delta_minutes > 0 and (specificity_km < 30 or avg_block_km < 8 or block_count < 2):
        primary_insight = (
            "La limitación más clara ahora no es tanto la forma general como la especificidad: "
            "falta acumular un poco más de trabajo claramente maratón dentro de la semana."
        )
        next_action = {
            "focus": "especificidad maratón",
            "why": "Ya existe base suficiente, pero todavía falta que una mayor parte del trabajo reciente se parezca a lo que exige realmente tu objetivo.",
            "impact": "alto",
        }
        adjustment_hint = {
            "current_issue": "La señal específica de maratón todavía es mejorable.",
            "proposed_change": "Aumentar la presencia de bloques controlados y sostenidos dentro de sesiones clave, sin convertirlos en esfuerzos máximos.",
            "expected_effect": "Predicción más sólida y más confianza en el ritmo objetivo.",
        }
        return primary_insight, next_action, adjustment_hint

    if "alta" in fatigue_label or "high" in fatigue_label:
        primary_insight = (
            "Ahora mismo el mayor freno no parece ser capacidad, sino asimilación: "
            "hay suficiente trabajo reciente, pero la fatiga puede impedir convertirlo en mejora real."
        )
        next_action = {
            "focus": "absorber carga",
            "why": "Cuando la fatiga sube, insistir más no siempre mejora el rendimiento; a menudo solo empeora la calidad de las siguientes sesiones.",
            "impact": "medio",
        }
        adjustment_hint = {
            "current_issue": "La carga reciente puede estar pesando demasiado sobre la frescura.",
            "proposed_change": "Mantener intención, pero suavizar uno de los estímulos secundarios y proteger la calidad de las sesiones clave.",
            "expected_effect": "Mejor recuperación y mejor transferencia del trabajo ya hecho.",
        }
        return primary_insight, next_action, adjustment_hint

    primary_insight = (
        "Tu situación actual es bastante estable: no hay una alarma clara, "
        "pero el siguiente salto vendrá más por afinar que por revolucionar el plan."
    )
    next_action = {
        "focus": "consistencia con intención",
        "why": "Cuando la estructura general ya es razonable, lo que más suma suele ser encadenar semanas útiles sin picos innecesarios.",
        "impact": "medio",
    }
    adjustment_hint = {
        "current_issue": "No destaca un fallo grande, pero todavía hay margen para afinar la semana.",
        "proposed_change": "Mantener la estructura y ajustar solo el punto de mayor retorno: reparto de carga, especificidad o frescura según la semana.",
        "expected_effect": "Progreso más estable y decisiones más fáciles de ejecutar.",
    }
    return primary_insight, next_action, adjustment_hint


def _training_tuple_to_dict(training_tuple: tuple[float, float, float]) -> dict[str, Any]:
    km_last_7, avg_week_km, long_run_km = training_tuple
    return {
        "km_last_7_days": km_last_7,
        "km_last_7": km_last_7,
        "weekly_average_km": avg_week_km,
        "avg_week_km": avg_week_km,
        "long_run_km": long_run_km,
    }


def _build_autogenerated_plan_text(
    training: dict[str, Any],
    next_action: dict[str, Any],
) -> str:
    focus = str(next_action.get("focus") or "").lower()
    weekly_km = _safe_float(training.get("weekly_average_km"), 50.0)

    if "distribución" in focus:
        return """
Lunes: descanso o 6-8 km suave
Martes: 10-12 km con 2x4 km ritmo maratón
Miércoles: 8-10 km suave
Jueves: 10-12 km progresivo
Viernes: descanso
Sábado: 8-10 km suave
Domingo: tirada larga 24-28 km
""".strip()

    if "especificidad" in focus:
        return """
Lunes: descanso
Martes: 12 km con 3x4 km ritmo maratón
Miércoles: 8 km suave
Jueves: 10 km con 5 km ritmo maratón
Viernes: descanso
Sábado: 8 km suave
Domingo: tirada larga 26-30 km con últimos 8 km a ritmo maratón
""".strip()

    if weekly_km >= 50:
        return """
Lunes: descanso
Martes: 10-12 km con bloque controlado
Miércoles: 8-10 km suave
Jueves: 8-10 km a ritmo maratón
Viernes: descanso o 6 km muy suaves
Sábado: 8 km suave
Domingo: tirada larga 26-30 km
""".strip()

    return """
Lunes: descanso
Martes: 10 km con cambios de ritmo
Miércoles: 8 km suave
Jueves: 10 km controlado
Viernes: descanso
Sábado: 8 km suave
Domingo: tirada larga 24-28 km
""".strip()


def _extract_proposed_week_lines(validation: dict[str, Any]) -> list[str]:
    proposed_week = validation.get("proposed_week") or {}
    order = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    lines: list[str] = []

    for day in order:
        value = proposed_week.get(day)
        if value:
            lines.append(f"{day.capitalize()}: {value}")

    notes = proposed_week.get("notas") or []
    for note in notes:
        lines.append(f"Nota: {note}")

    return lines


def _build_plan_comparison(
    analysis: dict[str, Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    training = analysis.get("training") or {}
    fatigue = analysis.get("fatigue") or {}
    next_action = analysis.get("next_action") or {}
    coach = analysis.get("coach") or {}
    last_key_session = analysis.get("last_key_session") or {}

    autogenerated_plan = _build_autogenerated_plan_text(training, next_action)

    validated = validate_plan(
        plan_text=autogenerated_plan,
        objective=user.get("objective") or "Maratón",
        training=training,
        fatigue=fatigue,
        race_date=user.get("race_date"),
    )

    differences: list[dict[str, Any]] = []
    for item in validated.get("recommended_adjustments_structured") or []:
        message = item.get("message")
        if not message:
            continue
        differences.append(
            {
                "title": item.get("action_type") or "ajuste",
                "priority": item.get("priority") or "media",
                "message": message,
            }
        )

    if not differences:
        for change in (validated.get("recommended_adjustments") or [])[:3]:
            differences.append(
                {
                    "title": "ajuste",
                    "priority": "media",
                    "message": change,
                }
            )

    return {
        "current": {
            "summary": coach.get("summary") or analysis.get("primary_insight") or "Sin resumen actual.",
            "focus": coach.get("next_focus") or next_action.get("focus") or "Sin foco actual.",
            "last_session": last_key_session,
        },
        "proposed": {
            "summary": validated.get("proposed_week_summary") or "Sin semana propuesta disponible.",
            "week": validated.get("proposed_week") or {},
            "lines": _extract_proposed_week_lines(validated),
        },
        "differences": differences,
    }


def _upsert_user_compatible(
    *,
    athlete_id: Any,
    access_token: Any,
    refresh_token: Any,
    expires_at: Any,
    first_name: Any = None,
    last_name: Any = None,
    race_date: Any = None,
    goal_time: Any = None,
    objective: Any = None,
) -> None:
    attempts = [
        lambda: upsert_user(
            strava_athlete_id=athlete_id,
            first_name=first_name,
            last_name=last_name,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            race_date=race_date,
            goal_time=goal_time,
            objective=objective,
        ),
        lambda: upsert_user(
            strava_athlete_id=athlete_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            race_date=race_date,
            goal_time=goal_time,
            objective=objective,
        ),
        lambda: upsert_user(
            strava_athlete_id=athlete_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        ),
        lambda: upsert_user(
            athlete_id,
            access_token,
            refresh_token,
            expires_at,
        ),
    ]

    last_error: Exception | None = None
    for attempt in attempts:
        try:
            attempt()
            return
        except TypeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error


def refresh_access_token_if_needed(user: dict[str, Any]) -> str:
    access_token = user.get("access_token")
    refresh_token = user.get("refresh_token")
    expires_at = _safe_int(user.get("expires_at"), 0)

    now = int(time.time())
    if access_token and expires_at > now + 120:
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

    athlete = data.get("athlete", {}) or {}
    athlete_id = athlete.get("id") or user.get("strava_athlete_id") or user.get("athlete_id")

    _upsert_user_compatible(
        athlete_id=athlete_id,
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        access_token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        expires_at=data.get("expires_at"),
        race_date=user.get("race_date"),
        goal_time=user.get("goal_time"),
        objective=user.get("objective"),
    )

    return data.get("access_token", "")


def fetch_athlete_profile(access_token: str) -> dict[str, Any]:
    response = requests.get(
        STRAVA_ATHLETE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_recent_runs(access_token: str, per_page: int = 60) -> list[dict[str, Any]]:
    response = requests.get(
        STRAVA_ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": per_page, "page": 1},
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()

    if isinstance(payload, dict):
        message = str(payload.get("message") or "Respuesta inesperada de Strava en /athlete/activities")
        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"{message}: {errors}")
        raise RuntimeError(message)

    if not isinstance(payload, list):
        raise RuntimeError("Strava devolvió un formato inesperado en /athlete/activities")

    runs: list[dict[str, Any]] = []
    for activity in payload:
        if not isinstance(activity, dict):
            continue
        if str(activity.get("type", "")).lower() == "run":
            runs.append(activity)

    return runs


def _safe_enrich_runs_with_activity_details(
    access_token: str,
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    clean_runs = [run for run in runs if isinstance(run, dict)]
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        enriched_subset = enrich_runs_with_activity_details(
            clean_runs,
            headers,
            min_distance_km=18.0,
            max_candidates=12,
            ttl_seconds=600,
        )

        if not isinstance(enriched_subset, list):
            logger.warning(
                "activity_details devolvió un tipo inesperado: %s. Se usarán runs base.",
                type(enriched_subset).__name__,
            )
            return clean_runs

        enriched_by_id: dict[Any, dict[str, Any]] = {}
        for run in enriched_subset:
            if isinstance(run, dict) and run.get("id") is not None:
                enriched_by_id[run.get("id")] = run

        merged_runs: list[dict[str, Any]] = []
        for run in clean_runs:
            run_id = run.get("id")
            if run_id in enriched_by_id:
                merged_runs.append(enriched_by_id[run_id])
            else:
                merged_runs.append(run)

        return merged_runs

    except Exception:
        logger.exception(
            "Fallo enriqueciendo activity details. Se continúa con runs base para no romper /api/analysis."
        )
        return clean_runs


def build_analysis_payload(access_token: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
    user = user or {}

    base_runs = fetch_recent_runs(access_token)
    runs = _safe_enrich_runs_with_activity_details(access_token, base_runs)

    goal_time = user.get("goal_time") or "3:30"
    objective = user.get("objective") or "Maratón"
    race_date = user.get("race_date")

    quality_blocks = detect_quality_blocks(runs)
    training_tuple = compute_training(runs)
    training = _training_tuple_to_dict(training_tuple)
    fatigue = compute_fatigue_signal(runs)
    prediction = compute_prediction(
        training=training,
        fatigue=fatigue,
        quality_blocks=quality_blocks,
        goal_time=goal_time,
    )
    last_key_session = build_last_key_session(runs, quality_blocks)
    coach = build_coach(
        prediction=prediction,
        training=training,
        fatigue=fatigue,
        last_key_session=last_key_session,
        quality_blocks=quality_blocks,
    )

    status = _build_status_block(goal_time=goal_time, prediction=prediction)
    primary_insight, next_action, adjustment_hint = _derive_product_direction(
        prediction=prediction,
        training=training,
        fatigue=fatigue,
        quality_blocks=quality_blocks,
        last_key_session=last_key_session,
    )

    temp_analysis = {
        "training": training,
        "fatigue": fatigue,
        "coach": coach,
        "next_action": next_action,
        "primary_insight": primary_insight,
        "last_key_session": last_key_session,
    }
    plan_comparison = _build_plan_comparison(temp_analysis, user)

    return {
        "objective": objective,
        "goal_time": goal_time,
        "race_date": race_date,
        "prediction": prediction,
        "training": training,
        "fatigue": fatigue,
        "coach": coach,
        "quality_blocks": quality_blocks,
        "last_key_session": last_key_session,
        "status": status,
        "primary_insight": primary_insight,
        "next_action": next_action,
        "adjustment_hint": adjustment_hint,
        "plan_comparison": plan_comparison,
    }


def render_dashboard_html(_: dict[str, Any] | None = None) -> str:
    html_template = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>SecondCoach</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      padding: 0;
      background: #0b1020;
      color: #f4f7fb;
    }
    .wrap {
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-block;
      padding: 12px 16px;
      border-radius: 10px;
      background: #4f7cff;
      color: white;
      text-decoration: none;
      border: none;
      cursor: pointer;
      font-weight: 600;
    }
    .btn.secondary {
      background: #1d2640;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    .comparison-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }
    .card {
      background: #121a30;
      border: 1px solid #25304d;
      border-radius: 16px;
      padding: 18px;
    }
    .card.highlight {
      border-color: #4f7cff;
      box-shadow: 0 0 0 1px rgba(79, 124, 255, 0.18);
    }
    .label {
      font-size: 12px;
      text-transform: uppercase;
      opacity: 0.7;
      margin-bottom: 8px;
      letter-spacing: 0.04em;
    }
    .value {
      font-size: 28px;
      font-weight: 700;
      line-height: 1.1;
    }
    .muted {
      opacity: 0.8;
    }
    .section-title {
      font-size: 22px;
      margin: 30px 0 14px;
    }
    .subtext {
      color: #c8d2ea;
      line-height: 1.5;
    }
    .stack {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .diff-item {
      padding: 12px;
      border-radius: 12px;
      background: #0f1629;
      border: 1px solid #2a3553;
    }
    .diff-title {
      font-size: 13px;
      text-transform: uppercase;
      opacity: 0.7;
      margin-bottom: 6px;
    }
    .list-clean {
      margin: 0;
      padding-left: 18px;
      line-height: 1.6;
    }
    input, textarea {
      width: 100%;
      background: #0f1629;
      color: #f4f7fb;
      border: 1px solid #2a3553;
      border-radius: 10px;
      padding: 10px 12px;
      box-sizing: border-box;
    }
    textarea {
      min-height: 140px;
      resize: vertical;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f1629;
      border: 1px solid #2a3553;
      border-radius: 12px;
      padding: 14px;
      overflow: auto;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1 style="margin:0;">SecondCoach</h1>
        <div class="muted">MVP conectado a Strava</div>
      </div>
      <div style="display:flex; gap:12px; flex-wrap:wrap;">
        <a class="btn" href="/login">Login con Strava</a>
        <a class="btn secondary" href="/logout">Salir</a>
      </div>
    </div>

    <div class="grid">
      <div class="card highlight">
        <div class="label">Objetivo</div>
        <div class="value" id="goalValue">-</div>
      </div>
      <div class="card highlight">
        <div class="label">Predicción</div>
        <div class="value" id="predictionValue">-</div>
      </div>
      <div class="card highlight">
        <div class="label">Estado</div>
        <div class="value" id="statusValue" style="font-size:22px;">-</div>
      </div>
      <div class="card highlight">
        <div class="label">Siguiente acción</div>
        <div class="value" id="nextActionValue" style="font-size:22px;">-</div>
      </div>
    </div>

    <h2 class="section-title">Qué cambiar esta semana</h2>
    <div class="comparison-grid">
      <div class="card">
        <div class="label">Mi plan actual</div>
        <div id="currentPlanBlock" class="stack subtext">-</div>
      </div>

      <div class="card">
        <div class="label">Semana propuesta</div>
        <div id="proposedWeekBlock" class="stack subtext">-</div>
      </div>

      <div class="card">
        <div class="label">Diferencias clave</div>
        <div id="differencesBlock" class="stack subtext">-</div>
      </div>
    </div>

    <h2 class="section-title">Lectura de producto</h2>
    <div class="grid">
      <div class="card">
        <div class="label">Insight principal</div>
        <div id="primaryInsight" class="subtext">-</div>
      </div>
      <div class="card">
        <div class="label">Comparador simple</div>
        <div id="adjustmentHint" class="subtext">-</div>
      </div>
    </div>

    <h2 class="section-title">Fecha de carrera</h2>
    <div class="card">
      <input type="date" id="raceDateInput" />
      <div style="height:12px;"></div>
      <button class="btn" onclick="saveRaceDate()">Guardar race_date</button>
      <div id="raceDateResult" class="muted" style="margin-top:10px;"></div>
    </div>

    <h2 class="section-title">Validador inteligente</h2>
    <div class="card">
      <textarea id="planText" placeholder="Pega aquí tu semana o plan..."></textarea>
      <div style="height:12px;"></div>
      <button class="btn" onclick="validatePlanManual()">Validar plan</button>
      <pre id="validateOutput">-</pre>
    </div>
  </div>

  <script>
    let currentAnalysis = null;
    let lastValidation = null;

    function renderCurrentPlan(analysis) {
      const target = document.getElementById('currentPlanBlock');
      const comparison = analysis?.plan_comparison?.current || {};
      const lastSession = comparison?.last_session;

      let html = `
        <div><strong>Resumen:</strong> ${
          comparison.summary || analysis?.primary_insight || 'Sin resumen actual.'
        }</div>
        <div><strong>Foco actual:</strong> ${
          comparison.focus || analysis?.next_action?.focus || 'Sin foco actual.'
        }</div>
      `;

      if (lastSession && Object.keys(lastSession).length) {
        html += `
          <div><strong>Última sesión clave:</strong> ${
            lastSession.type || 'sesión clave'
          } · ${
            lastSession.date || '-'
          } · ${
            lastSession.distance_km || '-'
          } km</div>
        `;
      } else {
        html += `<div><strong>Última sesión clave:</strong> No detectada.</div>`;
      }

      target.innerHTML = html;
    }

    function renderProposedWeekFromAnalysis(analysis) {
      const target = document.getElementById('proposedWeekBlock');
      const proposed = analysis?.plan_comparison?.proposed || {};
      const lines = proposed?.lines || [];

      target.innerHTML = `
        <div><strong>Resumen:</strong> ${
          proposed.summary || 'Sin semana propuesta disponible.'
        }</div>
        <div>
          ${
            lines.length
              ? `<ul class="list-clean">${lines.map(line => `<li>${line}</li>`).join('')}</ul>`
              : 'Sin detalle de semana propuesta.'
          }
        </div>
      `;
    }

    function renderDifferencesFromAnalysis(analysis) {
      const target = document.getElementById('differencesBlock');
      const differences = analysis?.plan_comparison?.differences || [];

      if (!differences.length) {
        target.innerHTML = `<div>No se detectan diferencias clave todavía.</div>`;
        return;
      }

      target.innerHTML = differences.map(item => `
        <div class="diff-item">
          <div class="diff-title">${item.title || 'ajuste'} · prioridad ${item.priority || 'media'}</div>
          <div>${item.message || '-'}</div>
        </div>
      `).join('');
    }

    function renderManualValidation(validation) {
      if (!validation) return;

      const targetWeek = document.getElementById('proposedWeekBlock');
      const targetDiff = document.getElementById('differencesBlock');

      const proposedWeek = validation?.proposed_week || {};
      const order = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo'];
      let dayLines = '';

      for (const day of order) {
        if (proposedWeek[day]) {
          dayLines += `<li><strong>${day.charAt(0).toUpperCase() + day.slice(1)}:</strong> ${proposedWeek[day]}</li>`;
        }
      }

      const notes = proposedWeek?.notas || [];
      if (notes.length) {
        dayLines += notes.map(note => `<li><strong>Nota:</strong> ${note}</li>`).join('');
      }

      targetWeek.innerHTML = `
        <div><strong>Resumen:</strong> ${
          validation?.proposed_week_summary || 'Sin resumen de semana propuesta.'
        }</div>
        <div>
          ${
            dayLines
              ? `<ul class="list-clean">${dayLines}</ul>`
              : 'Sin detalle de semana propuesta.'
          }
        </div>
      `;

      const structured = validation?.recommended_adjustments_structured || [];
      const basic = validation?.recommended_adjustments || validation?.recommended_changes || [];

      if (structured.length) {
        targetDiff.innerHTML = structured.map(item => `
          <div class="diff-item">
            <div class="diff-title">${item.action_type || 'ajuste'} · prioridad ${item.priority || 'media'}</div>
            <div>${item.message || '-'}</div>
          </div>
        `).join('');
        return;
      }

      if (basic.length) {
        targetDiff.innerHTML = basic.map(message => `
          <div class="diff-item">
            <div class="diff-title">ajuste</div>
            <div>${message}</div>
          </div>
        `).join('');
        return;
      }

      targetDiff.innerHTML = `<div>No se detectan diferencias clave todavía.</div>`;
    }

    async function loadAnalysis() {
      const res = await fetch('/api/analysis');
      const data = await res.json();
      currentAnalysis = data;

      document.getElementById('goalValue').textContent =
        data?.status?.goal || data?.goal_time || '-';

      document.getElementById('predictionValue').textContent =
        data?.status?.prediction || data?.prediction?.predicted_time || '-';

      const statusText = data?.status
        ? `${data.status.status_label || '-'} (${
            data.status.delta_minutes === null || data.status.delta_minutes === undefined
              ? '-'
              : (data.status.delta_minutes > 0 ? '+' : '') + data.status.delta_minutes + ' min'
          })`
        : '-';
      document.getElementById('statusValue').textContent = statusText;

      document.getElementById('nextActionValue').textContent =
        data?.next_action?.focus || '-';

      document.getElementById('primaryInsight').textContent =
        data?.primary_insight || '-';

      const hint = data?.adjustment_hint;
      document.getElementById('adjustmentHint').innerHTML = hint
        ? `<strong>Problema actual:</strong> ${hint.current_issue}<br><br>
           <strong>Cambio propuesto:</strong> ${hint.proposed_change}<br><br>
           <strong>Efecto esperado:</strong> ${hint.expected_effect}`
        : '-';

      if (data?.race_date) {
        document.getElementById('raceDateInput').value = data.race_date;
      }

      renderCurrentPlan(data);
      renderProposedWeekFromAnalysis(data);
      renderDifferencesFromAnalysis(data);
    }

    async function validatePlanManual() {
      const planText = document.getElementById('planText').value;
      const res = await fetch('/api/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_text: planText })
      });
      const data = await res.json();
      lastValidation = data;

      document.getElementById('validateOutput').textContent = JSON.stringify(data, null, 2);
      renderManualValidation(data);
    }

    async function saveRaceDate() {
      const raceDate = document.getElementById('raceDateInput').value;
      const res = await fetch('/api/race-date', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ race_date: raceDate })
      });
      const data = await res.json();
      document.getElementById('raceDateResult').textContent = JSON.stringify(data);
      await loadAnalysis();
    }

    loadAnalysis().catch((err) => {
      document.body.insertAdjacentHTML(
        'beforeend',
        `<div style="padding:16px;color:#ffb4b4;">Error cargando análisis: ${String(err)}</div>`
      );
    });
  </script>
</body>
</html>
"""
    return html_template


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    athlete_id = request.session.get("athlete_id")
    if not athlete_id:
        return HTMLResponse(render_dashboard_html())

    user = get_user_by_athlete_id(athlete_id)
    if not user:
        return HTMLResponse(render_dashboard_html({"error": "user_not_found"}))

    try:
        access_token = refresh_access_token_if_needed(user)
        analysis_payload = build_analysis_payload(access_token, user=user)
        return HTMLResponse(render_dashboard_html(analysis_payload))
    except Exception as exc:
        logger.exception("Error renderizando dashboard principal")
        return HTMLResponse(render_dashboard_html({"error": str(exc)}))


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
    return build_analysis_payload(access_token, user=user)


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

    return validate_plan(
        plan_text=plan_text,
        objective=objective,
        training=analysis_payload.get("training") or {},
        fatigue=analysis_payload.get("fatigue") or {},
        race_date=race_date,
    )


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


@app.get("/health")
async def health():
    return {"ok": True}