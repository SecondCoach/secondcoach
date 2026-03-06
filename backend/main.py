from datetime import datetime, timedelta, timezone
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont
from starlette.middleware.sessions import SessionMiddleware

from backend.settings import settings

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.STRAVA_CLIENT_SECRET,
)

# --- Paths / DB ---
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "secondcoach.db"

# --- Strava OAuth / API config ---
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ATHLETE_URL = "https://www.strava.com/api/v3/athlete"

# --- Marathon context (current goal) ---
MARATHON_DATE = "2026-04-12"
MARATHON_TARGET = "3:30"  # hh:mm
PB_MARATHON = "3:34"      # hh:mm


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strava_athlete_id INTEGER NOT NULL UNIQUE,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                expires_at INTEGER,
                firstname TEXT,
                lastname TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def upsert_user_token(token_data: dict[str, Any], athlete_data: dict[str, Any]) -> int:
    athlete_id = athlete_data["id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO users (
                strava_athlete_id,
                access_token,
                refresh_token,
                expires_at,
                firstname,
                lastname,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strava_athlete_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at,
                firstname = excluded.firstname,
                lastname = excluded.lastname,
                updated_at = excluded.updated_at
            """,
            (
                athlete_id,
                token_data.get("access_token"),
                token_data.get("refresh_token"),
                token_data.get("expires_at"),
                athlete_data.get("firstname"),
                athlete_data.get("lastname"),
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
        return athlete_id
    finally:
        conn.close()


def update_user_tokens(
    athlete_id: int,
    access_token: str,
    refresh_token: str | None,
    expires_at: int | None,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE users
            SET access_token = ?,
                refresh_token = ?,
                expires_at = ?,
                updated_at = ?
            WHERE strava_athlete_id = ?
            """,
            (access_token, refresh_token, expires_at, now_iso, athlete_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_athlete_id(athlete_id: int) -> sqlite3.Row | None:
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE strava_athlete_id = ?
            """,
            (athlete_id,),
        ).fetchone()
        return row
    finally:
        conn.close()


def get_current_user(request: Request) -> sqlite3.Row | None:
    athlete_id = request.session.get("athlete_id")
    if athlete_id is None:
        return None
    return get_user_by_athlete_id(int(athlete_id))


def refresh_access_token_if_needed(user: sqlite3.Row) -> sqlite3.Row:
    athlete_id = user["strava_athlete_id"]
    refresh_token = user["refresh_token"]
    expires_at = user["expires_at"]

    now_ts = int(datetime.now(timezone.utc).timestamp())
    should_refresh = (
        refresh_token
        and expires_at is not None
        and int(expires_at) <= now_ts + 300
    )

    if not should_refresh:
        return user

    token_response = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    token_response.raise_for_status()
    token_data = token_response.json()

    new_access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token", refresh_token)
    new_expires_at = token_data.get("expires_at", expires_at)

    if not new_access_token:
        raise requests.HTTPError("Strava no devolvió access_token al refrescar el token.")

    update_user_tokens(
        athlete_id=athlete_id,
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_at=new_expires_at,
    )

    refreshed_user = get_user_by_athlete_id(athlete_id)
    if refreshed_user is None:
        raise RuntimeError("No se pudo recargar el usuario tras refrescar token.")

    return refreshed_user


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        """
        <html>
        <head>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>SecondCoach</title>
          <style>
            body {
              font-family: -apple-system, BlinkMacSystemFont, sans-serif;
              margin: 0;
              background: #f7f7f7;
              color: #111;
            }
            .wrap {
              max-width: 720px;
              margin: 0 auto;
              padding: 32px 20px 48px 20px;
            }
            .hero {
              background: white;
              border: 1px solid #eee;
              border-radius: 18px;
              padding: 28px;
              box-shadow: 0 2px 10px rgba(0,0,0,0.04);
            }
            h1 {
              font-size: 42px;
              line-height: 1.05;
              margin: 0 0 14px 0;
            }
            .sub {
              font-size: 22px;
              line-height: 1.3;
              margin: 0 0 18px 0;
            }
            .muted {
              color: #666;
              font-size: 18px;
              line-height: 1.5;
            }
            .cta {
              display: inline-block;
              margin-top: 22px;
              padding: 14px 18px;
              border-radius: 14px;
              background: #fc4c02;
              color: white;
              text-decoration: none;
              font-weight: 700;
            }
            .card {
              background: white;
              border: 1px solid #eee;
              border-radius: 18px;
              padding: 22px 24px;
              margin-top: 18px;
              box-shadow: 0 2px 10px rgba(0,0,0,0.04);
            }
            ul {
              margin: 12px 0 0 0;
              padding-left: 20px;
              line-height: 1.8;
            }
            .tiny {
              margin-top: 16px;
              color: #777;
              font-size: 14px;
            }
          </style>
        </head>
        <body>
          <div class="wrap">
            <div class="hero">
              <h1>SecondCoach</h1>
              <p class="sub">¿Tu entrenamiento realmente te lleva a tu objetivo?</p>
              <p class="muted">
                Conecta tu Strava y descubre en segundos tu estado de carga,
                tu predicción de maratón y si tu objetivo es realista.
              </p>
              <a class="cta" href="/login">Conectar con Strava</a>
              <div class="tiny">Sin formularios. Sin configurar nada. Entra y mira tu análisis.</div>
            </div>

            <div class="card">
              <b>Qué te damos</b>
              <ul>
                <li>Estado de carga simple: verde, amarillo o rojo</li>
                <li>Volumen 7/14/28 días</li>
                <li>Tirada larga reciente</li>
                <li>Predicción maratón explicada</li>
              </ul>
            </div>
          </div>
        </body>
        </html>
        """
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "secondcoach",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/login")
def login():
    url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={settings.STRAVA_CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={settings.STRAVA_REDIRECT_URI}"
        "&scope=activity:read_all"
    )
    return RedirectResponse(url)


@app.get("/callback")
def callback(request: Request, code: str):
    token_response = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    token_response.raise_for_status()
    token_data = token_response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return JSONResponse(
            {"error": "Strava no devolvió access_token."},
            status_code=502,
        )

    athlete_response = requests.get(
        ATHLETE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    athlete_response.raise_for_status()
    athlete_data = athlete_response.json()

    athlete_id = upsert_user_token(token_data, athlete_data)
    request.session["athlete_id"] = athlete_id

    return RedirectResponse("/dashboard")


def _parse_strava_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt(mins: int) -> str:
    h = mins // 60
    m = mins % 60
    return f"{h}:{m:02d}"


def _unauthorized():
    return JSONResponse(
        {"error": "No user session. Ve a /login para autorizar Strava."},
        status_code=401,
    )


def _get_activities(request: Request) -> list[dict[str, Any]] | JSONResponse:
    user = get_current_user(request)
    if not user:
        return _unauthorized()

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
        data = response.json()

        if not isinstance(data, list):
            return JSONResponse(
                {"error": "Respuesta inesperada de Strava al pedir actividades."},
                status_code=502,
            )

        return data

    except requests.RequestException as exc:
        return JSONResponse(
            {"error": f"Error al consultar Strava: {str(exc)}"},
            status_code=502,
        )
    except RuntimeError as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=500,
        )


@app.get("/analysis")
def analysis(request: Request):
    acts = _get_activities(request)
    if isinstance(acts, JSONResponse):
        return acts

    now = datetime.now(timezone.utc)

    def in_last_days(activity: dict[str, Any], days: int) -> bool:
        dt = _parse_strava_dt(activity.get("start_date", "1970-01-01T00:00:00Z"))
        return dt >= (now - timedelta(days=days))

    def is_run(activity: dict[str, Any]) -> bool:
        return activity.get("type") == "Run"

    def summarize(days: int):
        items = [a for a in acts if is_run(a) and in_last_days(a, days)]
        total_time = sum(a.get("moving_time", 0) or 0 for a in items)
        total_dist = sum(a.get("distance", 0) or 0 for a in items)
        sessions = len(items)
        return (
            {
                "days": days,
                "sessions": sessions,
                "time_h": round(total_time / 3600, 2),
                "distance_km": round(total_dist / 1000, 2),
            },
            items,
        )

    s7, _runs7 = summarize(7)
    s14, _runs14 = summarize(14)
    s28, runs28 = summarize(28)

    long_run_km = 0.0
    long_run_date = None
    if runs28:
        best = max(runs28, key=lambda a: a.get("distance", 0) or 0)
        long_run_km = round((best.get("distance", 0) or 0) / 1000, 2)
        long_run_date = best.get("start_date")

    weekly_avg_km = (s28["distance_km"] / 4.0) if s28["distance_km"] else 0.0
    km7 = s7["distance_km"]

    if weekly_avg_km == 0:
        semaforo = "⚪ Insuficiente"
        ajuste = "No hay suficiente running en 28 días para evaluar preparación maratón."
    else:
        ratio = km7 / weekly_avg_km
        if ratio <= 1.10:
            semaforo = "🟢 Verde"
            ajuste = "Carga de running alineada con tu media. Mantén estructura y calidad."
        elif ratio <= 1.25:
            semaforo = "🟡 Amarillo"
            ajuste = "Carga algo por encima de tu media. Vigila recuperación y sueño."
        else:
            semaforo = "🔴 Rojo"
            ajuste = "Pico de carga vs tu media. Considera semana de descarga o recorte del 15–30%."

    prediction = {"estimate": "3:33", "range": "3:30–3:37"}

    return JSONResponse(
        {
            "sport": "Run",
            "window_7d": s7,
            "window_14d": s14,
            "window_28d": s28,
            "long_run_28d_km": long_run_km,
            "long_run_28d_date": long_run_date,
            "weekly_avg_km_from_28d": round(weekly_avg_km, 2),
            "semaforo": semaforo,
            "ajuste": ajuste,
            "prediction": prediction,
            "note": "Esto evalúa SOLO running. Bici/natación no están sumadas aquí a propósito para objetivo maratón.",
        }
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    response = analysis(request)
    data = json.loads(response.body.decode("utf-8"))

    if "error" in data:
        return HTMLResponse(
            """
            <html>
              <body style="font-family:-apple-system, BlinkMacSystemFont, sans-serif;padding:40px">
                <h2>SecondCoach</h2>
                <p>No estás conectado a Strava.</p>
                <a href="/login">Conectar con Strava</a>
              </body>
            </html>
            """
        )

    km7 = data["window_7d"]["distance_km"]
    km14 = data["window_14d"]["distance_km"]
    km28 = data["window_28d"]["distance_km"]
    avg_week = data["weekly_avg_km_from_28d"]
    long_km = data["long_run_28d_km"]
    sem = data["semaforo"]
    ajuste = data["ajuste"]

    pb_min = _to_minutes(PB_MARATHON)
    target_min = _to_minutes(MARATHON_TARGET)

    vol_bonus = min(max(avg_week - 45, 0), 20) * 0.25
    lr_bonus = min(max(long_km - 24, 0), 6) * 0.5
    freq_penalty = 2 if data["window_7d"]["sessions"] <= 3 else 0

    pred_min = pb_min - vol_bonus - lr_bonus + freq_penalty
    low = int(round(pred_min - 3))
    high = int(round(pred_min + 4))
    pred_range = f"{_fmt(low)}–{_fmt(high)}"
    pred_point = _fmt(int(round(pred_min)))
    pred_status = (
        "✔ Objetivo 3:30 en rango"
        if pred_min <= target_min
        else "⚠ Objetivo 3:30 exigente (aún)"
    )

    html = f"""
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>SecondCoach</title>
      <style>
        body {{ font-family:-apple-system, BlinkMacSystemFont, sans-serif; padding: 18px; max-width: 720px; margin: 0 auto; }}
        .card {{ border: 1px solid #eee; border-radius: 14px; padding: 16px; margin: 12px 0; box-shadow: 0 2px 10px rgba(0,0,0,0.04); }}
        .muted {{ color: #666; }}
        .big {{ font-size: 20px; }}
        .row {{ display:flex; gap: 10px; flex-wrap: wrap; }}
        .pill {{ display:inline-block; padding: 6px 10px; border-radius: 999px; background: #f5f5f5; }}
        a.btn {{ display:inline-block; padding: 10px 12px; border-radius: 12px; border: 1px solid #ddd; text-decoration:none; color:#111; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div style="font-size:26px;margin:0 0 6px 0;"><b>SecondCoach</b></div>
        <div class="muted">Modo maratón · Objetivo {MARATHON_DATE} · {MARATHON_TARGET} (ritmo ~4:58/km)</div>
        <div class="muted">PB maratón: {PB_MARATHON}</div>
      </div>

      <div class="card">
        <div class="big"><b>Estado de carga (running)</b></div>
        <div style="margin-top:8px" class="pill">{sem}</div>
        <div style="margin-top:10px">{ajuste}</div>
      </div>

      <div class="card">
        <div class="big"><b>Volumen</b></div>
        <div class="row" style="margin-top:10px">
          <div class="pill">7d: {km7:.1f} km</div>
          <div class="pill">14d: {km14:.1f} km</div>
          <div class="pill">28d: {km28:.1f} km</div>
          <div class="pill">Media: {avg_week:.1f} km/sem</div>
        </div>
      </div>

      <div class="card">
        <div class="big"><b>Tirada larga</b></div>
        <div style="margin-top:10px" class="pill">{long_km:.1f} km (últimos 28 días)</div>
      </div>

      <div class="card">
        <div class="big"><b>Predicción maratón {MARATHON_DATE}</b></div>
        <div class="row" style="margin-top:10px">
          <div class="pill">Estimación: {pred_point}</div>
          <div class="pill">Rango: {pred_range}</div>
        </div>
        <div style="margin-top:10px"><b>{pred_status}</b></div>
        <div class="muted" style="margin-top:6px">
          Heurística MVP: PB {PB_MARATHON} ajustado por volumen ({avg_week:.1f} km/sem) y tirada larga ({long_km:.1f} km).
        </div>
      </div>

      <div class="card">
        <a class="btn" href="/analysis">Ver JSON</a>
        <a class="btn" href="/login">Reautorizar Strava</a>
      </div>

      <div class="muted" style="margin-top:14px">
        Nota: esta pantalla evalúa SOLO running. Bici/natación no se suman aquí a propósito para objetivo maratón.
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/marathon_pace")
def marathon_pace(request: Request):
    acts = _get_activities(request)
    if isinstance(acts, JSONResponse):
        return acts

    now = datetime.now(timezone.utc)

    def in_last_days(activity: dict[str, Any], days: int) -> bool:
        dt = _parse_strava_dt(activity.get("start_date", "1970-01-01T00:00:00Z"))
        return dt >= (now - timedelta(days=days))

    pace_low_s = 4 * 60 + 45
    pace_high_s = 5 * 60 + 5

    speed_high = 1000 / pace_low_s
    speed_low = 1000 / pace_high_s

    km_in_zone = 0.0
    sessions_in_zone = 0
    longest_in_zone_km = 0.0
    longest_in_zone_date = None
    considered = 0

    for activity in acts:
        if activity.get("type") != "Run":
            continue
        if not in_last_days(activity, 28):
            continue

        dist_km = (activity.get("distance", 0) or 0) / 1000
        avg_speed = activity.get("average_speed")

        if dist_km < 5 or not avg_speed:
            continue

        considered += 1

        if speed_low <= avg_speed <= speed_high:
            km_in_zone += dist_km
            sessions_in_zone += 1
            if dist_km > longest_in_zone_km:
                longest_in_zone_km = dist_km
                longest_in_zone_date = activity.get("start_date")

    return JSONResponse(
        {
            "window_days": 28,
            "zone_pace_min_km": "4:45–5:05",
            "runs_considered": considered,
            "sessions_in_zone": sessions_in_zone,
            "km_in_zone": round(km_in_zone, 2),
            "longest_run_in_zone_km": round(longest_in_zone_km, 2),
            "longest_run_in_zone_date": longest_in_zone_date,
            "note": "Heurística MVP: usa el ritmo medio del entrenamiento (average_speed). No detecta segmentos internos.",
        }
    )


@app.get("/share")
def share(request: Request):
    resp = analysis(request)
    data = json.loads(resp.body.decode("utf-8"))

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
        <style>
            body {{ font-family: Arial; padding:40px; background:#f5f5f5 }}
            .card {{ background:white; padding:30px; border-radius:10px; max-width:520px }}
            h1 {{ margin-top: 0 }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>SecondCoach</h1>
            <p><b>Predicción maratón:</b> {data.get('prediction', {}).get('estimate', 'calculando...')}</p>
            <p><b>Rango:</b> {data.get('prediction', {}).get('range', 'calculando...')}</p>
            <p><b>Media semanal:</b> {data.get('weekly_avg_km_from_28d', 'calculando...')} km/sem</p>
            <p><b>Tirada larga:</b> {data.get('long_run_28d_km', 'calculando...')} km</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/share.png")
def share_png(request: Request):
    resp = analysis(request)
    data = json.loads(resp.body.decode("utf-8"))

    pred_est = data.get("prediction", {}).get("estimate", "--")
    pred_rng = data.get("prediction", {}).get("range", "--")
    weekly = data.get("weekly_avg_km_from_28d", "--")
    longrun = data.get("long_run_28d_km", "--")

    img = Image.new("RGB", (800, 450), "white")
    draw = ImageDraw.Draw(img)

    font_title = ImageFont.load_default()
    font_text = ImageFont.load_default()

    draw.text((40, 40), "SecondCoach", fill="black", font=font_title)
    draw.text((40, 140), f"Predicción maratón: {pred_est}", fill="black", font=font_text)
    draw.text((40, 200), f"Rango: {pred_rng}", fill="black", font=font_text)
    draw.text((40, 260), f"Media semanal: {weekly} km", fill="black", font=font_text)
    draw.text((40, 320), f"Tirada larga: {longrun} km", fill="black", font=font_text)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")

    return Response(buffer.getvalue(), media_type="image/png")


@app.get("/me")
def me(request: Request):
    user = get_current_user(request)

    if not user:
        return {"logged": False}

    return {
        "logged": True,
        "athlete_id": user["strava_athlete_id"],
        "firstname": user["firstname"],
        "lastname": user["lastname"],
        "token_expires_at": user["expires_at"],
    }


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port)

@app.get("/p/{athlete_id}", response_class=HTMLResponse)
def public_profile(athlete_id: int):
    user = get_user_by_athlete_id(athlete_id)

    if not user:
        return HTMLResponse("<h1>Runner no encontrado</h1>")

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
            return HTMLResponse("<h1>No se pudo cargar el análisis</h1>")

    except Exception:
        return HTMLResponse("<h1>No se pudo cargar el análisis</h1>")

    now = datetime.now(timezone.utc)

    def in_last_days(activity: dict[str, Any], days: int) -> bool:
        dt = _parse_strava_dt(activity.get("start_date", "1970-01-01T00:00:00Z"))
        return dt >= (now - timedelta(days=days))

    def is_run(activity: dict[str, Any]) -> bool:
        return activity.get("type") == "Run"

    def summarize(days: int):
        items = [a for a in acts if is_run(a) and in_last_days(a, days)]
        total_time = sum(a.get("moving_time", 0) or 0 for a in items)
        total_dist = sum(a.get("distance", 0) or 0 for a in items)
        sessions = len(items)
        return {
            "days": days,
            "sessions": sessions,
            "time_h": round(total_time / 3600, 2),
            "distance_km": round(total_dist / 1000, 2),
        }, items

    s7, _runs7 = summarize(7)
    s28, runs28 = summarize(28)

    long_run_km = 0.0
    if runs28:
        best = max(runs28, key=lambda a: a.get("distance", 0) or 0)
        long_run_km = round((best.get("distance", 0) or 0) / 1000, 2)

    weekly_avg_km = round((s28["distance_km"] / 4.0), 2) if s28["distance_km"] else 0.0
    km7 = s7["distance_km"]

    if weekly_avg_km == 0:
        semaforo = "⚪ Insuficiente"
    else:
        ratio = km7 / weekly_avg_km
        if ratio <= 1.10:
            semaforo = "🟢 Verde"
        elif ratio <= 1.25:
            semaforo = "🟡 Amarillo"
        else:
            semaforo = "🔴 Rojo"

    pb_min = _to_minutes(PB_MARATHON)
    target_min = _to_minutes(MARATHON_TARGET)

    vol_bonus = min(max(weekly_avg_km - 45, 0), 20) * 0.25
    lr_bonus = min(max(long_run_km - 24, 0), 6) * 0.5
    freq_penalty = 2 if s7["sessions"] <= 3 else 0

    pred_min = pb_min - vol_bonus - lr_bonus + freq_penalty
    low = int(round(pred_min - 3))
    high = int(round(pred_min + 4))
    pred_point = _fmt(int(round(pred_min)))
    pred_range = f"{_fmt(low)}–{_fmt(high)}"

    html = f"""
    <html>
    <head>
        <title>SecondCoach</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family:-apple-system,BlinkMacSystemFont,sans-serif;
                padding:30px;
                background:#f5f5f5;
                color:#111;
            }}
            .card {{
                background:white;
                padding:30px;
                border-radius:16px;
                max-width:560px;
                margin:auto;
                box-shadow: 0 2px 10px rgba(0,0,0,0.04);
                border: 1px solid #eee;
            }}
            h1 {{
                margin-top:0;
                font-size: 40px;
            }}
            .pill {{
                display:inline-block;
                padding:8px 12px;
                background:#eee;
                border-radius:999px;
                margin:5px 5px 0 0;
            }}
            .muted {{
                color:#666;
            }}
            .cta {{
                display:inline-block;
                margin-top:20px;
                padding:12px 16px;
                border-radius:12px;
                background:#fc4c02;
                color:white;
                text-decoration:none;
                font-weight:700;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>SecondCoach</h1>

            <p><b>Runner:</b> {user["firstname"]} {user["lastname"]}</p>

            <p><b>Predicción maratón:</b> {pred_point}</p>
            <p><b>Rango:</b> {pred_range}</p>

            <div class="pill">Media semanal: {weekly_avg_km} km</div>
            <div class="pill">Tirada larga: {long_run_km} km</div>
            <div class="pill">Estado: {semaforo}</div>

            <p class="muted" style="margin-top:20px;">
                Análisis generado a partir de actividad reciente en Strava.
            </p>

            <a class="cta" href="/">Analiza tu entrenamiento</a>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html)