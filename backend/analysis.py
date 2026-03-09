from datetime import datetime, timedelta, timezone
import requests


def compute_training(runs):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=28)

    km_last_7 = 0.0
    km_last_28 = 0.0
    long_run_28 = 0.0

    for r in runs:
        distance_m = r.get("distance", 0) or 0
        start_date = r.get("start_date")

        if not start_date:
            continue

        dist_km = distance_m / 1000
        date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))

        if date > week_ago:
            km_last_7 += dist_km

        if date > month_ago:
            km_last_28 += dist_km
            if dist_km > long_run_28:
                long_run_28 = dist_km

    weekly_avg = km_last_28 / 4 if km_last_28 else 0.0

    return round(km_last_7, 1), round(weekly_avg, 1), round(long_run_28, 1)


def detect_quality_blocks(runs, access_token):
    """
    Detecta bloques MP usando splits_metric por km.
    """

    blocks = []

    # ventana MP entrenamiento (3:30 objetivo)
    mp_low = 289   # 4:49/km
    mp_high = 304  # 5:04/km

    for r in runs:

        distance_m = r.get("distance", 0) or 0
        activity_id = r.get("id")

        if distance_m < 16000:
            continue

        if not activity_id:
            continue

        url = f"https://www.strava.com/api/v3/activities/{activity_id}"

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        try:
            res = requests.get(url, headers=headers, timeout=20)
            detail = res.json()
        except Exception:
            continue

        splits = detail.get("splits_metric")

        if not splits:
            continue

        current_block = 0.0

        for s in splits:

            distance = s.get("distance", 0) or 0
            moving_time = s.get("moving_time", 0) or 0

            if distance == 0:
                continue

            km = distance / 1000
            pace = moving_time / km

            if mp_low <= pace <= mp_high:
                current_block += km
            else:
                if current_block >= 2:
                    blocks.append({"km": round(current_block, 2)})
                current_block = 0

        if current_block >= 2:
            blocks.append({"km": round(current_block, 2)})

    return blocks