from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.db import get_user_by_athlete_id

router = APIRouter()


@router.get("/p/{athlete_id}", response_class=HTMLResponse)
def public_prediction_page(athlete_id: int):
    user = get_user_by_athlete_id(athlete_id)

    if not user:
        return HTMLResponse("<h1>Runner no encontrado</h1>", status_code=404)

    base_url = "https://secondcoach.onrender.com"

    # URLs absolutas para redes sociales
    og_image_url = f"{base_url}/share/{athlete_id}.png"
    og_page_url = f"{base_url}/p/{athlete_id}"

    # URLs relativas para que funcione también en local
    image_url = f"/share/{athlete_id}.png"
    login_url = "/login"
    logo_url = "/static/secondcoach_logo.png"

    firstname = (user.get("firstname") or "").strip()
    username = (user.get("username") or "").strip()

    runner_name = firstname or username or "Este runner"

    headline = f"{runner_name.capitalize()} ya tiene una predicción de carrera con SecondCoach"
    subheadline = (
        "SecondCoach analiza entrenamientos de Strava y transforma datos complejos "
        "en una lectura clara: predicción actual, margen frente al objetivo y señales reales de preparación."
    )

    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SecondCoach</title>

    <meta property="og:title" content="¿Estoy listo para mi objetivo?">
    <meta property="og:description" content="SecondCoach analiza entrenamientos de Strava y estima si vas en línea con tu objetivo.">
    <meta property="og:image" content="{og_image_url}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{og_page_url}">

    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="¿Estoy listo para mi objetivo?">
    <meta name="twitter:description" content="SecondCoach analiza entrenamientos de Strava y estima si vas en línea con tu objetivo.">
    <meta name="twitter:image" content="{og_image_url}">

    <style>
        :root {{
            --bg: #08111f;
            --panel: #0f1b2d;
            --panel-2: #132238;
            --text: #eef2f7;
            --muted: #9aa4b2;
            --accent: #ff5a1f;
            --accent-2: #ff7a1f;
            --border: rgba(255,255,255,0.08);
            --shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            background:
                radial-gradient(circle at top left, rgba(255,90,31,0.10), transparent 28%),
                radial-gradient(circle at bottom right, rgba(34,197,94,0.08), transparent 24%),
                var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 28px 20px 48px;
        }}

        .wrap {{
            max-width: 760px;
            margin: 0 auto;
        }}

        .hero {{
            text-align: center;
            margin-bottom: 20px;
        }}

        .logo {{
            width: 94px;
            height: auto;
            display: block;
            margin: 0 auto 18px;
        }}

        .eyebrow {{
            color: var(--muted);
            font-size: 15px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }}

        h1 {{
            font-size: 42px;
            line-height: 1.08;
            margin: 0 0 14px;
        }}

        .sub {{
            max-width: 640px;
            margin: 0 auto;
            font-size: 19px;
            line-height: 1.55;
            color: var(--muted);
        }}

        .proof {{
            margin: 18px auto 0;
            display: inline-block;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 999px;
            padding: 10px 16px;
            color: var(--text);
            font-size: 15px;
        }}

        .card {{
            background: linear-gradient(180deg, var(--panel), var(--panel-2));
            border: 1px solid var(--border);
            border-radius: 24px;
            box-shadow: var(--shadow);
            padding: 22px;
            overflow: hidden;
        }}

        .image-wrap {{
            border-radius: 18px;
            overflow: hidden;
            background: #050b15;
            border: 1px solid rgba(255,255,255,0.05);
        }}

        img.preview {{
            display: block;
            width: 100%;
            height: auto;
        }}

        .copy {{
            padding: 22px 6px 6px;
            text-align: center;
        }}

        .copy h2 {{
            font-size: 28px;
            margin: 0 0 10px;
        }}

        .copy p {{
            margin: 0 auto;
            max-width: 560px;
            font-size: 18px;
            line-height: 1.55;
            color: var(--muted);
        }}

        .bullets {{
            display: grid;
            gap: 12px;
            margin: 24px 0 0;
            text-align: left;
        }}

        .bullet {{
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 14px;
            padding: 14px 16px;
            color: var(--text);
            font-size: 17px;
            line-height: 1.45;
        }}

        .cta-wrap {{
            text-align: center;
            margin-top: 28px;
        }}

        .cta {{
            display: inline-block;
            background: linear-gradient(90deg, var(--accent), var(--accent-2));
            color: white;
            padding: 16px 26px;
            border-radius: 14px;
            font-size: 18px;
            font-weight: 700;
            text-decoration: none;
            box-shadow: 0 10px 24px rgba(255, 90, 31, 0.28);
        }}

        .foot {{
            text-align: center;
            margin-top: 16px;
            color: var(--muted);
            font-size: 14px;
        }}

        @media (max-width: 640px) {{
            body {{
                padding: 20px 14px 34px;
            }}

            .logo {{
                width: 82px;
            }}

            h1 {{
                font-size: 32px;
            }}

            .sub {{
                font-size: 17px;
            }}

            .card {{
                padding: 14px;
                border-radius: 18px;
            }}

            .copy h2 {{
                font-size: 24px;
            }}

            .copy p,
            .bullet {{
                font-size: 16px;
            }}

            .cta {{
                width: 100%;
                padding: 16px 18px;
            }}
        }}
    </style>
</head>
<body>
    <div class="wrap">
        <div class="hero">
            <img src="{logo_url}" alt="SecondCoach" class="logo">
            <div class="eyebrow">SecondCoach</div>
            <h1>{headline}</h1>
            <p class="sub">{subheadline}</p>
            <div class="proof">Basado en su actividad reciente de Strava</div>
        </div>

        <div class="card">
            <div class="image-wrap">
                <img src="{image_url}" alt="Predicción de carrera generada por SecondCoach" class="preview">
            </div>

            <div class="copy">
                <h2>Tu entrenamiento, explicado como lo haría un entrenador</h2>
                <p>
                    No solo muestra un tiempo estimado. Te dice si vas por delante, si estás en línea
                    o si tu objetivo empieza a estar en riesgo.
                </p>

                <div class="bullets">
                    <div class="bullet">Dato → interpretación → decisión.</div>
                    <div class="bullet">Volumen, tirada larga y trabajo a ritmo objetivo.</div>
                    <div class="bullet">Una predicción fácil de entender y compartir.</div>
                </div>

                <div class="cta-wrap">
                    <a class="cta" href="{login_url}">Conectar Strava y analizar mi entrenamiento</a>
                </div>

                <div class="foot">SecondCoach · análisis de entrenamiento explicable</div>
            </div>
        </div>
    </div>
</body>
</html>
"""

    return HTMLResponse(html)