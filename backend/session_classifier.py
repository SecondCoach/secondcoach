from datetime import datetime


def classify_run(run: dict, quality_blocks: list) -> str:
    """
    Clasifica una sesión de running de forma simple.
    """

    try:
        distance_km = float(run.get("distance", 0)) / 1000
    except Exception:
        distance_km = 0

    if distance_km >= 28 and quality_blocks:
        return "marathon_specific"

    if distance_km >= 24:
        return "long_run"

    if distance_km >= 12:
        return "aerobic_run"

    return "short_run"


def detect_last_key_session(runs: list, quality_blocks: list):
    """
    Devuelve la última sesión relevante del ciclo.
    """

    if not runs:
        return None

    runs_sorted = sorted(
        runs,
        key=lambda r: r.get("start_date", ""),
        reverse=True
    )

    for run in runs_sorted:

        try:
            distance_km = float(run.get("distance", 0)) / 1000
        except Exception:
            distance_km = 0

        if distance_km < 12:
            continue

        session_type = classify_run(run, quality_blocks)

        return {
            "type": session_type,
            "date": (run.get("start_date_local") or "")[:10],
            "distance_km": round(distance_km, 1)
        }

    return None