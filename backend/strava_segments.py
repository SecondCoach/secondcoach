import requests
from backend.cache import get_cache, set_cache


STRAVA_API_BASE = "https://www.strava.com/api/v3"


def get_activity_laps(access_token: str, activity_id: int) -> list[dict]:

    cache_key = f"laps_{activity_id}"
    cached = get_cache(cache_key, ttl_seconds=600)

    if cached is not None:
        return cached

    response = requests.get(
        f"{STRAVA_API_BASE}/activities/{activity_id}/laps",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )

    if response.status_code != 200:
        return []

    laps = response.json()

    if isinstance(laps, list):
        set_cache(cache_key, laps)
        return laps

    return []


def _pace_sec_per_km_from_lap(lap: dict):

    elapsed = lap.get("elapsed_time") or lap.get("moving_time")
    distance_m = lap.get("distance")

    if not elapsed or not distance_m or distance_m <= 0:
        return None

    return elapsed / (distance_m / 1000)


def detect_goal_pace_lap_blocks(
    access_token: str,
    runs: list[dict],
    target_pace_sec: float,
    tolerance_sec: int = 15,
    min_block_km: float = 2.0,
):

    lower = target_pace_sec - tolerance_sec
    upper = target_pace_sec + tolerance_sec

    blocks = []

    for run in runs:

        activity_id = run.get("id")

        if not activity_id:
            continue

        laps = get_activity_laps(access_token, activity_id)

        current_distance = 0.0
        current_time = 0.0

        def flush():

            nonlocal current_distance, current_time

            if current_distance >= min_block_km:

                pace = current_time / current_distance

                if lower <= pace <= upper:
                    blocks.append(
                        {
                            "activity_id": activity_id,
                            "date": str(run.get("start_date", ""))[:10],
                            "activity_name": run.get("name", "Run"),
                            "distance": round(current_distance, 1),
                            "pace": round(pace, 1),
                        }
                    )

            current_distance = 0
            current_time = 0

        for lap in laps:

            lap_pace = _pace_sec_per_km_from_lap(lap)
            lap_dist = (lap.get("distance") or 0) / 1000
            lap_time = lap.get("elapsed_time") or lap.get("moving_time") or 0

            if lap_pace is None:
                flush()
                continue

            if lower <= lap_pace <= upper:
                current_distance += lap_dist
                current_time += lap_time
            else:
                flush()

        flush()

    return blocks


def total_block_km(blocks):

    return round(sum(b.get("distance", 0) for b in blocks), 1)