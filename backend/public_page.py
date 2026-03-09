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
    image_url = f"{base_url}/share/{athlete_id}.png"
    login_url = f"{base_url}/login"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Predicción de carrera - SecondCoach</title>

        <!-- Open Graph -->
        <meta property="og:title" content="¿Estoy listo para mi objetivo?">
        <meta property="og:description" content="SecondCoach analiza mi entrenamiento y predice mi tiempo de carrera.">
        <meta property="og:image" content="{image_url}">
        <meta property="og:type" content="website">
        <meta property="og:url" content="{base_url}/p/{athlete_id}">

        <!-- Twitter -->
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="¿Estoy listo para mi objetivo?">
        <meta name="twitter:description" content="SecondCoach analiza mi entrenamiento y predice mi tiempo de carrera.">
        <meta name="twitter:image" content="{image_url}">

        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                background: #f5f5f5;
                padding: 40px;
                text-align: center;
            }}
            .card {{
                background: white;
                max-width: 600px;
                margin: auto;
                padding: 40px;
                border-radius: 14px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }}
            h1 {{
                margin-top: 0;
            }}
            img {{
                width: 100%;
                border-radius: 10px;
                margin-top: 20px;
            }}
            .cta {{
                display: inline-block;
                margin-top: 30px;
                background: #ff5a1f;
                color: white;
                padding: 16px 28px;
                border-radius: 8px;
                font-size: 18px;
                text-decoration: none;
                font-weight: 600;
            }}
        </style>
    </head>
    <body>

        <div class="card">
            <h1>SecondCoach</h1>

            <p>Analiza tu entrenamiento y descubre si estás listo para tu objetivo.</p>

            <img src="{image_url}" />

            <a class="cta" href="{login_url}">
                Analiza tu entrenamiento con Strava
            </a>
        </div>

    </body>
    </html>
    """

    return HTMLResponse(html)