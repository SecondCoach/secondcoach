from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
import requests
from datetime import datetime, timezone, timedelta
from backend.settings import settings as settings

app = FastAPI()

# --- Strava OAuth config ---
CLIENT_ID = settings.STRAVA_CLIENT_ID
CLIENT_SECRET = settings.STRAVA_CLIENT_SECRET
REDIRECT_URI = settings.STRAVA_REDIRECT_URI

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

# NOTE: MVP stores token in-memory. Restart/reload => re-login needed.
access_token = None

# --- Marathon context (your current goal) ---
MARATHON_DATE = "2026-04-12"
MARATHON_TARGET = "3:30"   # hh:mm
PB_MARATHON = "3:34"       # hh:mm


@app.get("/")
def home():
    return {"status": "SecondCoach backend running"}


@app.get("/login")
def login():
    url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=activity:read_all"
    )
    return RedirectResponse(url)


@app.get("/callback")
def callback(code: str):
    global access_token
    r = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    data = r.json()
    access_token = data.get("access_token")
    return RedirectResponse("/dashboard")


def _parse_strava_dt(s: str) -> datetime:
    # Strava suele dar: "2026-03-05T12:34:56Z"
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


@app.get("/analysis")
def analysis():
    if not access_token:
        return JSONResponse(
            {"error": "No access_token. Ve a /login para autorizar Strava."},
            status_code=401,
        )

    headers = {"Authorization": f"Bearer {access_token}"}

    acts = requests.get(
        ACTIVITIES_URL, headers=headers, params={"per_page": 200}, timeout=30
    ).json()

    now = datetime.now(timezone.utc)

    def in_last_days(a, days: int) -> bool:
        dt = _parse_strava_dt(a.get("start_date", "1970-01-01T00:00:00Z"))
        return dt >= (now - timedelta(days=days))

    def is_run(a) -> bool:
        return a.get("type") == "Run"

    def summarize(days: int):
        items = [a for a in acts if is_run(a) and in_last_days(a, days)]
        total_time = sum(a.get("moving_time", 0) for a in items)  # segundos
        total_dist = sum(a.get("distance", 0) for a in items)     # metros
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

    s7, runs7 = summarize(7)
    s14, runs14 = summarize(14)
    s28, runs28 = summarize(28)

    long_run_km = 0.0
    long_run_date = None
    if runs28:
        best = max(runs28, key=lambda a: a.get("distance", 0))
        long_run_km = round(best.get("distance", 0) / 1000, 2)
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


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt(mins: int) -> str:
    h = mins // 60
    m = mins % 60
    return f"{h}:{m:02d}"


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    import json as _json

    res = analysis()
    if hasattr(res, "body"):
        data = _json.loads(res.body.decode("utf-8"))
    else:
        data = res

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

    pred_status = "✔ Objetivo 3:30 en rango" if pred_min <= target_min else "⚠ Objetivo 3:30 exigente (aún)"

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
def marathon_pace():
    """
    Detecta km a ritmo maratón objetivo (3:30 ~ 4:58/km) en los últimos 28 días.
    Heurística MVP: usa average_speed (m/s) de Strava por actividad (no streams).
    """
    if not access_token:
        return JSONResponse(
            {"error": "No access_token. Ve a /login para autorizar Strava."},
            status_code=401,
        )

    headers = {"Authorization": f"Bearer {access_token}"}
    acts = requests.get(
        ACTIVITIES_URL, headers=headers, params={"per_page": 200}, timeout=30
    ).json()

    now = datetime.now(timezone.utc)

    def in_last_days(a, days: int) -> bool:
        dt = _parse_strava_dt(a.get("start_date", "1970-01-01T00:00:00Z"))
        return dt >= (now - timedelta(days=days))

    # Zona “ritmo maratón” para 3:30 (ajustable)
    # 4:45–5:05 /km
    pace_low_s = 4 * 60 + 45   # más rápido
    pace_high_s = 5 * 60 + 5   # más lento

    # Convertimos pace (s/km) a speed (m/s): speed = 1000 / pace_s
    speed_high = 1000 / pace_low_s   # límite superior de velocidad (más rápido)
    speed_low = 1000 / pace_high_s   # límite inferior de velocidad (más lento)

    km_in_zone = 0.0
    sessions_in_zone = 0
    longest_in_zone_km = 0.0
    longest_in_zone_date = None

    considered = 0

    for a in acts:
        if a.get("type") != "Run":
            continue
        if not in_last_days(a, 28):
            continue

        dist_km = (a.get("distance", 0) or 0) / 1000
        avg_speed = a.get("average_speed", None)  # m/s

        # filtros anti-ruido
        if dist_km < 5 or not avg_speed:
            continue

        considered += 1

        if speed_low <= avg_speed <= speed_high:
            km_in_zone += dist_km
            sessions_in_zone += 1
            if dist_km > longest_in_zone_km:
                longest_in_zone_km = dist_km
                longest_in_zone_date = a.get("start_date")

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
def share():
    import json

    # 1) Obtener el JSON real que devuelve /analysis
    resp = analysis().body
    raw = resp
    # 2) Convertir raw -> dict de forma robusta
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")

    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}

    # 3) Pintar HTML
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

from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont
import io

@app.get("/share.png")
def share_png():

    import json

    # Obtener datos de /analysis
    resp = analysis()
    data = json.loads(resp.body)

    pred_est = data.get("prediction", {}).get("estimate", "--")
    pred_rng = data.get("prediction", {}).get("range", "--")
    weekly   = data.get("weekly_avg_km_from_28d", "--")
    longrun  = data.get("long_run_28d_km", "--")

    # Crear imagen
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