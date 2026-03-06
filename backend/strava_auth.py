import time
import requests

from backend.settings import settings
from backend.db import upsert_user

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def refresh_access_token_if_needed(user: dict) -> dict:
    """
    Refresh Strava token if expired.
    Returns updated user dict.
    """

    now = int(time.time())

    if user["expires_at"] > now:
        return user

    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": user["refresh_token"],
        },
        timeout=30,
    )

    response.raise_for_status()

    token_data = response.json()

    upsert_user(
        strava_athlete_id=user["strava_athlete_id"],
        username=user.get("username"),
        firstname=user.get("firstname"),
        lastname=user.get("lastname"),
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
    )

    user["access_token"] = token_data["access_token"]
    user["refresh_token"] = token_data["refresh_token"]
    user["expires_at"] = token_data["expires_at"]

    return user