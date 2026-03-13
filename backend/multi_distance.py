from typing import Dict, Tuple, List


def _clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(value, max_v))


def _sec_to_time(sec: float) -> str:
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}"


def predict_all_distances(
    avg_week_km: float,
    long_run_km: float,
    goal_blocks_km: float,
) -> Dict[str, str]:
    """
    Prediction v2 core.

    Inputs:
    - weekly volume
    - long run
    - marathon pace blocks

    Returns predicted times for distances.
    """

    base_marathon = 3 * 3600 + 30 * 60

    volume_factor = _clamp((avg_week_km - 40) / 40, -0.2, 0.2)
    long_run_factor = _clamp((long_run_km - 24) / 20, -0.15, 0.15)
    mp_factor = _clamp(goal_blocks_km / 60, 0, 0.12)

    adjustment = (
        volume_factor * -900
        + long_run_factor * -600
        + mp_factor * -300
    )

    marathon_sec = base_marathon + adjustment
    marathon_sec = _clamp(marathon_sec, 3 * 3600 + 10 * 60, 4 * 3600)

    k5 = marathon_sec * 0.105
    k10 = marathon_sec * 0.218
    half = marathon_sec * 0.46

    return {
        "5k": _sec_to_time(k5),
        "10k": _sec_to_time(k10),
        "half": _sec_to_time(half),
        "marathon": _sec_to_time(marathon_sec),
    }


def build_prediction_explanation(
    avg_week_km: float,
    long_run_km: float,
    goal_blocks_km: float,
    goal_time_sec: int,
    predicted_sec: int,
) -> Tuple[str, List[str], str]:
    """
    Builds:
    - confidence
    - why
    - missing_for_goal
    """

    why: List[str] = []

    if avg_week_km >= 55:
        why.append("Tu volumen semanal ya está en zona sólida para maratón.")
    elif avg_week_km >= 45:
        why.append("Tu volumen semanal es consistente.")
    else:
        why.append("Tu volumen semanal aún es limitado.")

    if long_run_km >= 28:
        why.append("Estás haciendo tiradas largas suficientes.")
    else:
        why.append("Tus tiradas largas aún pueden crecer.")

    if goal_blocks_km >= 20:
        why.append("Ya acumulas bastantes km a ritmo maratón.")
    elif goal_blocks_km >= 10:
        why.append("Empiezas a tener bloques específicos.")
    else:
        why.append("Aún faltan bloques largos a ritmo objetivo.")

    # confidence

    score = 0

    if avg_week_km >= 55:
        score += 2
    elif avg_week_km >= 45:
        score += 1

    if long_run_km >= 28:
        score += 2
    elif long_run_km >= 24:
        score += 1

    if goal_blocks_km >= 20:
        score += 2
    elif goal_blocks_km >= 10:
        score += 1

    if score >= 5:
        confidence = "high"
    elif score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    # missing for goal

    if predicted_sec <= goal_time_sec:
        missing = "Mantener consistencia y evitar picos de fatiga."
    elif avg_week_km < 55:
        missing = "Algo más de volumen semanal consolidaría el objetivo."
    elif goal_blocks_km < 15:
        missing = "Más km continuos a ritmo maratón reforzarían la predicción."
    else:
        missing = "Consolidar semanas consistentes cerca del objetivo."

    return confidence, why[:3], missing