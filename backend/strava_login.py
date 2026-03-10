from fastapi.responses import RedirectResponse
from backend.settings import settings


STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"


def login():

    params = {
        "client_id": settings.STRAVA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.STRAVA_REDIRECT_URI,
        "approval_prompt": "auto",
        "scope": "read,activity:read_all"
    }

    query = "&".join([f"{k}={v}" for k, v in params.items()])

    url = f"{STRAVA_AUTHORIZE_URL}?{query}"

    return RedirectResponse(url)