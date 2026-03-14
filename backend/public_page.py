from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def render_public_page(athlete_id: int, base_url: str) -> HTMLResponse:
    base_url = base_url.rstrip("/")
    page_url = f"{base_url}/p/{athlete_id}"
    share_image = f"{base_url}/share/{athlete_id}.png"
    logo_url = f"{base_url}/static/secondcoach_logo.png"
    login_url = f"{base_url}/login"

    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>Predicción de carrera con SecondCoach</title>

<meta name="description" content="SecondCoach analiza entrenamientos de Strava y transforma datos complejos en una lectura clara: predicción actual, margen frente al objetivo y señales reales de preparación.">

<meta property="og:title" content="Predicción de carrera con SecondCoach">
<meta property="og:description" content="SecondCoach analiza entrenamientos de Strava y transforma datos complejos en una lectura clara: predicción actual, margen frente al objetivo y señales reales de preparación.">
<meta property="og:type" content="article">
<meta property="og:url" content="{page_url}">
<meta property="og:site_name" content="SecondCoach">
<meta property="og:image" content="{share_image}">
<meta property="og:image:secure_url" content="{share_image}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Predicción de carrera generada por SecondCoach">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Predicción de carrera con SecondCoach">
<meta name="twitter:description" content="SecondCoach transforma datos de Strava en una lectura clara y compartible.">
<meta name="twitter:image" content="{share_image}">

<link rel="icon" href="{logo_url}">

<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background:
        radial-gradient(circle at top left, rgba(255,106,61,0.14), transparent 28%),
        radial-gradient(circle at top right, rgba(16,58,140,0.22), transparent 30%),
        linear-gradient(180deg, #071122 0%, #04101f 100%);
    margin: 0;
    padding: 0;
    text-align: center;
    color: #f5f7fb;
}}

.page {{
    width: 100%;
}}

.hero {{
    padding: 60px 20px 36px 20px;
    max-width: 1100px;
    margin: auto;
}}

.logo {{
    width: 88px;
    margin-bottom: 18px;
}}

.brand {{
    color: #a9b4c8;
    font-size: 18px;
    letter-spacing: 0.12em;
    margin-bottom: 10px;
}}

h1 {{
    font-size: 68px;
    line-height: 1.05;
    letter-spacing: -0.03em;
    margin: 0 auto 20px auto;
    max-width: 980px;
    font-weight: 800;
}}

.sub {{
    max-width: 900px;
    margin: auto;
    font-size: 26px;
    line-height: 1.45;
    color: #b8c2d6;
}}

.badge {{
    display: inline-block;
    margin-top: 28px;
    padding: 14px 26px;
    border-radius: 999px;
    font-size: 18px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.08);
}}

.section {{
    padding: 10px 20px 40px 20px;
}}

.prediction-shell {{
    max-width: 1120px;
    margin: auto;
    background: rgba(11,25,49,0.88);
    border: 1px solid rgba(139,171,255,0.16);
    border-radius: 36px;
    padding: 30px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.28);
}}

.card {{
    max-width: 980px;
    margin: 0 auto;
}}

.card img {{
    width: 100%;
    border-radius: 28px;
    display: block;
}}

h2 {{
    font-size: 48px;
    margin: 10px 0 20px 0;
    font-weight: 800;
    line-height: 1.08;
}}

.copy {{
    max-width: 900px;
    margin: auto;
    font-size: 24px;
    color: #b8c2d6;
    line-height: 1.5;
}}

.bullets {{
    max-width: 900px;
    margin: 30px auto 0 auto;
    display: grid;
    gap: 16px;
}}

.bullet {{
    background: rgba(255,255,255,0.04);
    padding: 18px 22px;
    border-radius: 18px;
    font-size: 22px;
    text-align: left;
    border: 1px solid rgba(255,255,255,0.05);
}}

.features {{
    max-width: 1100px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 18px;
}}

.feature {{
    text-align: left;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 22px;
    padding: 24px 22px;
}}

.feature-title {{
    font-size: 22px;
    font-weight: 800;
    margin-bottom: 12px;
}}

.feature-copy {{
    font-size: 18px;
    line-height: 1.5;
    color: #b8c2d6;
}}

.cta {{
    margin-top: 40px;
}}

.cta-button {{
    display: inline-block;
    background: #FC4C02;
    color: #ffffff;
    text-decoration: none;
    border: none;
    padding: 18px 34px;
    font-size: 20px;
    font-weight: 700;
    border-radius: 16px;
    cursor: pointer;
    box-shadow: 0 10px 30px rgba(0,0,0,0.22);
    transition: background 0.2s ease, transform 0.2s ease;
}}

