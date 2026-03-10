from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.session_classifier import detect_last_key_session

QUALITY_BLOCK_LOOKBACK_DAYS = 84


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


def _activity_datetime(run: dict[str, Any]) -> datetime | None:
    dt = _parse_datetime(run.get("start_date")) or _parse_datetime(run.get("start_date_local"))
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_training(runs: list[dict[str, Any]]) -> tuple[float, float, float]:
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

        dt = _activity_datetime(run)
        if dt is None:
            continue

        if dt >= seven_days_ago:
            km_last_7_days += run_km

        if dt >= twenty_eight_days_ago:
            km_last_28_days += run_km

    weekly_average_km = km_last_28_days / 4.0
    return round(km_last_7_days, 1), round(weekly_average_km, 1), round(long_run_km, 1)


def _extract_units(run: dict[str, Any]) -> list[dict[str, Any]]:
    splits = run.get("splits_metric")
    if isinstance(splits, list) and splits:
        return splits

    laps = run.get("laps")
    if isinstance(laps, list) and laps:
        return laps

    return []


def _unit_distance_km(unit: dict[str, Any]) -> float:
    km = _safe_float(unit.get("distance")) / 1000.0
    if km <= 0:
        km = 1.0
    return km


def _unit_pace_sec_per_km(unit: dict[str, Any]) -> float:
    moving_time_sec = _safe_float(unit.get("moving_time"))
    distance_km = _unit_distance_km(unit)

    if moving_time_sec <= 0 or distance_km <= 0:
        return 9999.0

    return moving_time_sec / distance_km


def _build_quality_block(
    run: dict[str, Any],
    start_index: int,
    end_index: int,
    cumulative_distances_km: list[float],
    unit_count: int,
    source_kind: str,
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
        "unit_count": unit_count,
        "source_kind": source_kind,
    }


def detect_quality_blocks(
    runs: list[dict[str, Any]],
    goal_time: str = "3:30",
    race_type: str = "marathon",
) -> list[dict[str, Any]]:
    if race_type != "marathon":
        return []

    now = _now_utc()
    lookback_start = now - timedelta(days=QUALITY_BLOCK_LOOKBACK_DAYS)

    # Ventana calibrada con tu caso real: 4:44–4:55 detectado sin romper el resto.
    min_pace_sec = 4 * 60 + 40
    max_pace_sec = 5 * 60 + 5

    blocks: list[dict[str, Any]] = []

    for run in runs:
        if run.get("type") != "Run":
            continue

        activity_dt = _activity_datetime(run)
        if activity_dt is None or activity_dt < lookback_start:
            continue

        total_run_km = _meters_to_km(run.get("distance"))
        if total_run_km < 24.0:
            continue

        has_splits = isinstance(run.get("splits_metric"), list) and bool(run.get("splits_metric"))
        source_kind = "splits_metric" if has_splits else "laps"

        units = _extract_units(run)
        if not units:
            continue

        cumulative_distances_km: list[float] = [0.0]
        for unit in units:
            cumulative_distances_km.append(cumulative_distances_km[-1] + _unit_distance_km(unit))

        second_half_threshold = total_run_km / 2.0

        current_start_idx: int | None = None
        current_end_idx: int | None = None
        current_distance_km = 0.0
        current_unit_count = 0

        for idx, unit in enumerate(units):
            unit_distance_km = _unit_distance_km(unit)
            unit_end_km = cumulative_distances_km[idx + 1]

            if unit_end_km <= second_half_threshold:
                continue

            pace_sec_per_km = _unit_pace_sec_per_km(unit)
            is_mp = min_pace_sec <= pace_sec_per_km <= max_pace_sec

            if is_mp:
                if current_start_idx is None:
                    current_start_idx = idx
                    current_end_idx = idx + 1
                    current_distance_km = unit_distance_km
                    current_unit_count = 1
                else:
                    current_end_idx = idx + 1
                    current_distance_km += unit_distance_km
                    current_unit_count += 1
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
                            unit_count=current_unit_count,
                            source_kind=source_kind,
                        )
                    )

                current_start_idx = None
                current_end_idx = None
                current_distance_km = 0.0
                current_unit_count = 0

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
                    unit_count=current_unit_count,
                    source_kind=source_kind,
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


def build_last_key_session(runs: list[dict[str, Any]], quality_blocks: list[dict[str, Any]]):
    recent_runs = []
    lookback_start = _now_utc() - timedelta(days=QUALITY_BLOCK_LOOKBACK_DAYS)

    for run in runs:
        dt = _activity_datetime(run)
        if dt is None or dt < lookback_start:
            continue
        recent_runs.append(run)

    recent_runs.sort(key=lambda r: r.get("start_date") or r.get("start_date_local") or "", reverse=True)

    return detect_last_key_session(recent_runs, quality_blocks)