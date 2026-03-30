from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any


# =========================
# HELPERS
# =========================

DAYS = {
    "lunes": "lunes",
    "martes": "martes",
    "miércoles": "miércoles",
    "miercoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sábado": "sábado",
    "sabado": "sábado",
    "domingo": "domingo",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _today_utc() -> date:
    return datetime.utcnow().date()


def _days_to_race(race_date: date | None) -> int | None:
    if race_date is None:
        return None
    return (race_date - _today_utc()).days


def _classify_phase(days_to_race: int | None) -> str:
    if days_to_race is None:
        return "normal"
    if days_to_race <= 7:
        return "race_week"
    if days_to_race <= 14:
        return "taper"
    if days_to_race <= 35:
        return "peak"
    return "normal"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_quality_text(text: str) -> bool:
    txt = _clean_text(text)

    if any(x in txt for x in ["series", "tempo", "interval"]):
        return True

    if any(x in txt for x in ["ritmo controlado", "ritmo objetivo", "ritmo maratón", "ritmo maraton", "cambios de ritmo"]):
        return True

    has_rep_pattern = bool(re.search(r"\b\d+\s*x\s*\d+[\.,]?\d*\s*(km|m)\b", txt))
    has_recovery = (" rec " in f" {txt} ") or (" recuperación" in txt) or (" recuperacion" in txt)

    return has_rep_pattern or (has_recovery and (" km " in f" {txt} " or " m " in f" {txt} "))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_goal_time_to_minutes(goal_time: str | None) -> float | None:
    if not goal_time:
        return None

    raw = str(goal_time).strip()
    if not raw:
        return None

    parts = raw.split(":")
    try:
        if len(parts) == 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            return float(hours * 60 + minutes)
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return float(hours * 60 + minutes + seconds / 60.0)
    except ValueError:
        return None

    return None


def _normalize_objective(objective: str | None) -> str:
    raw = str(objective or "").strip().lower()

    if "media" in raw or "half" in raw:
        return "half_marathon"
    if "10" in raw:
        return "10k"
    if "5" in raw:
        return "5k"
    return "marathon"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)

    return result


# =========================
# EXTRAER ESTRUCTURA REAL
# =========================

def _extract_day_structure(plan_text: str) -> dict[str, str]:
    lines = plan_text.lower().splitlines()
    day_map: dict[str, str] = {}

    current_day = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        for key in DAYS:
            if key in line:
                current_day = DAYS[key]
                break

        if current_day:
            day_map[current_day] = line

    return day_map


# =========================
# DETECTAR ERRORES DE PLAN
# =========================

def _detect_structure_issues(day_map: dict[str, str]) -> list[str]:
    issues = []

    ordered_days = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo",
    ]

    prev_intensity = None

    for day in ordered_days:
        text = day_map.get(day, "")

        if not text:
            continue

        is_quality = _is_quality_text(text)
        is_long = "tirada larga" in text

        intensity = "none"
        if is_quality:
            intensity = "quality"
        elif is_long:
            intensity = "long"

        if prev_intensity == "quality" and intensity == "long":
            issues.append("Estás juntando calidad y tirada larga sin suficiente recuperación.")

        prev_intensity = intensity

    return issues


# =========================
# CLASIFICAR DÍAS
# =========================

def _classify_days(day_map: dict[str, str]) -> dict[str, str]:
    result = {}

    for day, text in day_map.items():
        if "tirada larga" in text:
            result[day] = "long"
        elif _is_quality_text(text):
            result[day] = "quality"
        elif "descanso" in text:
            result[day] = "rest"
        else:
            result[day] = "easy"

    return result


# =========================
# COHERENCIA CON OBJETIVO
# =========================

