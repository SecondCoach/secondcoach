from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple


# =========================
# HELPERS
# =========================

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(activity: Dict[str, Any]) -> Optional[datetime]:
    raw = activity.get("start_date") or activity.get("start_date_local")
    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _extract_distance_km(activity: Dict[str, Any]) -> float:
    if activity.get("distance") is not None:
        return _safe_float(activity.get("distance")) / 1000.0
    return _safe_float(activity.get("distance_km"))


def _sec_to_time(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def _parse_goal(goal: Optional[str]) -> Optional[int]:
    if not goal:
        return None

    parts = str(goal).split(":")
    try:
        if len(parts) == 2:
            h, m = parts
            return int(h) * 3600 + int(m) * 60
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + int(s)
    except ValueError:
        return None

    return None


def _format_pace(sec_per_km: Optional[float]) -> Optional[str]:
    if sec_per_km is None:
        return None

    total = max(0, int(round(sec_per_km)))
    minutes = total // 60
    seconds = total % 60
    return f"{minutes}:{seconds:02d}"


# =========================
# TRAINING
# CONTRATO:
# km_last_7, avg_week_km, long_run_km = compute_training(all_runs)
# =========================

def compute_training(runs: List[Dict[str, Any]]) -> Tuple[float, float, float]:
    now = _now()
    cutoff_7d = now - timedelta(days=7)
    cutoff_28d = now - timedelta(days=28)

    km_7 = 0.0
    long_run = 0.0
    weekly_buckets = [0.0, 0.0, 0.0, 0.0]

    for run in runs:
        date = _parse_date(run)
        if not date:
            continue

        km = _extract_distance_km(run)
        if km <= 0:
            continue

        if date > now:
            continue

        if cutoff_7d <= date <= now:
            km_7 += km

        if cutoff_28d <= date <= now:
            age_seconds = (now - date).total_seconds()
            bucket_index = int(age_seconds // (7 * 24 * 3600))
            bucket_index = min(max(bucket_index, 0), 3)
            weekly_buckets[bucket_index] += km

        if km > long_run:
            long_run = km

    avg_week = sum(weekly_buckets) / 4.0
    return round(km_7, 1), round(avg_week, 1), round(long_run, 1)


# =========================
# FATIGUE
# =========================

def compute_fatigue_signal(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    now = _now()
    daily_km: Dict[Any, float] = {}

    for i in range(7):
        day = (now - timedelta(days=i)).date()
        daily_km[day] = 0.0

    for run in runs:
        date = _parse_date(run)
        if not date:
            continue

        day = date.date()
        if day in daily_km:
            daily_km[day] += _extract_distance_km(run)

    values = list(daily_km.values())
    weekly_total = sum(values)
    mean = weekly_total / 7.0
    variance = sum((x - mean) ** 2 for x in values) / 7.0
    std = variance ** 0.5
    monotony = mean / std if std > 0 else 10.0

    _, avg_week, _ = compute_training(runs)
    load_ratio = (weekly_total / avg_week) if avg_week > 0 else 0.0
    strain = weekly_total * monotony
    spike_ratio = (max(values) / mean) if mean > 0 else 0.0

    red_flags = 0
    yellow_flags = 0

    if load_ratio >= 1.30:
        red_flags += 1
    elif load_ratio >= 1.12:
        yellow_flags += 1

    if monotony >= 2.20:
        red_flags += 1
    elif monotony >= 1.80:
        yellow_flags += 1

    if spike_ratio >= 2.20:
        red_flags += 1
    elif spike_ratio >= 1.80:
        yellow_flags += 1

    if strain >= 95:
        red_flags += 1
    elif strain >= 70:
        yellow_flags += 1

    if red_flags >= 2 or (red_flags >= 1 and yellow_flags >= 1):
        label = "Alta"
        message = "Fatiga elevada"
    elif yellow_flags >= 1 or red_flags == 1:
        label = "Media"
        message = "Carga moderada"
    else:
        label = "Baja"
        message = "Fatiga controlada"

    return {
        "label": label,
        "message": message,
        "load_ratio": round(load_ratio, 2),
        "monotony": round(monotony, 2),
        "strain": round(strain, 1),
        "spike_ratio": round(spike_ratio, 2),
    }


# =========================
# QUALITY BLOCKS
# =========================

def _extract_units_from_laps(run: Dict[str, Any]) -> List[Dict[str, float]]:
    laps = run.get("laps") or []
    units: List[Dict[str, float]] = []

    for lap in laps:
        km = _safe_float(lap.get("distance")) / 1000.0
        sec = _safe_float(lap.get("moving_time"))
        if km > 0 and sec > 0:
            units.append(
                {
                    "km": km,
                    "sec": sec,
                    "pace": sec / km,
                }
            )

    return units


def _is_recent(run: Dict[str, Any], days: int = 42) -> bool:
    d = _parse_date(run)
    return bool(d and d >= (_now() - timedelta(days=days)))


def _block_quality_score(block: Dict[str, Any]) -> float:
    km = _safe_float(block.get("km"))
    pace = _safe_float(block.get("avg_pace_sec_per_km"))
    source_kind = str(block.get("source_kind") or "")
    total_run_km = _safe_float(block.get("total_run_km"))

    score = 0.0
    score += min(km / 6.0, 2.5)

    if source_kind == "macro":
        score += 1.0
    elif source_kind == "laps":
        score += 0.4

    if total_run_km >= 24 and km >= 6:
        score += 0.7
    if total_run_km >= 18 and km >= 4:
        score += 0.4
    if 285 <= pace <= 305:
        score += 0.6

    return round(score, 3)


def _is_valid_marathon_block(block: Dict[str, Any]) -> bool:
    km = _safe_float(block.get("km"))
    source_kind = str(block.get("source_kind") or "")
    total_run_km = _safe_float(block.get("total_run_km"))

    if source_kind == "macro":
        return km >= 8.0

    if km < 4.0:
        return False

    if total_run_km >= 22 and km >= 4.0:
        return True

    return km >= 5.0


def detect_quality_blocks(
    runs: List[Dict[str, Any]],
    goal_pace_sec: float = 299.0,
    slow_tol: float = 15.0,
    fast_tol: float = 30.0,
    min_block_km: float = 3.0,
) -> List[Dict[str, Any]]:
    upper = goal_pace_sec + slow_tol
    lower = goal_pace_sec - fast_tol

    blocks: List[Dict[str, Any]] = []

    for run in runs:
        if not _is_recent(run):
            continue

        units = _extract_units_from_laps(run)
        if not units:
            continue

        total_km = sum(u["km"] for u in units)
        if total_km <= 0:
            continue

        in_range_km = sum(u["km"] for u in units if lower <= u["pace"] <= upper)

        if total_km >= 8 and (in_range_km / total_km) >= 0.85:
            total_sec = sum(u["sec"] for u in units)
            pace = total_sec / total_km

            block = {
                "activity_name": run.get("name"),
                "activity_date": str(run.get("start_date"))[:10],
                "km": round(total_km, 1),
                "avg_pace_sec_per_km": pace,
                "avg_pace": _format_pace(pace),
                "start_km": 0,
                "end_km": round(total_km, 1),
                "source_kind": "macro",
                "total_run_km": round(total_km, 1),
            }

            if _is_valid_marathon_block(block):
                block["quality_score"] = _block_quality_score(block)
                blocks.append(block)

            continue

        current_km = 0.0
        current_sec = 0.0
        start_km = 0.0
        cumulative = 0.0

        for unit in units:
            km = unit["km"]
            sec = unit["sec"]
            pace = unit["pace"]

            prev = cumulative
            cumulative += km

            if lower <= pace <= upper:
                if current_km == 0:
                    start_km = prev
                current_km += km
                current_sec += sec
            else:
                if current_km >= min_block_km:
                    block = {
                        "activity_name": run.get("name"),
                        "activity_date": str(run.get("start_date"))[:10],
                        "km": round(current_km, 1),
                        "avg_pace_sec_per_km": current_sec / current_km,
                        "avg_pace": _format_pace(current_sec / current_km),
                        "start_km": round(start_km, 1),
                        "end_km": round(prev, 1),
                        "source_kind": "laps",
                        "total_run_km": round(total_km, 1),
                    }

                    if _is_valid_marathon_block(block):
                        block["quality_score"] = _block_quality_score(block)
                        blocks.append(block)

                current_km = 0.0
                current_sec = 0.0

        if current_km >= min_block_km:
            block = {
                "activity_name": run.get("name"),
                "activity_date": str(run.get("start_date"))[:10],
                "km": round(current_km, 1),
                "avg_pace_sec_per_km": current_sec / current_km,
                "avg_pace": _format_pace(current_sec / current_km),
                "start_km": round(start_km, 1),
                "end_km": round(cumulative, 1),
                "source_kind": "laps",
                "total_run_km": round(total_km, 1),
            }

            if _is_valid_marathon_block(block):
                block["quality_score"] = _block_quality_score(block)
                blocks.append(block)

    blocks.sort(
        key=lambda b: (
            _safe_float(b.get("quality_score")),
            _safe_float(b.get("km")),
            str(b.get("activity_date")),
        ),
        reverse=True,
    )
    return blocks


# =========================
# LAST KEY SESSION
# =========================

def build_last_key_session(
    all_runs: List[Dict[str, Any]],
    quality_blocks: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if quality_blocks:
        block = sorted(quality_blocks, key=lambda x: x["activity_date"], reverse=True)[0]
        return {
            "type": "bloque ritmo objetivo",
            "date": block["activity_date"],
            "distance_km": block["km"],
        }

    return None


# =========================
# PREDICTION
# =========================

def _weighted_pace(blocks: List[Dict[str, Any]]) -> Optional[float]:
    if not blocks:
        return None

    weighted_sum = 0.0
    total_weight = 0.0

    for block in blocks:
        km = _safe_float(block.get("km"))
        pace = _safe_float(block.get("avg_pace_sec_per_km"))
        quality = _safe_float(block.get("quality_score"), 1.0)

        if km <= 0 or pace <= 0:
            continue

        effective_km = min(km, 10.0)
        effective_quality = min(max(quality, 0.5), 3.0)
        weight = effective_km * effective_quality

        weighted_sum += pace * weight
        total_weight += weight

    if total_weight <= 0:
        return None

    return weighted_sum / total_weight


def _block_consistency_penalty(blocks: List[Dict[str, Any]]) -> float:
    usable = [
        _safe_float(block.get("avg_pace_sec_per_km"))
        for block in blocks
        if _safe_float(block.get("avg_pace_sec_per_km")) > 0
    ]

    if len(usable) < 2:
        return 0.018

    mean = sum(usable) / len(usable)
    variance = sum((x - mean) ** 2 for x in usable) / len(usable)
    std = variance ** 0.5

    if std <= 3:
        return 0.004
    if std <= 6:
        return 0.012
    if std <= 10:
        return 0.02
    return 0.03


def _specificity_depth(blocks: List[Dict[str, Any]]) -> float:
    depth = 0.0

    for block in blocks:
        km = min(_safe_float(block.get("km")), 10.0)
        quality = min(max(_safe_float(block.get("quality_score"), 1.0), 0.5), 3.0)
        depth += km * quality

    return depth


def _few_blocks_penalty(blocks: List[Dict[str, Any]]) -> float:
    count = len(blocks)

    if count >= 5:
        return 0.0
    if count == 4:
        return 0.006
    if count == 3:
        return 0.014
    if count == 2:
        return 0.024
    if count == 1:
        return 0.04
    return 0.055


def compute_prediction(
    training: Dict[str, Any],
    fatigue: Dict[str, Any],
    quality_blocks: List[Dict[str, Any]],
    goal_time: Optional[str],
    race_context: Dict[str, Any] | None = None,
    objective: Optional[str] = None,
) -> Dict[str, Any]:
    weekly = _safe_float(training.get("weekly_average_km"))
    long_run = _safe_float(training.get("long_run_km"))
    spec_km = sum(_safe_float(block.get("km")) for block in quality_blocks)
    spec_depth = _specificity_depth(quality_blocks)

    base_pace = _weighted_pace(quality_blocks) or 305.0
    pace = base_pace

    pace *= (1 - 0.018 * min(spec_depth / 55.0, 1.0))
    pace *= (1 - 0.010 * min(long_run / 30.0, 1.0))
    pace *= (1 - 0.008 * min(weekly / 60.0, 1.0))

    block_lengths = [_safe_float(block.get("km")) for block in quality_blocks if _safe_float(block.get("km")) > 0]
    avg_block = (sum(block_lengths) / len(block_lengths)) if block_lengths else 0.0

    endurance_penalty = max(0.0, (10.0 - avg_block) / 10.0) * 0.035
    volume_penalty = max(0.0, (30.0 - spec_km) / 30.0) * 0.03
    consistency_penalty = _block_consistency_penalty(quality_blocks)
    few_blocks_penalty = _few_blocks_penalty(quality_blocks)
    projection_penalty = 0.028

    pace *= (
        1.0
        + endurance_penalty
        + volume_penalty
        + consistency_penalty
        + few_blocks_penalty
        + projection_penalty
    )

    fatigue_label = str(fatigue.get("label") or "")
    is_marathon_pre_race = (
        objective == "marathon"
        and bool(race_context)
        and bool(race_context.get("is_pre_race_window"))
    )
    if fatigue_label == "Alta":
        pace *= 1.015 if is_marathon_pre_race else 1.035
    elif fatigue_label == "Media":
        pace *= 1.01 if is_marathon_pre_race else 1.02

    total = pace * 42.195
    low = total * 0.955
    high = total * 1.045

    goal = _parse_goal(goal_time)
    diff = int(round((total - goal) / 60.0)) if goal else None

    return {
        "predicted_time": _sec_to_time(total),
        "range_low": _sec_to_time(low),
        "range_high": _sec_to_time(high),
        "minutes_vs_goal": diff,
        "debug": {
            "base_weighted_pace_sec_per_km": round(base_pace, 1),
            "final_projected_pace_sec_per_km": round(pace, 1),
            "specificity_km": round(spec_km, 1),
            "specificity_depth": round(spec_depth, 1),
            "avg_block_km": round(avg_block, 1),
            "endurance_penalty": round(endurance_penalty, 4),
            "volume_penalty": round(volume_penalty, 4),
            "consistency_penalty": round(consistency_penalty, 4),
            "few_blocks_penalty": round(few_blocks_penalty, 4),
            "projection_penalty": round(projection_penalty, 4),
            "fatigue_label": fatigue.get("label"),
        },
    }


# =========================
# COACH
# =========================

def build_coach(
    prediction: Dict[str, Any],
    training: Dict[str, Any],
    fatigue: Dict[str, Any],
    last_key_session: Optional[Dict[str, Any]],
    quality_blocks: List[Dict[str, Any]],
) -> Dict[str, str]:
    weekly = _safe_float(training.get("weekly_average_km"))
    long_run = _safe_float(training.get("long_run_km"))
    fatigue_label = str(fatigue.get("label") or "")
    predicted_time = str(prediction.get("predicted_time") or "")
    spec_km = sum(_safe_float(block.get("km")) for block in quality_blocks)

    if last_key_session:
        positive = (
            f"Has consolidado una sesión clave reciente de {last_key_session.get('distance_km')} km, "
            "lo que refuerza tu capacidad de sostener ritmo objetivo."
        )
    elif quality_blocks:
        positive = "Ya aparecen bloques específicos útiles para estimar tu nivel actual."
    else:
        positive = "Todavía no hay sesiones clave claras detectadas."

    if fatigue_label == "Alta":
        limiter = "La fatiga es alta y puede distorsionar tanto el rendimiento reciente como la asimilación."
    elif weekly < 45:
        limiter = "El volumen semanal todavía limita la solidez de la proyección maratón."
    elif spec_km < 24:
        limiter = "Falta algo más de especificidad reciente para que la proyección sea más robusta."
    else:
        limiter = "La carga está concentrada en pocos días, lo que incrementa el riesgo de fatiga residual."

    if long_run < 26:
        next_focus = "Necesitas consolidar mejor la tirada larga para sostener el ritmo objetivo en maratón."
    elif spec_km < 30:
        next_focus = "Conviene sumar más kilómetros específicos controlados dentro de tiradas o sesiones estables."
    else:
        next_focus = "Distribuye mejor la carga semanal para reducir picos y mejorar la asimilación."

    summary = ""
    if predicted_time:
        summary = f"Con la evidencia actual, tu proyección maratón se mueve alrededor de {predicted_time}."
    elif quality_blocks:
        summary = "Hay señales útiles, pero todavía no suficiente consistencia para una predicción sólida."

    return {
        "positive": positive,
        "limiter": limiter,
        "next_focus": next_focus,
        "summary": summary,
    }
# =========================
# ONE LINE (FINAL PRODUCT)
# =========================



def _round_time_5min(hhmm: str) -> str:
    try:
        h, m = hhmm.split(":")
        h = int(h)
        m = int(m)
        m_rounded = 5 * round(m / 5)
        if m_rounded == 60:
            h += 1
            m_rounded = 0
        return f"{h}:{m_rounded:02d}"
    except:
        return hhmm

def build_one_line(
    prediction: Dict[str, Any],
    training: Dict[str, Any],
    fatigue: Dict[str, Any],
    quality_blocks: List[Dict[str, Any]],
    goal_time: str | None = None,
    race_context: Dict[str, Any] | None = None,
) -> Dict[str, str]:

    def fatigue_high():
        load = _safe_float(fatigue.get("load_ratio"), 1)
        monotony = _safe_float(fatigue.get("monotony"), 0)
        strain = _safe_float(fatigue.get("strain"), 0)
        return load > 1.35 or (monotony > 2 and strain > 500)

    def initial():
        km7 = _safe_float(training.get("km_last_7_days"), 0)
        return km7 < 25 or not quality_blocks

    def prediction_ok():
        return prediction and prediction.get("confidence") != "low"

    def mv():
        return prediction.get("minutes_vs_goal") or 0

    def low_specificity():
        if not quality_blocks:
            return True
        total = sum(_safe_float(b.get("km")) for b in quality_blocks)
        return total < 6

    def low_continuity():
        km7 = _safe_float(training.get("km_last_7_days"), 0)
        avg = _safe_float(training.get("weekly_average_km"), 0)
        return avg == 0 or km7 < 0.7 * avg

    def _format_hhmm(value: str | None) -> str:
        if not value:
            return ""
        parts = str(value).split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:{parts[1]}"
        return str(value)

    def _goal_label(value: str | None) -> str:
        hhmm = _format_hhmm(value)
        if hhmm.startswith("3:"):
            return f"sub {hhmm}"
        return hhmm

    def _behind_punchline() -> str:
        predicted_hhmm = _format_hhmm(prediction.get("predicted_time"))
        goal_hhmm = _format_hhmm(goal_time)
        goal_label = _goal_label(goal_time)
        if predicted_hhmm and goal_label:
            return f"Tu entrenamiento ahora mismo es de {_round_time_5min(predicted_hhmm)}, no de {goal_time}."
        return "Ahora mismo ese objetivo te queda lejos."

    def in_pre_race_window() -> bool:
        return bool(race_context and race_context.get("is_pre_race_window"))

    # FATIGA
    if fatigue_high():
        if not in_pre_race_window():
            return {
                "headline": "Estás entrenando, pero no estás asimilando.",
                "subline": "Porque la carga reciente te está pesando más de lo que estás asimilando.",
                "action": "Esta semana baja carga y llega fresco.",
                "chip": "FATIGA ALTA",
            }

    # INICIAL
    if initial():
        return {
            "headline": "Aún no hay una lectura clara.",
            "subline": "Porque aún no hay suficiente entrenamiento reciente para evaluarte.",
            "action": "Entrena unas semanas con continuidad y volvemos a leerlo.",
            "chip": "LECTURA INICIAL",
        }

    # PREDICTION
    if prediction_ok():
        minutes = mv()

        if minutes > 10:
            suggested_goal = _round_time_5min(_format_hhmm(prediction.get("predicted_time"))) if prediction.get("predicted_time") else ""
            goal_text = suggested_goal or _round_time_5min(_format_hhmm(prediction.get("predicted_time")))
            action = (
                f"O bajas a {goal_text}, o entrenas para correr en {goal_time}."
                if goal_text else
                "Ajusta tu objetivo o cambia el nivel de entrenamiento."
            )
            return {
                "headline": "Así, no te va a dar.",
                "subline": f"Tu entrenamiento ahora mismo es de {goal_text}, no de {goal_time}." if goal_text and goal_time else "Ahora mismo ese objetivo no encaja con tu nivel.",
                "action": action,
                "suggested_goal": suggested_goal,
                "chip": "POR DETRÁS",
            }

        if 3 < minutes <= 10:
            motivo = (
                "Porque aún no estás sosteniendo suficiente trabajo a ritmo objetivo."
                if low_specificity()
                else "Porque te falta continuidad en el trabajo que realmente importa."
            )
            return {
                "headline": "Estás cerca, pero aún no es suficiente.",
                "subline": motivo,
                "action": "No sumes por sumar: repite semanas buenas.",
                "chip": "CERCA",
            }

        if -3 <= minutes <= 3:
            if low_specificity():
                return {
                    "headline": "Estás cerca, pero aún no es suficiente.",
                    "subline": "Porque aún no estás sosteniendo suficiente trabajo a ritmo objetivo.",
                    "action": "No sumes por sumar: repite semanas buenas.",
                    "chip": "CERCA",
                }

            if minutes >= 0:
                return {
                    "headline": "Estás en nivel para ese objetivo.",
                    "subline": "Hoy te da, pero con poco margen.",
                    "action": "Mantén el rumbo y protege el trabajo útil.",
                    "chip": "EN OBJETIVO",
                }

            return {
                "headline": "Estás haciendo lo necesario para tu objetivo.",
                "subline": "Ya estás sosteniendo trabajo específico reciente que encaja con ese nivel.",
                "action": "Mantén el rumbo y no cambies lo que está funcionando.",
                "chip": "EN OBJETIVO",
            }

        if minutes < -3:
            return {
                "headline": "Vas por delante de lo que exige tu objetivo.",
                "subline": "Porque ya estás acumulando más trabajo útil del necesario para ese nivel.",
                "action": "No aprietes más: consolida y evita pasarte.",
                "chip": "POR DELANTE",
            }

    # FALLBACK
    return {
        "headline": "Aún no hay una lectura clara.",
        "subline": "Porque aún no hay suficiente entrenamiento reciente para evaluarte.",
        "action": "Entrena unas semanas con continuidad y volvemos a leerlo.",
        "chip": "LECTURA INICIAL",
    }
