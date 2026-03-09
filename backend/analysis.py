from datetime import datetime, timedelta, timezone


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


def detect_quality_blocks(runs):
    """
    MVP:
    detecta laps cercanas a ritmo maratón usando laps de Strava.
    Ventana actual: 4:45/km a 5:05/km (~objetivo 3h30).
    """
    blocks = []

    for r in runs:
        laps = r.get("laps") or []

        for lap in laps:
            distance_m = lap.get("distance", 0) or 0
            moving_time = lap.get("moving_time", 0) or 0

            km = distance_m / 1000
            if km < 0.8:
                continue

            pace = moving_time / km  # segundos por km

            if 285 <= pace <= 305:
                blocks.append(
                    {
                        "km": round(km, 2),
                        "pace": round(pace, 1),
                    }
                )

    return blocks