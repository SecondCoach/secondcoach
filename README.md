
# SecondCoach Web MVP

## Requisitos
- Python 3.10+
- Cuenta Strava con App creada

## Pasos
1. Rellena CLIENT_ID y CLIENT_SECRET en backend/main.py
2. pip install fastapi uvicorn requests
3. uvicorn backend.main:app --reload
4. Abre frontend/index.html en el navegador
5. Conecta con Strava y revisa el análisis

## Qué valida
- OAuth Strava real
- Lectura de actividades reales
- Análisis semanal explicable
- Base del producto SecondCoach
