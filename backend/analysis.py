from datetime import datetime, timedelta, timezone


def pace_sec_per_km(activity):
    average_speed = activity.get("average_speed")
    if not average_speed:
        return None
    return 1000 / average_speed


def _parse_strava_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def detect_marathon_pace_blocks(
    runs,
    target_pace_sec,
    tolerance=15,
    min_distance_km=4.0,
    max_distance_km=18.0,
    recent_days=56,
):
    """
    MVP sin splits:
    detecta actividades recientes cuyo ritmo medio está cerca del ritmo objetivo.

    Ajustes para evitar ambos errores:
    - no sobrecontar todos los rodajes largos
    - no quedarse en cero por ser demasiado estricto
    """

    blocks = []

    lower = target_pace_sec - tolerance
    upper = target_pace_sec + tolerance
    now = datetime.now(timezone.utc)

    for run in runs:
        pace = pace_sec_per_km(run)
        if pace is None:
            continue

        start_date = run.get("start_date")
        distance_m = run.get("distance", 0)
        if not start_date or not distance_m:
            continue

        run_dt = _parse_strava_date(start_date)
        if now - run_dt > timedelta(days=recent_days):
            continue

        distance_km = distance_m / 1000

        if not (min_distance_km <= distance_km <= max_distance_km):
            continue

        if lower <= pace <= upper:
            blocks.append(
                {
                    "distance": round(distance_km, 1),
                    "pace": round(pace, 1),
                    "date": start_date[:10],
                    "name": run.get("name", "Run"),
                }
            )

    return blocks


def training_volume(runs):
    now = datetime.now(timezone.utc)

    km_7 = 0.0
    km_28 = 0.0
    long_run = 0.0

    for r in runs:
        start_date = r.get("start_date")
        distance_m = r.get("distance", 0)

        if not start_date or not distance_m:
            continue

        d = _parse_strava_date(start_date)
        km = distance_m / 1000

        if now - d < timedelta(days=7):
            km_7 += km

        if now - d < timedelta(days=28):
            km_28 += km

        long_run = max(long_run, km)

    avg_week = km_28 / 4 if km_28 else 0.0

    return round(km_7, 1), round(avg_week, 1), round(long_run, 1)