from datetime import datetime, timedelta

from backend.session_classifier import detect_last_key_session


QUALITY_BLOCK_MIN_KM = 4


def compute_training(runs):
    """
    Calcula volumen reciente.
    """

    now = datetime.utcnow()

    km_7 = 0
    km_28 = 0
    long_km = 0

    for r in runs:
        try:
            distance_km = float(r.get("distance", 0)) / 1000
        except:
            distance_km = 0

        date_str = r.get("start_date")

        if not date_str:
            continue

        try:
            dt = datetime.fromisoformat(date_str.replace("Z", ""))
        except:
            continue

        days = (now - dt).days

        if days <= 7:
            km_7 += distance_km

        if days <= 28:
            km_28 += distance_km

        if distance_km > long_km:
            long_km = distance_km

    avg_week = km_28 / 4 if km_28 else 0

    return round(km_7, 1), round(avg_week, 1), round(long_km, 1)


def detect_quality_blocks(runs, goal_time="3:30", race_type="marathon"):
    """
    Detecta bloques a ritmo objetivo usando splits_metric.
    """

    blocks = []

    for run in runs:

        splits = run.get("splits_metric")

        if not splits:
            continue

        try:
            distance_km = float(run.get("distance", 0)) / 1000
        except:
            distance_km = 0

        if distance_km < 24:
            continue

        current_block = 0
        start_km = None

        for i, s in enumerate(splits):

            pace = s.get("average_speed")

            if not pace:
                continue

            pace_sec = 1000 / pace

            if 4.8 * 60 <= pace_sec <= 5.1 * 60:

                if current_block == 0:
                    start_km = i

                current_block += 1

            else:

                if current_block >= QUALITY_BLOCK_MIN_KM:

                    blocks.append(
                        {
                            "km": current_block,
                            "activity_id": run.get("id"),
                            "activity_name": run.get("name"),
                            "activity_date": (run.get("start_date_local") or "")[:10],
                            "total_run_km": round(distance_km, 1),
                            "start_km": start_km,
                            "end_km": start_km + current_block,
                        }
                    )

                current_block = 0

        if current_block >= QUALITY_BLOCK_MIN_KM:

            blocks.append(
                {
                    "km": current_block,
                    "activity_id": run.get("id"),
                    "activity_name": run.get("name"),
                    "activity_date": (run.get("start_date_local") or "")[:10],
                    "total_run_km": round(distance_km, 1),
                    "start_km": start_km,
                    "end_km": start_km + current_block,
                }
            )

    blocks.sort(key=lambda b: b["activity_date"], reverse=True)

    return blocks


def build_last_key_session(runs, quality_blocks):
    """
    Detecta la última sesión importante del ciclo.
    """

    return detect_last_key_session(runs, quality_blocks)
def build_last_key_session(runs, quality_blocks):
    """
    Devuelve la última sesión importante del ciclo.
    """

    if quality_blocks:
        b = quality_blocks[0]
        return {
            "type": "marathon_specific",
            "date": b.get("activity_date"),
            "distance_km": b.get("total_run_km"),
        }

    if runs:
        r = runs[0]
        try:
            km = float(r.get("distance", 0)) / 1000
        except Exception:
            km = 0

        return {
            "type": "long_run",
            "date": (r.get("start_date_local") or "")[:10],
            "distance_km": round(km, 1),
        }

    return None
