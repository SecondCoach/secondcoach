from math import pow


def riegel(time_seconds, dist1_km, dist2_km):
    if not dist1_km:
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


def predict_all_distances(avg_week_km, long_run_km, goal_blocks_km):
    """
    Firma compatible con backend/main.py:
    predict_all_distances(avg_week_km=..., long_run_km=..., goal_blocks_km=...)
    """

    avg_week_km = _safe_float(avg_week_km)
    long_run_km = _safe_float(long_run_km)
    goal_blocks_km = _safe_float(goal_blocks_km)

    score = avg_week_km * 0.6 + long_run_km * 0.3 + goal_blocks_km * 1.5

    if score <= 0:
        return {
            "5k": None,
            "10k": None,
            "half": None,
            "marathon": None,
        }

    # base simple sobre 10K
    base_10k_seconds = max(1800, 4200 - score * 20)

    pred_5k = riegel(base_10k_seconds, 10, 5)
    pred_half = riegel(base_10k_seconds, 10, 21.097)
    pred_marathon = riegel(base_10k_seconds, 10, 42.195)

    return {
        "5k": seconds_to_time_str(pred_5k),
        "10k": seconds_to_time_str(base_10k_seconds),
        "half": seconds_to_time_str(pred_half),
        "marathon": seconds_to_time_str(pred_marathon),
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