def _evaluate_objective_coherence(
    day_map: dict[str, str],
    objective: str,
    goal_time: str | None,
    fatigue_label: str,
) -> tuple[str | None, str | None]:
    """
    Devuelve:
    - objective_reason: lo que pesa respecto al objetivo
    - objective_decision: qué haría ahora respecto al objetivo
    """
    normalized_objective = _normalize_objective(objective)
    goal_minutes = _parse_goal_time_to_minutes(goal_time)

    texts = list(day_map.values())
    has_long_run = any("tirada larga" in t for t in texts)
    has_quality = any(_is_quality_text(t) for t in texts)
    has_fast_finish_long_run = any("2 km finales" in t or "finales" in t for t in texts)
    quality_count = sum(
        1 for t in texts if _is_quality_text(t)
    )

    if normalized_objective == "marathon":
        if goal_minutes is not None and goal_minutes <= 210:
            if fatigue_label == "alta":
                return (
                    "La semana tiene sentido, pero ahora mismo protege más de lo que empuja el objetivo.",
                    "Mantendría la estructura, pero esta semana tocaría asimilar antes de volver a meter especificidad real para el 3:30.",
                )

            if not has_long_run:
                return (
                    "Para un objetivo exigente de maratón falta el estímulo de resistencia más importante.",
                    "Reintroduciría una tirada larga útil para que la semana vuelva a empujar el objetivo.",
                )

            if not has_quality:
                return (
                    "La semana se queda demasiado plana para un objetivo exigente de maratón.",
                    "Añadiría un estímulo de calidad o un bloque específico para que la semana no se quede solo en mantenimiento.",
                )

            if quality_count == 1 and not has_fast_finish_long_run:
                return (
                    "La semana tiene lógica, pero la especificidad sigue siendo algo conservadora para un objetivo tan exigente.",
                    "Cuando la fatiga lo permita, metería más trabajo específico dentro de la tirada larga o de la sesión clave.",
                )

        if has_long_run and has_quality:
            return (
                "La semana sí toca las dos palancas que más pesan en maratón: resistencia y calidad.",
                "Mantendría esta línea, ajustando agresividad según la fatiga.",
            )

        if not has_long_run:
            return (
                "La semana pierde parte de su sentido maratón si desaparece la tirada larga.",
                "Reforzaría la resistencia con una tirada larga útil.",
            )

        if not has_quality:
            return (
                "La semana queda demasiado plana para seguir empujando el objetivo de maratón.",
                "Añadiría un estímulo de calidad controlada.",
            )

    if normalized_objective == "half_marathon":
        if not has_quality:
            return (
                "La semana se queda algo corta de ritmo útil para media maratón.",
                "Metería un estímulo más específico de ritmo controlado.",
            )
        return (
            "La semana tiene una base razonable para media maratón.",
            "Mantendría la estructura, vigilando que no se convierta en una semana demasiado larga y lenta.",
        )

    if normalized_objective == "10k":
        if quality_count == 0:
            return (
                "La semana es demasiado plana para 10K.",
                "Introduciría una sesión de calidad clara para que el objetivo no quede desatendido.",
            )
        return (
            "La semana tiene al menos una base razonable para 10K.",
            "Mantendría calidad útil y evitaría convertirla en una mini semana de maratón.",
        )

    if normalized_objective == "5k":
        if quality_count == 0:
            return (
                "La semana es demasiado conservadora para 5K.",
                "Añadiría un estímulo breve de calidad para no perder chispa.",
            )
        return (
            "La semana toca algo de calidad, que es lo mínimo para 5K.",
            "Mantendría la chispa sin cargar la semana como si fuera una preparación más larga.",
        )

    return None, None


# =========================
# AJUSTE CON DECISIÓN REAL
# =========================

def _adjust_week(day_map: dict[str, str], fatigue_label: str) -> dict[str, str]:
    day_types = _classify_days(day_map)
    adjusted = {}

    quality_days = [d for d, t in day_types.items() if t == "quality"]

    keep_quality = quality_days[:1] if fatigue_label == "alta" else quality_days

    for day in day_map:
        t = day_types.get(day)

        if t == "long":
            if fatigue_label == "alta":
                adjusted[day] = "Tirada larga más contenida, sin acabar fatigado."
            else:
                adjusted[day] = "Tirada larga controlada."
            continue

        if t == "quality":
            if day in keep_quality:
                adjusted[day] = "Sesión de calidad moderada, sin vaciarte."
            else:
                adjusted[day] = "Rodaje controlado (se elimina carga de calidad)."
            continue

        if t == "rest":
            adjusted[day] = "Descanso total."
            continue

        if fatigue_label == "alta":
            adjusted[day] = "Rodaje muy suave."
        else:
            adjusted[day] = "Rodaje suave o controlado."

    return adjusted


