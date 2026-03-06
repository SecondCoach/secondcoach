from pathlib import Path
from functools import lru_cache
from starlette.config import Config


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

config = Config(str(ENV_FILE))


class Settings:
    STRAVA_CLIENT_ID: str = config("STRAVA_CLIENT_ID", cast=str)
    STRAVA_CLIENT_SECRET: str = config("STRAVA_CLIENT_SECRET", cast=str)
    STRAVA_REDIRECT_URI: str = config("STRAVA_REDIRECT_URI", cast=str)
    APP_SESSION_SECRET: str = config("APP_SESSION_SECRET", cast=str, default="change-this-in-production")


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()