from fastapi.staticfiles import StaticFiles

from backend.main import app
from backend.db import init_db

# Inicializar base de datos al arrancar
init_db()

# Montar archivos estáticos
app.mount("/static", StaticFiles(directory="backend/static"), name="static")
