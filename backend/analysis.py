from datetime import datetime, timedelta, timezone


def compute_training(runs):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=28)

    km_last_7 = 0
    km_last_28 = 0
    long_run = 0

    for r in runs:
        dist_km = r["distance"] / 1000
        date = datetime.fromisoformat(r["start_date"].replace("Z", "+00:00"))

        if date > week_ago:
            km_last_7 += dist_km

        if date > month_ago:
            km_last_28 += dist_km

        if dist_km > long_run:
            long_run = dist_km

    weekly_avg = km_last_28 / 4 if km_last_28 else 0

    return round(km_last_7, 1), round(weekly_avg, 1), round(long_run, 1)


def detect_quality_blocks(runs):
    """
    Versión simple:
    detecta bloques cercanos a ritmo maratón
    usando laps de Strava.
    """
    blocks = []

    for r in runs:
        if r.get("laps"):
            for lap in r["laps"]:
                km = lap["distance"] / 1000

                if km < 0.8:
                    continue

                pace = lap["moving_time"] / km

                # ritmo 4:45–5:05 (maratón ~3h30)
                if 285 <= pace <= 305:
                    blocks.append({
                        "km": round(km, 2),
                        "pace": pace,
                    })

    return blocks