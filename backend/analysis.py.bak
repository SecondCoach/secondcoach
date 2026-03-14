from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_goal_time_to_seconds(goal_time: str) -> int:
    """
    Acepta formatos:
    - "3:30"    -> 3h 30m
    - "3:30:00" -> 3h 30m 0s
    - "210"     -> 210 minutos
    """
    if not goal_time:
        raise ValueError("goal_time vacío")

    raw = str(goal_time).strip()

    if raw.isdigit():
        return int(raw) * 60

    parts = raw.split(":")
    if len(parts) == 2:
        hours = int(parts[0])
        minutes = int(parts[1])
        return hours * 3600 + minutes * 60

    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds

    raise ValueError(f"Formato de goal_time no válido: {goal_time}")


def _goal_pace_sec_per_km(goal_time: str, race_km: float = 42.195) -> float:
    total_seconds = _parse_goal_time_to_seconds(goal_time)
    return total_seconds / race_km


def _goal_pace_window(goal_time: str) -> tuple[float, float]:
    """
    Ventana base:
    - más rápido: MP - 20s/km
    - más lento : MP + 10s/km
    """
    mp_sec = _goal_pace_sec_per_km(goal_time)
    min_sec = max(1.0, mp_sec - 20.0)
    max_sec = mp_sec + 10.0
    return min_sec, max_sec


def _goal_pace_continuation_window(goal_time: str) -> tuple[float, float]:
    """
    Ventana de continuidad cuando el bloque YA ha empezado:
    - más rápido: MP - 45s/km
    - más lento : MP + 15s/km
    """
    mp_sec = _goal_pace_sec_per_km(goal_time)
    min_sec = max(1.0, mp_sec - 45.0)
    max_sec = mp_sec + 15.0
    return min_sec, max_sec


def _pace_from_unit(unit: dict[str, Any]) -> float | None:
    """
    Calcula el ritmo en sec/km de un split o lap.

    Prioridad:
    1) average_speed (m/s)
    2) moving_time / distance
    3) elapsed_time / distance
    """
    distance_m = unit.get("distance") or 0
    if not distance_m or distance_m <= 0:
        return None

    avg_speed = unit.get("average_speed")
    if avg_speed and avg_speed > 0:
        return 1000.0 / float(avg_speed)

    moving_time = unit.get("moving_time")
    if moving_time and moving_time > 0:
        return float(moving_time) / (float(distance_m) / 1000.0)

    elapsed_time = unit.get("elapsed_time")
    if elapsed_time and elapsed_time > 0:
        return float(elapsed_time) / (float(distance_m) / 1000.0)

    return None


def _unit_distance_km(unit: dict[str, Any]) -> float:
    distance_m = unit.get("distance") or 0
    return float(distance_m) / 1000.0 if distance_m else 0.0