# =========================
# LECTURA FINAL DEL ENTRENADOR
# =========================

def _build_coach_readout(
    day_map: dict[str, str],
    objective: str,
    fatigue_label: str,
    issues: list[str],
    objective_reason: str | None,
    objective_decision: str | None,
) -> dict[str, Any]:
    texts = list(day_map.values())
    has_long_run = any("tirada larga" in t for t in texts)
    has_quality = any(_is_quality_text(t) for t in texts)

    dominant_issue = "on_track"

    if fatigue_label == "alta":
        dominant_issue = "fatigue"
    elif issues:
        dominant_issue = "structure"
    elif objective_reason and any(
        marker in objective_reason.lower()
        for marker in [
            "falta",
            "demasiado plana",
            "algo corta",
            "conservadora",
            "pierde parte de su sentido",
        ]
    ):
        dominant_issue = "specificity"

    estado = ""
    foco = ""
    decision = ""
    actions: list[str] = []
    positives: list[str] = []
    reasons: list[str] = []
    proposed_week_summary = ""

    if dominant_issue == "fatigue":
        estado = "Estás acumulando fatiga y ahora mismo no estás absorbiendo igual la carga."
        foco = "Ahora mismo manda la fatiga."
        decision = "Esta semana no toca empujar, toca asimilar."

        actions = [
            "Mantén una sola sesión de calidad.",
            "Quita la segunda sesión exigente.",
            "Mantén la tirada larga, pero más controlada.",
        ]

        if has_long_run or has_quality:
            positives.append("La semana tiene una base útil, pero ahora mismo eso no es lo que manda.")

        reasons = [
            "La carga acumulada empieza a pesar más que la estructura del papel.",
        ]

        if objective_reason:
            reasons.append("El problema esta semana no es el objetivo, es que ahora toca proteger mejor la asimilación.")

        proposed_week_summary = "Semana de descarga relativa: mantener la base y bajar la exigencia."

    elif dominant_issue == "structure":
        estado = "La semana tiene trabajo útil, pero está demasiado apretada."
        foco = "Ahora mismo manda cómo está repartida la carga."
        decision = "No necesitas meter más trabajo; necesitas ordenarlo mejor."

        actions = [
            "Separa mejor la calidad de la tirada larga.",
            "Mete un día realmente suave entre los dos bloques que más cargan.",
            "Mantén el volumen solo si la semana respira mejor.",
        ]

        if objective_reason and ("sí toca" in objective_reason.lower() or "base razonable" in objective_reason.lower()):
            positives.append("La semana sí toca cosas útiles para el objetivo.")

        reasons = issues[:2] if issues else ["La carga importante está demasiado junta."]
        proposed_week_summary = "Semana a reorganizar: mantener lo útil, pero mejor repartido."

    elif dominant_issue == "specificity":
        estado = "La semana se queda corta para empujar bien el objetivo."
        foco = "Ahora mismo falta algo de trabajo realmente útil para la prueba."
        decision = "Antes que sumar más días, toca afinar mejor la semana."

        if not has_long_run and _normalize_objective(objective) == "marathon":
            actions.append("Recupera una tirada larga con sentido dentro de la semana.")
        if not has_quality:
            actions.append("Mete una sesión de calidad clara y controlada.")
        if len(actions) < 3:
            actions.append("Mantén el resto simple para que lo importante de verdad destaque.")

        positives = []
        reasons = [objective_reason] if objective_reason else ["La semana no está empujando lo suficiente hacia el objetivo."]
        proposed_week_summary = "Semana a afinar: menos plano y más orientada al objetivo."

    else:
        estado = "La semana está bien orientada y puedes seguir avanzando."
        foco = "Ahora mismo lo importante es mantener el rumbo sin meter ruido."
        decision = "Sí puedes apretar, pero con control."

        actions = [
            "Mantén la sesión de calidad principal.",
            "Sostén la tirada larga si la estás tolerando bien.",
            "Haz de verdad suaves los días suaves.",
        ]

        positives = []
        if has_long_run:
            positives.append("La semana incluye tirada larga, que sigue siendo una pieza importante.")
        if has_quality:
            positives.append("La semana mantiene una sesión de calidad útil.")
        if objective_reason and ("sí toca" in objective_reason.lower() or "base razonable" in objective_reason.lower()):
            positives.append(objective_reason)

        positives = positives[:2]
        reasons = ["No hay una señal clara que obligue a frenar o a reorganizar la semana."]
        proposed_week_summary = "Semana para seguir en línea: mantener la lógica y no complicarla."

    positives = _dedupe_keep_order(positives)[:2]
    reasons = _dedupe_keep_order(reasons)[:2]
    actions = _dedupe_keep_order(actions)[:3]

    return {
        "dominant_issue": dominant_issue,
        "estado": estado,
        "foco": foco,
        "decision": decision,
        "actions": actions,
        "summary": estado,
        "positives": positives,
        "reasons": reasons,
        "recommended_changes": actions,
        "proposed_week_summary": proposed_week_summary,
    }


