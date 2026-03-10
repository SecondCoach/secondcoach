from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "SecondCoach"
    APP_ENV: str = Field(default="development")
    APP_SESSION_SECRET: str = Field(default="change-this-session-secret")

    # Backend public URL
    BASE_URL: str = Field(default="http://127.0.0.1:8000")

    # Strava OAuth
    STRAVA_CLIENT_ID: str = Field(default="")
    STRAVA_CLIENT_SECRET: str = Field(default="")
    STRAVA_REDIRECT_URI: str = Field(default="http://127.0.0.1:8000/callback")

    # Race defaults
    DEFAULT_RACE_TYPE: str = Field(default="marathon")
    DEFAULT_RACE_NAME: str = Field(default="Maratón objetivo")
    DEFAULT_RACE_DATE: str = Field(default="2026-04-12")
    DEFAULT_GOAL_TIME: str = Field(default="3:30")

    # Data / analysis
    ANALYSIS_WEEKS: int = Field(default=12)
    ACTIVITIES_PER_PAGE: int = Field(default=200)

    @property
    def analysis_days(self) -> int:
        return self.ANALYSIS_WEEKS * 7


settings = Settings()