def _extract_units(activity: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """
    Devuelve una lista de unidades homogéneas y la fuente usada:
    - splits_metric
    - laps
    """
    splits = activity.get("splits_metric")
    if isinstance(splits, list) and splits:
        return splits, "splits_metric"

    laps = activity.get("laps")
    if isinstance(laps, list) and laps:
        return laps, "laps"

    return [], None


def _round1(value: float) -> float:
    return round(value + 1e-9, 1)


def _is_in_window(pace_sec: float | None, window: tuple[float, float]) -> bool:
    if pace_sec is None:
        return False
    min_sec, max_sec = window
    return min_sec <= pace_sec <= max_sec


def compute_training(runs: list[dict[str, Any]]) -> tuple[float, float, float]:
    """
    Devuelve:
    - km últimos 7 días
    - media semanal últimas 4 semanas (28 días)
    - tirada larga máxima
    """
    now = datetime.now(timezone.utc)
    start_7 = now - timedelta(days=7)
    start_28 = now - timedelta(days=28)

    km_last_7 = 0.0
    km_last_28 = 0.0
    long_run_km = 0.0

    for run in runs:
        distance_km = float(run.get("distance", 0)) / 1000.0
        if distance_km > long_run_km:
            long_run_km = distance_km

        run_dt = _parse_datetime(run.get("start_date"))
        if not run_dt:
            continue

        if run_dt >= start_7:
            km_last_7 += distance_km

        if run_dt >= start_28:
            km_last_28 += distance_km

    avg_week_km = km_last_28 / 4.0

    return _round1(km_last_7), _round1(avg_week_km), _round1(long_run_km)


def _daily_km_last_7(runs: list[dict[str, Any]]) -> list[float]:
    now = datetime.now(timezone.utc)
    start_day = (now - timedelta(days=6)).date()
    totals: dict[Any, float] = {}

    for i in range(7):
        day = start_day + timedelta(days=i)
        totals[day] = 0.0

    for run in runs:
        run_dt = _parse_datetime(run.get("start_date"))
        if not run_dt:
            continue

        day = run_dt.astimezone(timezone.utc).date()
        if day not in totals:
            continue

        totals[day] += float(run.get("distance", 0) or 0) / 1000.0

    return [totals[day] for day in sorted(totals.keys())]


def compute_fatigue_signal(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    MVP robusto:
    - load_ratio_7d_28d = km últimos 7d / media semanal 28d
    - monotony = media diaria 7d / desviación típica diaria 7d
    - strain = km_7d * monotony

    Semáforo:
    - red: mucha carga reciente o mucha monotonía
    - yellow: vigilancia
    - green: carga controlada
    """
    km_7, avg_week, _ = compute_training(runs)
    daily_km = _daily_km_last_7(runs)

    avg_daily = mean(daily_km) if daily_km else 0.0
    std_daily = pstdev(daily_km) if len(daily_km) > 1 else 0.0

    load_ratio = (km_7 / avg_week) if avg_week > 0 else 0.0
    monotony = (avg_daily / std_daily) if std_daily > 0 else 0.0
    strain = km_7 * monotony

    load_ratio = round(load_ratio, 2)
    monotony = round(monotony, 2)
    strain = round(strain, 1)

    if load_ratio >= 1.35 or monotony >= 2.0 or strain >= 90:
        status = "red"
        label = "Fatiga alta"
        message = "Tu carga reciente está siendo exigente; conviene priorizar recuperación."
    elif load_ratio >= 1.1 or monotony >= 1.5 or strain >= 55:
        status = "yellow"
        label = "Fatiga vigilada"
        message = "Tu carga reciente empieza a apretarse; vigila descanso y sensaciones."
    else:
        status = "green"
        label = "Fatiga controlada"
        message = "Tu carga reciente está bien equilibrada."

    return {
        "status": status,
        "label": label,
        "load_ratio_7d_28d": load_ratio,
        "monotony": monotony,
        "strain": strain,
        "message": message,
    }


def detect_quality_blocks(
    runs: list[dict[str, Any]],
    goal_time: str = "3:30",
    min_block_km: float = 3.0,
) -> list[dict[str, Any]]:
    """
    Detecta bloques continuos a ritmo maratón usando splits_metric o laps.

    Reglas:
    - entrada al bloque con ventana base: MP -20s/km hasta MP +10s/km
    - continuidad del bloque con ventana extendida: MP -45s/km hasta MP +15s/km
    - compatible con goal_time dinámico
    - evita off-by-one usando acumulado real de distancia
    """
    base_window = _goal_pace_window(goal_time)
    continuation_window = _goal_pace_continuation_window(goal_time)

    blocks: list[dict[str, Any]] = []

    for run in runs:
        units, source_kind = _extract_units(run)
        if not units:
            continue

        cumulative_km = 0.0
        current_start_km: float | None = None
        current_km = 0.0
        current_units = 0

        def flush_block(end_km: float) -> None:
            nonlocal current_start_km, current_km, current_units

            if current_start_km is None:
                return

            if current_km >= min_block_km:
                blocks.append(
                    {
                        "km": _round1(current_km),
                        "activity_id": run.get("id"),
                        "activity_name": run.get("name"),
                        "activity_date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
                        "total_run_km": _round1(float(run.get("distance", 0)) / 1000.0),
                        "start_km": _round1(current_start_km),
                        "end_km": _round1(end_km),
                        "unit_count": current_units,
                        "source_kind": source_kind,
                    }
                )

            current_start_km = None
            current_km = 0.0
            current_units = 0

        for unit in units:
            unit_km = _unit_distance_km(unit)
            if unit_km <= 0:
                continue

            start_km = cumulative_km
            end_km = cumulative_km + unit_km
            pace_sec = _pace_from_unit(unit)

            if current_start_km is None:
                is_mp_like = _is_in_window(pace_sec, base_window)
            else:
                is_mp_like = _is_in_window(pace_sec, continuation_window)

            if is_mp_like:
                if current_start_km is None:
                    current_start_km = start_km
                current_km += unit_km
                current_units += 1
            else:
                flush_block(start_km)

            cumulative_km = end_km

        flush_block(cumulative_km)

    blocks.sort(
        key=lambda b: (
            b.get("activity_date", ""),
            b.get("activity_id") or 0,
            b.get("start_km") or 0.0,
        ),
        reverse=True,
    )

    return blocks


def build_last_key_session(
    runs: list[dict[str, Any]],
    quality_blocks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Clasificación simple y robusta de la última sesión clave.
    Prioriza:
    1) última actividad con bloque MP detectado
    2) si no existe, mejor tirada larga reciente
    """
    if quality_blocks:
        block = quality_blocks[0]
        return {
            "type": "marathon_specific",
            "date": block.get("activity_date"),
            "distance_km": block.get("total_run_km"),
            "activity_id": block.get("activity_id"),
        }

    dated_runs: list[tuple[datetime, dict[str, Any]]] = []
    for run in runs:
        dt = _parse_datetime(run.get("start_date"))
        if not dt:
            continue
        if run.get("type") != "Run":
            continue
        dated_runs.append((dt, run))

    if not dated_runs:
        return None

    dated_runs.sort(key=lambda x: x[0], reverse=True)

    recent_long = None
    for _, run in dated_runs:
        dist_km = float(run.get("distance", 0) or 0) / 1000.0
        if dist_km >= 24:
            recent_long = run
            break

    run = recent_long or dated_runs[0][1]
    dist_km = _round1(float(run.get("distance", 0) or 0) / 1000.0)

    if dist_km >= 24:
        session_type = "long_run"
    elif dist_km >= 14:
        session_type = "aerobic_run"
    else:
        session_type = "short_run"

    return {
        "type": session_type,
        "date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
        "distance_km": dist_km,
        "activity_id": run.get("id"),
    }