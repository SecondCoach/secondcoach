from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _meters_to_km(meters: Any) -> float:
    return round(_safe_float(meters) / 1000.0, 1)


def _seconds_to_mmss(seconds: float) -> str:
    total = int(round(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"


def _pace_seconds_per_km_from_goal_time(goal_time: str, distance_km: float = 42.195) -> float:
    """
    goal_time examples:
    - '3:30'
    - '3:30:00'
    """
    if not goal_time:
        goal_time = "3:30"

    parts = [int(p) for p in goal_time.split(":")]

    if len(parts) == 2:
        hours, minutes = parts
        seconds = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours, minutes, seconds = 3, 30, 0

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds / distance_km


def _goal_pace_window_seconds(goal_time: str = "3:30") -> tuple[float, float]:
    """
    Mantiene una ventana muy parecida a la actual para no romper el comportamiento:
    para 3:30 maratón ≈ 4:58/km, y usamos ±9 segundos.
    """
    target = _pace_seconds_per_km_from_goal_time(goal_time, 42.195)
    return target - 9, target + 9


def compute_training(runs: list[dict[str, Any]]) -> tuple[float, float, float]:
    """
    Devuelve:
    - km últimos 7 días
    - media semanal estimada en 28 días
    - tirada larga (km)
    """
    now = _now_utc()
    seven_days_ago = now - timedelta(days=7)
    twenty_eight_days_ago = now - timedelta(days=28)

    km_last_7_days = 0.0
    km_last_28_days = 0.0
    long_run_km = 0.0

    for run in runs:
        if run.get("type") != "Run":
            continue

        distance_m = _safe_float(run.get("distance"))
        run_km = distance_m / 1000.0
        long_run_km = max(long_run_km, run_km)

        dt = _parse_datetime(run.get("start_date")) or _parse_datetime(run.get("start_date_local"))
        if dt is None:
            continue

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        if dt >= seven_days_ago:
            km_last_7_days += run_km

        if dt >= twenty_eight_days_ago:
            km_last_28_days += run_km

    weekly_average_km = km_last_28_days / 4.0

    return round(km_last_7_days, 1), round(weekly_average_km, 1), round(long_run_km, 1)


def _extract_splits(run: dict[str, Any]) -> list[dict[str, Any]]:
    splits = run.get("splits_metric")
    if isinstance(splits, list):
        return splits
    return []


def _build_quality_block(
    run: dict[str, Any],
    start_index: int,
    end_index: int,
    cumulative_distances_km: list[float],
    split_count: int,
) -> dict[str, Any]:
    total_run_km = _meters_to_km(run.get("distance"))
    start_km = round(cumulative_distances_km[start_index], 1)
    end_km = round(cumulative_distances_km[end_index], 1)
    block_km = round(end_km - start_km, 1)

    return {
        "km": block_km,
        "activity_id": run.get("id"),
        "activity_name": run.get("name", "Run"),
        "activity_date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
        "total_run_km": total_run_km,
        "start_km": start_km,
        "end_km": end_km,
        "split_count": split_count,
    }


def detect_quality_blocks(
    runs: list[dict[str, Any]],
    goal_time: str = "3:30",
    race_type: str = "marathon",
) -> list[dict[str, Any]]:
    """
    Reglas MVP conservadoras:
    - solo tipo Run
    - solo tiradas >= 24 km
    - solo segunda mitad de la tirada
    - split válido si pace está en ventana MP
    - bloque válido si acumula >= 4.0 km continuos

    Devuelve bloques enriquecidos con:
    activity_id, activity_name, activity_date, total_run_km, start_km, end_km
    """
    if race_type != "marathon":
        return []

    min_pace_sec, max_pace_sec = _goal_pace_window_seconds(goal_time)
    blocks: list[dict[str, Any]] = []

    for run in runs:
        if run.get("type") != "Run":
            continue

        total_run_km = _meters_to_km(run.get("distance"))
        if total_run_km < 24.0:
            continue

        splits = _extract_splits(run)
        if not splits:
            continue

        cumulative_distances_km: list[float] = [0.0]
        for split in splits:
            last = cumulative_distances_km[-1]
            split_km = _safe_float(split.get("distance")) / 1000.0
            if split_km <= 0:
                split_km = 1.0
            cumulative_distances_km.append(last + split_km)

        second_half_threshold = total_run_km / 2.0

        current_start_idx: int | None = None
        current_end_idx: int | None = None
        current_distance_km = 0.0
        current_split_count = 0

        for idx, split in enumerate(splits):
            split_distance_km = _safe_float(split.get("distance")) / 1000.0
            if split_distance_km <= 0:
                split_distance_km = 1.0

            split_start_km = cumulative_distances_km[idx]
            split_end_km = cumulative_distances_km[idx + 1]

            if split_end_km <= second_half_threshold:
                continue

            moving_time_sec = _safe_float(split.get("moving_time"))
            if moving_time_sec <= 0:
                pace_sec_per_km = 9999.0
            else:
                pace_sec_per_km = moving_time_sec / split_distance_km

            is_mp = min_pace_sec <= pace_sec_per_km <= max_pace_sec

            if is_mp:
                if current_start_idx is None:
                    current_start_idx = idx
                    current_end_idx = idx + 1
                    current_distance_km = split_distance_km
                    current_split_count = 1
                else:
                    current_end_idx = idx + 1
                    current_distance_km += split_distance_km
                    current_split_count += 1
            else:
                if (
                    current_start_idx is not None
                    and current_end_idx is not None
                    and current_distance_km >= 4.0
                ):
                    blocks.append(
                        _build_quality_block(
                            run=run,
                            start_index=current_start_idx,
                            end_index=current_end_idx,
                            cumulative_distances_km=cumulative_distances_km,
                            split_count=current_split_count,
                        )
                    )

                current_start_idx = None
                current_end_idx = None
                current_distance_km = 0.0
                current_split_count = 0

        if (
            current_start_idx is not None
            and current_end_idx is not None
            and current_distance_km >= 4.0
        ):
            blocks.append(
                _build_quality_block(
                    run=run,
                    start_index=current_start_idx,
                    end_index=current_end_idx,
                    cumulative_distances_km=cumulative_distances_km,
                    split_count=current_split_count,
                )
            )

    blocks.sort(
        key=lambda b: (
            b.get("activity_date", ""),
            _safe_float(b.get("start_km")),
        ),
        reverse=True,
    )

    return blocks