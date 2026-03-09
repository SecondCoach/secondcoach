from math import pow


def riegel(time_seconds, dist1_km, dist2_km):
    if not dist1_km or time_seconds is None:
        return None
    return time_seconds * pow(dist2_km / dist1_km, 1.06)


def seconds_to_time_str(seconds):
    if seconds is None:
        return None

    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _clamp(value, low, high):
    return max(low, min(high, value))


def predict_all_distances(avg_week_km, long_run_km, goal_blocks_km):
    """
    MVP calibrado para que la predicción de maratón sea plausible
    con las métricas que ya calcula SecondCoach.

    Entradas:
    - avg_week_km
    - long_run_km
    - goal_blocks_km

    Salidas:
    - 5k
    - 10k
    - half
    - marathon
    """

    avg_week_km = _safe_float(avg_week_km)
    long_run_km = _safe_float(long_run_km)
    goal_blocks_km = _safe_float(goal_blocks_km)

    if avg_week_km <= 0 and long_run_km <= 0 and goal_blocks_km <= 0:
        return {
            "5k": None,
            "10k": None,
            "half": None,
            "marathon": None,
        }

    # Heurística simple, pero calibrada:
    # más volumen semanal, tirada larga y km a ritmo objetivo => mejor maratón
    marathon_seconds = (
        15480
        - avg_week_km * 20
        - long_run_km * 30
        - goal_blocks_km * 8
    )

    # límites razonables para evitar barbaridades
    marathon_seconds = _clamp(marathon_seconds, 10800, 18000)  # 3:00:00 a 5:00:00

    pred_half = riegel(marathon_seconds, 42.195, 21.097)
    pred_10k = riegel(marathon_seconds, 42.195, 10)
    pred_5k = riegel(marathon_seconds, 42.195, 5)

    return {
        "5k": seconds_to_time_str(pred_5k),
        "10k": seconds_to_time_str(pred_10k),
        "half": seconds_to_time_str(pred_half),
        "marathon": seconds_to_time_str(marathon_seconds),
    }


def _time_str_to_seconds(value):
    if not value:
        return None

    parts = str(value).split(":")
    parts = [int(p) for p in parts]

    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s

    if len(parts) == 2:
        m, s = parts
        return m * 60 + s

    return None


def predict_goal(goal_time_seconds, goal_distance_km, predictions):
    key_map = {
        5: "5k",
        10: "10k",
        21: "half",
        42: "marathon",
    }

    key = key_map.get(goal_distance_km)
    if not key:
        return None

    predicted_seconds = _time_str_to_seconds(predictions.get(key))
    if predicted_seconds is None:
        return None

    diff = predicted_seconds - goal_time_seconds

    if diff < -300:
        return "ahead"
    if diff > 300:
        return "behind"
    return "on_track"