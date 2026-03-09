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
    Detecta bloques específicos de maratón usando splits_metric.

    Criterios MVP:
    - solo runs candidatas de 24 km o más
    - ventana MP entrenamiento: 4:49/km → 5:04/km
    - bloque mínimo: 4 km continuos
    - solo cuenta bloques en la segunda mitad de la tirada
    """

    blocks = []

    mp_low = 289   # 4:49/km
    mp_high = 304  # 5:04/km

    for r in runs:
        distance_m = r.get("distance", 0) or 0
        activity_id = r.get("id")

        if distance_m < 24000:
            continue

        if not activity_id:
            continue

        total_km = distance_m / 1000

        url = f"https://www.strava.com/api/v3/activities/{activity_id}"
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            res = requests.get(url, headers=headers, timeout=20)
            detail = res.json()
        except Exception:
            continue

        splits = detail.get("splits_metric") or []
        if not splits:
            continue

        current_block = 0.0
        km_covered = 0.0

        for s in splits:
            distance = s.get("distance", 0) or 0
            moving_time = s.get("moving_time", 0) or 0

            if distance <= 0 or moving_time <= 0:
                continue

            km = distance / 1000
            pace = moving_time / km
            block_start_km = km_covered
            km_covered += km

            in_second_half = block_start_km >= (total_km / 2)

            if in_second_half and mp_low <= pace <= mp_high:
                current_block += km
            else:
                if current_block >= 4.0:
                    blocks.append({"km": round(current_block, 2)})
                current_block = 0.0

        if current_block >= 4.0:
            blocks.append({"km": round(current_block, 2)})

    return blocks