# =========================
# MAIN
# =========================

def validate_plan(
    plan_text: str,
    objective: str,
    training: dict[str, Any] | None = None,
    fatigue: dict[str, Any] | None = None,
    race_date: str | None = None,
) -> dict[str, Any]:
    training = training or {}
    fatigue = fatigue or {}

    fatigue_label = str(fatigue.get("label", "baja")).lower().strip()
    goal_time = training.get("goal_time") or None

    day_map = _extract_day_structure(plan_text)

    if not day_map:
        return {
            "validation_status": "warning",
            "summary": "No se ha podido interpretar la semana.",
            "positives": [],
            "reasons": ["El formato del plan no es claro."],
            "recommended_changes": [],
            "proposed_week": {},
            "proposed_week_summary": "No se puede evaluar una semana que no se ha entendido bien.",
            "estado": "No se ha podido interpretar la semana.",
            "foco": "Falta claridad en el texto del plan.",
            "decision": "Antes de ajustar nada, necesito una semana escrita de forma más clara.",
            "actions": ["Escribe cada día en una línea separada para poder leer bien la estructura."],
        }

    issues = _detect_structure_issues(day_map)
    objective_reason, objective_decision = _evaluate_objective_coherence(
        day_map=day_map,
        objective=objective,
        goal_time=goal_time,
        fatigue_label=fatigue_label,
    )

    coach_readout = _build_coach_readout(
        day_map=day_map,
        objective=objective,
        fatigue_label=fatigue_label,
        issues=issues,
        objective_reason=objective_reason,
        objective_decision=objective_decision,
    )

    adjusted_week = _adjust_week(day_map, fatigue_label)

    notes: list[str] = []

    if coach_readout["dominant_issue"] == "fatigue":
        notes.append("Se mantiene la estructura general, pero esta semana baja la exigencia.")
        notes.append("El objetivo ahora es asimilar mejor antes de volver a empujar.")
    elif coach_readout["dominant_issue"] == "structure":
        notes.append("Se mantiene la base de la semana, pero mejor repartida.")
        notes.append("El objetivo ahora es que la calidad y la tirada larga no se estorben.")
    elif coach_readout["dominant_issue"] == "specificity":
        notes.append("Se afina la semana para que empuje mejor el objetivo.")
        if objective_decision:
            notes.append(objective_decision)
    else:
        notes.append("Se mantiene la lógica general del plan.")
        if objective_decision:
            notes.append(objective_decision)
        else:
            notes.append("No hace falta complicar una semana que ya va bien orientada.")

    proposed_week = {
        **adjusted_week,
        "notas": _dedupe_keep_order(notes),
    }

    return {
        "validation_status": "ok",
        "summary": coach_readout["summary"],
        "positives": coach_readout["positives"],
        "reasons": coach_readout["reasons"],
        "recommended_changes": coach_readout["recommended_changes"],
        "proposed_week": proposed_week,
        "proposed_week_summary": coach_readout["proposed_week_summary"],
        "estado": coach_readout["estado"],
        "foco": coach_readout["foco"],
        "decision": coach_readout["decision"],
        "actions": coach_readout["actions"],
    }