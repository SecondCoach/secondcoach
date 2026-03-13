from fastapi.responses import HTMLResponse


def render_public_page(athlete_id: int) -> HTMLResponse:
    share_image = f"/share/{athlete_id}.png"

    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>

<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>SecondCoach — Predicción de carrera</title>

<meta name="description" content="SecondCoach analiza entrenamientos de Strava y genera una predicción clara de rendimiento en carrera basada en volumen, carga y trabajo a ritmo objetivo.">

<meta property="og:title" content="Predicción de carrera con SecondCoach">
<meta property="og:description" content="SecondCoach analiza entrenamientos de Strava y transforma datos complejos en una lectura clara: predicción actual, margen frente al objetivo y señales reales de preparación.">
<meta property="og:image" content="{share_image}">
<meta property="og:type" content="website">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{share_image}">

<link rel="icon" href="/static/secondcoach_logo.png">

<style>

body {{
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
background: #ffffff;
margin: 0;
padding: 0;
text-align: center;
color: #111;
}}

.hero {{
padding: 60px 20px 40px 20px;
}}

.logo {{
width: 120px;
margin-bottom: 30px;
}}

h1 {{
font-size: 34px;
margin-bottom: 20px;
}}

.sub {{
max-width: 680px;
margin: auto;
font-size: 18px;
line-height: 1.5;
color: #444;
}}

.section {{
padding: 40px 20px;
}}

.card {{
max-width: 600px;
margin: auto;
}}

.card img {{
width: 100%;
border-radius: 16px;
box-shadow: 0 10px 30px rgba(0,0,0,0.15);
}}

.cta {{
margin-top: 40px;
}}

button {{
background: black;
color: white;
border: none;
padding: 16px 26px;
font-size: 16px;
border-radius: 8px;
cursor: pointer;
}}

.footer {{
margin-top: 40px;
color: #666;
font-size: 14px;
}}

</style>

</head>

<body>

<div class="hero">

<img src="/static/secondcoach_logo.png" class="logo">

<h1>Este runner ya tiene una predicción de carrera con SecondCoach</h1>

<p class="sub">
SecondCoach analiza entrenamientos de Strava y transforma datos complejos
en una lectura clara: predicción actual, margen frente al objetivo
y señales reales de preparación.
</p>

</div>

<div class="section">

<p><b>Basado en su actividad reciente de Strava</b></p>

<div class="card">
<img src="{share_image}">
</div>

</div>

<div class="section">

<h2>Tu entrenamiento, explicado como lo haría un entrenador</h2>

<p class="sub">
No solo muestra un tiempo estimado. Te dice si vas por delante, si estás en línea o si tu objetivo empieza a estar en riesgo.
</p>

<p class="sub">
Dato → interpretación → decisión.
</p>

<p class="sub">
Volumen, tirada larga y trabajo a ritmo objetivo.
Una predicción fácil de entender y compartir.
</p>

</div>

<div class="section cta">

<a href="/login">
<button>Conectar Strava y analizar mi entrenamiento</button>
</a>

</div>

<div class="footer">

SecondCoach · análisis de entrenamiento explicable

</div>

</body>
</html>
"""
    return HTMLResponse(html)