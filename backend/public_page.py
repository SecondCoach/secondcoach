from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def render_public_page(athlete_id: int, base_url: str) -> HTMLResponse:
    base_url = base_url.rstrip("/")
    page_url = f"{base_url}/p/{athlete_id}"
    share_image = f"{base_url}/share/{athlete_id}.png"
    logo_url = f"{base_url}/static/secondcoach_logo.png"

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
margin:0;
padding:0;
text-align:center;
color:#f5f7fb;
}}

.hero {{
padding:60px 20px 40px 20px;
max-width:1100px;
margin:auto;
}}

.logo {{
width:88px;
margin-bottom:18px;
}}

.brand {{
color:#a9b4c8;
font-size:18px;
letter-spacing:0.12em;
margin-bottom:10px;
}}

h1 {{
font-size:68px;
line-height:1.05;
letter-spacing:-0.03em;
margin-bottom:20px;
font-weight:800;
}}

.sub {{
max-width:900px;
margin:auto;
font-size:26px;
line-height:1.45;
color:#b8c2d6;
}}

.badge {{
display:inline-block;
margin-top:28px;
padding:14px 26px;
border-radius:999px;
font-size:18px;
background:rgba(255,255,255,0.06);
border:1px solid rgba(255,255,255,0.08);
}}

.section {{
padding:10px 20px 40px 20px;
}}

.prediction-shell {{
max-width:1120px;
margin:auto;
background:rgba(11,25,49,0.88);
border:1px solid rgba(139,171,255,0.16);
border-radius:36px;
padding:30px;
box-shadow:0 24px 80px rgba(0,0,0,0.28);
}}

.card img {{
width:100%;
border-radius:28px;
}}

h2 {{
font-size:48px;
margin-top:40px;
margin-bottom:20px;
font-weight:800;
}}

.copy {{
max-width:900px;
margin:auto;
font-size:24px;
color:#b8c2d6;
line-height:1.5;
}}

.bullets {{
max-width:900px;
margin:30px auto;
display:grid;
gap:16px;
}}

.bullet {{
background:rgba(255,255,255,0.04);
padding:18px 22px;
border-radius:18px;
font-size:22px;
text-align:left;
}}

.cta {{
margin-top:40px;
}}

button {{
background:white;
color:#071122;
border:none;
padding:18px 34px;
font-size:20px;
font-weight:700;
border-radius:16px;
cursor:pointer;
box-shadow:0 10px 30px rgba(0,0,0,0.22);
}}

.micro {{
margin-top:10px;
font-size:16px;
color:#9aa6bf;
}}

.footer {{
margin-top:40px;
margin-bottom:50px;
color:#93a0b8;
font-size:16px;
}}

</style>
</head>

<body>

<div class="hero">

<img src="{logo_url}" class="logo">

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
<img src="{share_image}">
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

<div class="cta">

<a href="{base_url}/login">
<button>Conectar Strava y ver mi predicción</button>
</a>

<div class="micro">Menos de 1 minuto.</div>

</div>

<div class="footer">
SecondCoach · análisis de entrenamiento explicable
</div>

</body>
</html>
"""
    return HTMLResponse(content=html)


@router.get("/p/{athlete_id}", response_class=HTMLResponse)
def public_prediction_page(request: Request, athlete_id: int):
    return render_public_page(athlete_id=athlete_id, base_url=str(request.base_url))