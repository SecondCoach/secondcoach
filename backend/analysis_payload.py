from datetime import datetime, timedelta, timezone
from typing import Any

from backend.analysis import (
    build_coach,
    build_last_key_session,
    build_one_line,
    compute_fatigue_signal,
    compute_prediction,
    compute_training,
    detect_quality_blocks,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_time_to_seconds(time_str: str | None) -> int | None:
    if not time_str:
        return None

    raw = str(time_str).strip()
    if not raw:
        return None

    parts = raw.split(":")
    try:
        if len(parts) == 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            return hours * 3600 + minutes * 60
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return None

    return None


def _format_goal_time(goal_time: str | None) -> str | None:
    if not goal_time:
        return None
    raw = str(goal_time).strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    if len(parts) == 3:
        return f"{parts[0]}:{parts[1]}:{parts[2]}"
    return raw


def _normalize_objective(objective: str | None) -> str:
    if not objective:
        return "marathon"

    raw = str(objective).strip().lower()

    if "media" in raw or "half" in raw:
        return "half_marathon"
    if "10" in raw:
        return "10k"
    if "5" in raw:
        return "5k"

    return "marathon"


def _objective_display_name(objective: str) -> str:
    if objective == "half_marathon":
        return "Media maratón"
    if objective == "10k":
        return "10K"
    if objective == "5k":
        return "5K"
    return "Maratón"


def _extract_delta_minutes(prediction: dict[str, Any], goal_time: str | None) -> int | None:
    direct = prediction.get("minutes_vs_goal")
    if direct is not None:
        return _safe_int(direct)

    predicted_time = prediction.get("predicted_time")
    predicted_seconds = _parse_time_to_seconds(predicted_time)
    goal_seconds = _parse_time_to_seconds(goal_time)

    if predicted_seconds is None or goal_seconds is None:
        return None

    return round((predicted_seconds - goal_seconds) / 60)


def _build_status_block(goal_time: str | None, prediction: dict[str, Any]) -> dict[str, Any]:
    predicted_time = prediction.get("predicted_time")
    delta_minutes = _extract_delta_minutes(prediction, goal_time)

    if delta_minutes is None:
        status_label = "sin suficiente señal"
    elif delta_minutes <= -3:
        status_label = "por delante"
    elif delta_minutes <= 2:
        status_label = "en objetivo"
    elif delta_minutes <= 10:
        status_label = "ligeramente por detrás"
    else:
        status_label = "claramente por detrás"

    return {
        "goal": _format_goal_time(goal_time),
        "prediction": predicted_time,
        "delta_minutes": delta_minutes,
        "status_label": status_label,
    }


def _build_race_context(
    race_date: str | None,
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    if not race_date:
        return None

    raw = str(race_date).strip()
    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.fromisoformat(f"{raw}T00:00:00+00:00")
        except ValueError:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    today = (as_of or datetime.now(timezone.utc)).date()
    target_day = dt.date()
    days_to_race = (target_day - today).days

    return {
        "race_date": raw,
        "days_to_race": days_to_race,
        "is_pre_race_window": 0 <= days_to_race <= 7,
    }


def _build_prediction_trend(
    runs: list[dict[str, Any]],
    user: dict[str, Any],
    objective_override: str | None,
    as_of: datetime | None,
) -> list[dict[str, Any]]:
    reference = as_of or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    else:
        reference = reference.astimezone(timezone.utc)

    last_closed_week_end = (
        reference - timedelta(days=reference.weekday() + 1)
    ).replace(hour=23, minute=59, second=59, microsecond=0)

    points: list[dict[str, Any]] = []

    for weeks_back in range(4, -1, -1):
        point_as_of = last_closed_week_end - timedelta(weeks=weeks_back)
        snapshot = build_analysis_payload_from_runs(
            runs=runs,
            user=user,
            objective_override=objective_override,
            as_of=point_as_of,
            include_prediction_trend=False,
        )
        point_prediction = snapshot.get("prediction") or {}
        point_training = snapshot.get("training") or {}
        point_quality_blocks = snapshot.get("quality_blocks") or []
        has_signal = bool(point_quality_blocks) or any(
            _safe_float(point_training.get(key)) > 0
            for key in ("km_last_7_days", "weekly_average_km", "long_run_km")
        )

        predicted_time = point_prediction.get("predicted_time") if has_signal else None
        minutes_vs_goal = (
            _safe_int(point_prediction.get("minutes_vs_goal"))
            if has_signal and point_prediction.get("minutes_vs_goal") is not None
            else None
        )

        points.append(
            {
                "label": point_as_of.strftime("%d-%m"),
                "predicted_time": predicted_time,
                "minutes_vs_goal": minutes_vs_goal,
            }
        )

    return points


def _build_half_marathon_readout(
    training: dict[str, Any],
    fatigue: dict[str, Any],
    quality_blocks: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    weekly = _safe_float(training.get("weekly_average_km"))
    km7 = _safe_float(training.get("km_last_7_days"))
    long_run = _safe_float(training.get("long_run_km"))
    fatigue_label = str(fatigue.get("label") or "")
    spec_km = sum(_safe_float(block.get("km")) for block in quality_blocks)
    block_count = len(quality_blocks)
    has_signal = weekly >= 24 or km7 >= 18 or long_run >= 14 or spec_km >= 6 or block_count >= 1

    if not has_signal:
        return (
            {
                "goal": "Media maratón",
                "prediction": None,
                "delta_minutes": None,
                "status_label": "todavía falta señal útil para leer tu media",
            },
            {
                "headline": "Aún no se deja leer tu media.",
                "subline": "Todavía falta continuidad y algo más de trabajo útil para leer tu nivel con credibilidad.",
                "action": "Suma semanas estables y mete una sesión útil antes de volver a evaluarlo.",
                "chip": "LECTURA INICIAL",
            },
        )

    if fatigue_label == "Alta":
        return (
            {
                "goal": "Media maratón",
                "prediction": None,
                "delta_minutes": None,
                "status_label": "señal de media tapada por fatiga",
            },
            {
                "headline": "Tu nivel para media está, pero hoy llega tapado.",
                "subline": "La carga reciente pesa más que la lectura fina de tu nivel.",
                "action": "Recorta ruido esta semana y vuelve a mirar la señal con más frescura.",
                "chip": "FATIGA ALTA",
            },
        )

    if weekly < 28 or long_run < 15 or (spec_km < 8 and block_count == 0):
        return (
            {
                "goal": "Media maratón",
                "prediction": None,
                "delta_minutes": None,
                "status_label": "tu media todavía no se sostiene con solidez",
            },
            {
                "headline": "Tu nivel ahora mismo no sostiene una media sólida.",
                "subline": "Te falta combinar mejor continuidad, tirada larga y algo de trabajo útil a ritmo.",
                "action": "Antes de apretar objetivo, consolida semanas más estables y una tirada larga más seria.",
                "chip": "POR DETRÁS",
            },
        )

    if weekly < 38 or long_run < 18 or spec_km < 12 or block_count < 2:
        return (
            {
                "goal": "Media maratón",
                "prediction": None,
                "delta_minutes": None,
                "status_label": "media maratón cerca, pero aún sin demasiado margen",
            },
            {
                "headline": "Tu nivel ahora mismo está cerca de una media.",
                "subline": "Ya hay base útil, pero todavía falta más continuidad para sostenerla con margen.",
                "action": "Repite semanas buenas y protege una tirada larga sólida con un bloque útil.",
                "chip": "CERCA",
            },
        )

    return (
        {
            "goal": "Media maratón",
            "prediction": None,
            "delta_minutes": None,
            "status_label": "lectura coherente con una media maratón",
        },
        {
            "headline": "Tu nivel ahora mismo encaja con una media.",
            "subline": "Ya tienes una base que se parece a una media creíble, siempre que sigas sosteniéndola.",
            "action": "No busques épica: mantén continuidad y llega con frescura.",
            "chip": "EN OBJETIVO",
        },
    )


def _build_half_marathon_coach(
    training: dict[str, Any],
    fatigue: dict[str, Any],
    quality_blocks: list[dict[str, Any]],
) -> dict[str, str]:
    weekly = _safe_float(training.get("weekly_average_km"))
    km7 = _safe_float(training.get("km_last_7_days"))
    long_run = _safe_float(training.get("long_run_km"))
    fatigue_label = str(fatigue.get("label") or "")
    spec_km = sum(_safe_float(block.get("km")) for block in quality_blocks)
    block_count = len(quality_blocks)
    has_signal = weekly >= 24 or km7 >= 18 or long_run >= 14 or spec_km >= 6 or block_count >= 1

    if not has_signal:
        return {
            "positive": "Todavía no hay suficiente señal útil para leer bien tu nivel de media.",
            "limiter": "Falta continuidad y algo más de trabajo útil para que la lectura gane credibilidad.",
            "next_focus": "Encadena semanas estables y mete una sesión útil antes de volver a evaluarlo.",
            "summary": "Ahora mismo todavía falta base real para leer tu media maratón con claridad.",
        }

    if fatigue_label == "Alta":
        return {
            "positive": "La base reciente permite intuir nivel de media.",
            "limiter": "La fatiga reciente tapa parte de la señal buena que sí tienes.",
            "next_focus": "Baja ruido esta semana y busca llegar más fresco a la siguiente sesión útil.",
            "summary": "La lectura de media existe, pero hoy queda distorsionada por la fatiga.",
        }

    if weekly < 28 or long_run < 15 or (spec_km < 8 and block_count == 0):
        return {
            "positive": "Ya aparece algo de base para empezar a leer este objetivo.",
            "limiter": "Todavía falta combinar mejor continuidad, tirada larga y trabajo útil a ritmo.",
            "next_focus": "Consolida semanas más estables y una tirada larga más seria antes de apretar el objetivo.",
            "summary": "Tu base actual todavía no sostiene una media maratón con suficiente solidez.",
        }

    if weekly < 38 or long_run < 18 or spec_km < 12 or block_count < 2:
        return {
            "positive": "Ya hay señales útiles que empiezan a parecerse a una media creíble.",
            "limiter": "Todavía falta algo más de continuidad para sostener ese nivel con margen.",
            "next_focus": "Repite semanas buenas y protege una tirada larga sólida con un bloque útil.",
            "summary": "La lectura de media está cerca, pero todavía no sobra margen.",
        }

    return {
        "positive": "Ya hay base suficiente para leer una media maratón con credibilidad.",
        "limiter": "El riesgo ahora es meter ruido y perder continuidad más que falta de base.",
        "next_focus": "Mantén continuidad, no añadas épica innecesaria y llega fresco a las sesiones útiles.",
        "summary": "Tu entrenamiento ya se parece al de una media maratón bien sostenida.",
    }


def build_analysis_payload_from_runs(
    runs: list[dict[str, Any]],
    user: dict[str, Any] | None = None,
    objective_override: str | None = None,
    as_of: datetime | None = None,
    include_prediction_trend: bool = True,
) -> dict[str, Any]:
    user = user or {}
    if as_of is not None:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        else:
            as_of = as_of.astimezone(timezone.utc)

    goal_time = user.get("goal_time") or "3:30"
    objective_raw = objective_override or user.get("objective") or "Maratón"
    objective = _normalize_objective(objective_raw)
    race_date = user.get("race_date")
    race_context = _build_race_context(race_date, as_of=as_of)

    quality_blocks = detect_quality_blocks(runs, as_of=as_of)
    training_tuple = compute_training(runs, as_of=as_of)
    training = {
        "km_last_7_days": training_tuple[0],
        "km_last_7": training_tuple[0],
        "weekly_average_km": training_tuple[1],
        "avg_week_km": training_tuple[1],
        "long_run_km": training_tuple[2],
    }
    fatigue = compute_fatigue_signal(runs, as_of=as_of)
    prediction = compute_prediction(
        training=training,
        fatigue=fatigue,
        quality_blocks=quality_blocks,
        goal_time=goal_time,
        race_context=race_context,
        objective=objective,
    )
    last_key_session = build_last_key_session(runs, quality_blocks)
    coach = build_coach(
        prediction=prediction,
        training=training,
        fatigue=fatigue,
        last_key_session=last_key_session,
        quality_blocks=quality_blocks,
    )

    if objective in {"10k", "5k"}:
        coach = {
            **coach,
            "positive": "Ya hay señal reciente de ritmo para empezar a leer este objetivo corto.",
            "limiter": "Todavía falta más ritmo útil cerca del objetivo o más repetición de calidad.",
            "next_focus": "Repite bloques rápidos con continuidad antes de subir más carga.",
            "summary": "Para este objetivo corto, la lectura se apoya en tu ritmo reciente y, como referencia secundaria, en media maratón.",
        }

    status = _build_status_block(goal_time=goal_time, prediction=prediction)

    if objective == "half_marathon":
        prediction = {
            **prediction,
            "predicted_time": None,
            "range_low": None,
            "range_high": None,
            "minutes_vs_goal": None,
            "message": "Lectura de media maratón activa, sin tiempo exacto por ahora.",
        }
        status, one_line = _build_half_marathon_readout(
            training=training,
            fatigue=fatigue,
            quality_blocks=quality_blocks,
        )
        coach = _build_half_marathon_coach(
            training=training,
            fatigue=fatigue,
            quality_blocks=quality_blocks,
        )
    elif objective in {"10k", "5k"}:
        prediction = {
            **prediction,
            "predicted_time": None,
            "range_low": None,
            "range_high": None,
            "minutes_vs_goal": None,
            "message": f'Predicción específica de {_objective_display_name(objective).lower()} aún no disponible',
        }
        status = {
            "goal": _objective_display_name(objective),
            "prediction": None,
            "delta_minutes": None,
            "status_label": "sin predicción específica todavía",
        }
        one_line = build_one_line_short_goal(
            objective=objective,
            goal_time=goal_time,
            quality_blocks=quality_blocks,
        )
    else:
        one_line = build_one_line(
            prediction=prediction,
            training=training,
            fatigue=fatigue,
            quality_blocks=quality_blocks,
            goal_time=goal_time,
            race_context=race_context,
        )

    if objective in {"10k", "5k"}:
        short_goal_evidence = build_short_goal_evidence(
            objective=objective,
            goal_time=goal_time,
            quality_blocks=quality_blocks,
        )
    else:
        short_goal_evidence = None

    if objective in {"10k", "5k"}:
        short_goal_product_evidence = build_short_goal_product_evidence(short_goal_evidence)
    else:
        short_goal_product_evidence = []

    prediction_trend = (
        _build_prediction_trend(
            runs=runs,
            user=user,
            objective_override=objective_override,
            as_of=as_of,
        )
        if include_prediction_trend and objective == "marathon"
        else []
    )

    return {
        "objective": objective,
        "goal_time": goal_time,
        "race_date": race_date,
        "prediction": prediction,
        "training": training,
        "fatigue": fatigue,
        "coach": coach,
        "quality_blocks": quality_blocks,
        "last_key_session": last_key_session,
        "status": status,
        "one_line": one_line,
        "short_goal_evidence": short_goal_evidence,
        "short_goal_product_evidence": short_goal_product_evidence,
        "prediction_trend": prediction_trend,
    }


def build_one_line_short_goal(
    objective: str,
    goal_time: str,
    quality_blocks: list[dict],
) -> dict[str, str]:

    def pace_to_sec(p):
        if p is None:
            return None
        try:
            parts = str(p).split(":")
            if len(parts) == 2:
                m, s = parts
                return int(m) * 60 + int(s)
            return None
        except:
            return None

    def goal_time_to_pace_sec(goal):
        if goal is None:
            return None
        try:
            parts = str(goal).split(":")
            if len(parts) == 3:
                h, m, s = parts
                total_sec = int(h) * 3600 + int(m) * 60 + int(s)
            elif len(parts) == 2:
                m, s = parts
                total_sec = int(m) * 60 + int(s)
            else:
                return None
            distance_km = 5 if objective == "5k" else 10
            return total_sec / distance_km
        except:
            return None

    goal_sec = goal_time_to_pace_sec(goal_time)
    max_km = 6 if objective == "5k" else 12

    best_pace = None
    for b in quality_blocks:
        try:
            km_value = float(b.get("km"))
        except:
            km_value = None
        if km_value is None or km_value > max_km:
            continue
        pace = b.get("avg_pace")
        sec = pace_to_sec(pace)
        if sec is not None:
            if best_pace is None or sec < best_pace:
                best_pace = sec

    if best_pace is None or goal_sec is None:
        return {
            "headline": "Aún no se puede leer tu nivel.",
            "subline": "Falta señal de ritmo útil.",
            "action": "Introduce sesiones con ritmo.",
            "chip": "LECTURA INICIAL",
        }

    diff = best_pace - goal_sec

    if diff > 15:
        return {
            "headline": "Así, no te va a dar.",
            "subline": "Tu ritmo actual está lejos de lo que exige ese objetivo.",
            "action": "O ajustas objetivo, o subes nivel.",
            "chip": "POR DETRÁS",
        }

    if diff > 5:
        return {
            "headline": "Vas cerca, pero aún no estás ahí.",
            "subline": "Tienes ritmo, pero no lo sostienes lo suficiente.",
            "action": "Más continuidad en ritmos altos.",
            "chip": "CERCA",
        }

    if diff >= -5:
        return {
            "headline": "Estás en nivel para ese objetivo.",
            "subline": "Lo que haces encaja con lo que quieres correr.",
            "action": "Mantén la estructura.",
            "chip": "EN OBJETIVO",
        }

    return {
        "headline": "Tu nivel actual está por encima de tu objetivo.",
        "subline": "Estás entrenando para algo más rápido.",
        "action": "O lo mantienes fácil… o subes el objetivo.",
        "chip": "POR DELANTE",
    }



def build_short_goal_evidence(
    objective: str,
    goal_time: str,
    quality_blocks: list[dict[str, Any]],
) -> dict[str, Any]:

    def pace_to_sec(p):
        if p is None:
            return None
        try:
            parts = str(p).split(":")
            if len(parts) == 2:
                m, s = parts
                return int(m) * 60 + int(s)
            return None
        except:
            return None

    def goal_time_to_pace(goal):
        if goal is None:
            return None
        try:
            parts = str(goal).split(":")
            if len(parts) == 3:
                h, m, s = parts
                total_sec = int(h) * 3600 + int(m) * 60 + int(s)
            elif len(parts) == 2:
                m, s = parts
                total_sec = int(m) * 60 + int(s)
            else:
                return None
            distance_km = 5 if objective == "5k" else 10
            sec = round(total_sec / distance_km)
            return f"{sec // 60}:{str(sec % 60).zfill(2)}"
        except:
            return None

    goal_pace = goal_time_to_pace(goal_time)
    max_km = 6 if objective == "5k" else 12

    filtered_blocks = []
    for b in quality_blocks:
        km = b.get("km")
        try:
            km_value = float(km)
        except:
            km_value = None

        if km_value is None:
            continue

        if km_value <= max_km:
            filtered_blocks.append(b)

    best_block = None
    best_sec = None

    for b in filtered_blocks:
        sec = pace_to_sec(b.get("avg_pace"))
        if sec is not None and (best_sec is None or sec < best_sec):
            best_sec = sec
            best_block = b

    recent_count = len(filtered_blocks)

    return {
        "goal_pace": goal_pace,
        "best_recent_pace": best_block.get("avg_pace") if best_block else None,
        "best_recent_km": best_block.get("km") if best_block else None,
        "recent_quality_count": recent_count,
    }



def build_short_goal_product_evidence(
    short_goal_evidence: dict[str, Any] | None,
) -> list[str]:
    if not short_goal_evidence:
        return []

    lines = []

    goal_pace = short_goal_evidence.get("goal_pace")
    best_recent_pace = short_goal_evidence.get("best_recent_pace")
    best_recent_km = short_goal_evidence.get("best_recent_km")
    recent_quality_count = short_goal_evidence.get("recent_quality_count")

    if goal_pace:
        lines.append(f"Tu objetivo exige ~{goal_pace}/km")

    if best_recent_pace and best_recent_km:
        lines.append(f"Tu mejor bloque reciente útil está en ~{best_recent_pace}/km durante {best_recent_km} km")

    if recent_quality_count is not None:
        lines.append(f"Has hecho {recent_quality_count} sesiones útiles recientes")

    return lines