.cta-button:hover {{
    background: #e64500;
    transform: translateY(-1px);
}}

.micro {{
    margin-top: 10px;
    font-size: 16px;
    color: #9aa6bf;
}}

.footer {{
    margin-top: 40px;
    margin-bottom: 50px;
    color: #93a0b8;
    font-size: 16px;
}}

@media (max-width: 980px) {{
    h1 {{
        font-size: 50px;
    }}

    .sub {{
        font-size: 22px;
    }}

    h2 {{
        font-size: 38px;
    }}

    .copy {{
        font-size: 21px;
    }}

    .bullet {{
        font-size: 19px;
    }}

    .features {{
        grid-template-columns: 1fr;
    }}

    .feature-title {{
        font-size: 21px;
    }}

    .feature-copy {{
        font-size: 18px;
    }}
}}

@media (max-width: 560px) {{
    .hero {{
        padding-top: 42px;
    }}

    .logo {{
        width: 72px;
    }}

    .brand {{
        font-size: 15px;
    }}

    h1 {{
        font-size: 34px;
    }}

    .sub {{
        font-size: 18px;
    }}

    .badge {{
        font-size: 16px;
        padding: 12px 18px;
    }}

    .prediction-shell {{
        border-radius: 24px;
        padding: 14px;
    }}

    h2 {{
        font-size: 30px;
    }}

    .copy {{
        font-size: 18px;
    }}

    .bullet {{
        font-size: 17px;
        padding: 16px;
    }}

    .feature {{
        padding: 18px 16px;
    }}

    .feature-title {{
        font-size: 19px;
    }}

    .feature-copy {{
        font-size: 16px;
    }}

    .cta-button {{
        width: calc(100% - 40px);
        max-width: 520px;
        font-size: 18px;
        box-sizing: border-box;
    }}
}}
</style>
</head>

<body>
<div class="page">

    <div class="hero">
        <img src="{logo_url}" class="logo" alt="SecondCoach logo">
        <div class="brand">SECONDCOACH</div>

        <h1>Descubre tu predicción de carrera con SecondCoach</h1>

        <p class="sub">
            Conecta tu Strava y obtén una lectura clara de tu entrenamiento:
            tiempo estimado, margen frente a tu objetivo y señales reales de preparación.
        </p>

        <div class="badge">Basado en tu actividad reciente de Strava</div>
    </div>

    <div class="section">
        <div class="prediction-shell">
            <div class="card">
                <img src="{share_image}" alt="Predicción de carrera">
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Tu entrenamiento, explicado como lo haría un entrenador</h2>

        <p class="copy">
            No solo muestra un tiempo estimado. Te dice si vas por delante,
            si estás en línea o si tu objetivo empieza a estar en riesgo.
        </p>

        <div class="bullets">
            <div class="bullet">Dato → interpretación → decisión.</div>
            <div class="bullet">Volumen, tirada larga y trabajo a ritmo objetivo.</div>
            <div class="bullet">Una predicción fácil de entender y compartir.</div>
        </div>
    </div>

    <div class="section">
        <h2>Qué obtienes al conectar Strava</h2>

        <div class="features">
            <div class="feature">
                <div class="feature-title">Predicción actual</div>
                <div class="feature-copy">
                    Un tiempo estimado fácil de entender según tu entrenamiento reciente,
                    no una cifra suelta sin contexto.
                </div>
            </div>

            <div class="feature">
                <div class="feature-title">Margen frente a tu objetivo</div>
                <div class="feature-copy">
                    Sabrás si vas por delante, en línea o si tu objetivo empieza a estar
                    en riesgo antes de que sea demasiado tarde.
                </div>
            </div>

            <div class="feature">
                <div class="feature-title">Señales claras de preparación</div>
                <div class="feature-copy">
                    Volumen, tirada larga, bloques de calidad y ritmo objetivo convertidos
                    en una lectura simple, útil y accionable.
                </div>
            </div>
        </div>

        <div class="cta">
            <a class="cta-button" href="{login_url}">Conectar Strava y ver mi predicción</a>
            <div class="micro">Menos de 1 minuto.</div>
        </div>
    </div>

    <div class="footer">
        SecondCoach · análisis de entrenamiento explicable
    </div>

</div>
</body>
</html>
"""
    return HTMLResponse(content=html)


@router.get("/p/{athlete_id}", response_class=HTMLResponse)
def public_prediction_page(request: Request, athlete_id: int):
    return render_public_page(athlete_id=athlete_id, base_url=str(request.base_url))