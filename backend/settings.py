# backend/settings.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    STRAVA_CLIENT_ID: str
    STRAVA_CLIENT_SECRET: str
    STRAVA_REDIRECT_URI: str

    class Config:
        env_file = ".env"


settings = Settings()