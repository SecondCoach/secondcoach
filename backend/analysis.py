from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


QUALITY_BLOCK_LOOKBACK_DAYS = 28
MARATHON_PACE_MIN_SEC_PER_KM = 285  # 4:45/km
MARATHON_PACE_MAX_SEC_PER_KM = 305  # 5:05/km


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _activity_datetime(run: dict[str, Any]) -> datetime | None:
    raw = run.get("start_date") or run.get("start_date_local")
    if not raw:
        return None

    try:
        if isinstance(raw, str) and raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _distance_km(run: dict[str, Any]) -> float:
    return round(_safe_float(run.get("distance")) / 1000.0, 1)


def _extract_units(run: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    splits = run.get("splits_metric")
    if isinstance(splits, list) and splits:
        return splits, "splits_metric"

    laps = run.get("laps")
    if isinstance(laps, list) and laps:
        return laps, "laps"

    return [], None


def _unit_distance_km(unit: dict[str, Any]) -> float:
    return _safe_float(unit.get("distance")) / 1000.0


def _unit_pace_sec_per_km(unit: dict[str, Any]) -> float:
    moving_time = _safe_float(unit.get("moving_time"))
    distance_km = _unit_distance_km(unit)

    if moving_time <= 0 or distance_km <= 0:
        return 9999.0

    return moving_time / distance_km


def _is_goal_pace_unit(unit: dict[str, Any]) -> bool:
    pace = _unit_pace_sec_per_km(unit)
    return MARATHON_PACE_MIN_SEC_PER_KM <= pace <= MARATHON_PACE_MAX_SEC_PER_KM


def _build_quality_block(
    run: dict[str, Any],
    start_index: int,
    end_index: int,
    cumulative_distances_km: list[float],
    unit_count: int,
    source_kind: str | None,
) -> dict[str, Any]:
    total_run_km = _distance_km(run)
    start_km = round(cumulative_distances_km[start_index] + 1.0, 1)
    end_km = round(cumulative_distances_km[end_index + 1], 1)
    block_km = round(end_km - cumulative_distances_km[start_index], 1)

    return {
        "km": block_km,
        "activity_id": run.get("id"),
        "activity_name": run.get("name"),
        "activity_date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
        "total_run_km": total_run_km,
        "start_km": start_km,
        "end_km": end_km,
        "unit_count": unit_count,
        "source_kind": source_kind,
    }


def compute_training(runs: list[dict[str, Any]]) -> tuple[float, float, float]:
    now = _now_utc()
    start_7 = now - timedelta(days=7)
    start_84 = now - timedelta(days=84)

    km_last_7_days = 0.0
    total_km_84_days = 0.0
    long_run_km = 0.0

    for run in runs:
        dt = _activity_datetime(run)
        if dt is None:
            continue

        run_km = _distance_km(run)
        if run_km <= 0:
            continue

        if dt >= start_7:
            km_last_7_days += run_km

        if dt >= start_84:
            total_km_84_days += run_km

        if run_km > long_run_km:
            long_run_km = run_km

    weekly_average_km = total_km_84_days / 12.0 if total_km_84_days > 0 else 0.0

    return round(km_last_7_days, 1), round(weekly_average_km, 1), round(long_run_km, 1)


def detect_quality_blocks(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookback_start = _now_utc() - timedelta(days=QUALITY_BLOCK_LOOKBACK_DAYS)
    blocks: list[dict[str, Any]] = []

    for run in runs:
        dt = _activity_datetime(run)
        if dt is None or dt < lookback_start:
            continue

        total_run_km = _distance_km(run)
        if total_run_km < 12:
            continue

        units, source_kind = _extract_units(run)
        if not units:
            continue

        cumulative_distances_km = [0.0]
        for unit in units:
            cumulative_distances_km.append(
                round(cumulative_distances_km[-1] + _unit_distance_km(unit), 3)
            )

        current_start_idx = None
        current_end_idx = None
        current_distance_km = 0.0
        current_unit_count = 0

        for idx, unit in enumerate(units):
            unit_km = _unit_distance_km(unit)

            if unit_km <= 0:
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
                continue

            if _is_goal_pace_unit(unit):
                if current_start_idx is None:
                    current_start_idx = idx
                current_end_idx = idx
                current_distance_km += unit_km
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


def build_last_key_session(
    runs: list[dict[str, Any]],
    quality_blocks: list[dict[str, Any]],
):
    lookback_start = _now_utc() - timedelta(days=QUALITY_BLOCK_LOOKBACK_DAYS)

    recent_runs = []
    for run in runs:
        dt = _activity_datetime(run)
        if dt is None or dt < lookback_start:
            continue
        recent_runs.append(run)

    recent_runs.sort(
        key=lambda r: r.get("start_date") or r.get("start_date_local") or "",
        reverse=True,
    )

    recent_run_by_id = {
        run.get("id"): run
        for run in recent_runs
        if run.get("id") is not None
    }

    recent_blocks = sorted(
        quality_blocks or [],
        key=lambda b: (
            b.get("activity_date", ""),
            _safe_float(b.get("start_km")),
        ),
        reverse=True,
    )

    for block in recent_blocks:
        activity_id = block.get("activity_id")
        run = recent_run_by_id.get(activity_id)
        if not run:
            continue

        km = _distance_km(run)
        if km < 20:
            continue

        return {
            "type": "marathon_specific",
            "date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
            "distance_km": km,
        }

    if not recent_runs:
        return None

    best = None
    priorities = {
        "marathon_specific": 5,
        "long_run": 4,
        "progressive_run": 3,
        "race_or_test": 2,
        "aerobic_run": 1,
        "short_run": 0,
    }

    def _name_lower(run: dict[str, Any]) -> str:
        return str(run.get("name") or "").strip().lower()

    def _run_quality_km(run: dict[str, Any]) -> float:
        run_id = run.get("id")
        total = 0.0
        for block in quality_blocks or []:
            if block.get("activity_id") == run_id:
                total += _safe_float(block.get("km"))
        return round(total, 1)

    def _is_progressive_run(run: dict[str, Any]) -> bool:
        units, _ = _extract_units(run)
        if len(units) < 9:
            return False

        paces = [_unit_pace_sec_per_km(u) for u in units]
        third = len(paces) // 3
        if third < 3:
            return False

        first_avg = sum(paces[:third]) / len(paces[:third])
        last_avg = sum(paces[-third:]) / len(paces[-third:])
        return (first_avg - last_avg) >= 10

    def _is_race_or_test(run: dict[str, Any]) -> bool:
        name = _name_lower(run)
        km = _distance_km(run)
        keywords = [
            "race",
            "carrera",
            "maratón",
            "maraton",
            "media maratón",
            "media maraton",
            "half marathon",
            "10k",
            "5k",
            "test",
        ]
        if any(k in name for k in keywords):
            return True
        typical = [5.0, 10.0, 21.1, 42.2]
        return any(abs(km - t) <= 0.4 for t in typical)

    def _classify_run(run: dict[str, Any]) -> str:
        km = _distance_km(run)
        quality_km = _run_quality_km(run)

        if _is_race_or_test(run):
            return "race_or_test"
        if km >= 24 and quality_km >= 6:
            return "marathon_specific"
        if km >= 14 and _is_progressive_run(run):
            return "progressive_run"
        if km >= 24:
            return "long_run"
        if km >= 10:
            return "aerobic_run"
        return "short_run"

    for run in recent_runs:
        km = _distance_km(run)
        if km < 8:
            continue

        session_type = _classify_run(run)
        candidate = {
            "type": session_type,
            "date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
            "distance_km": km,
        }

        if best is None:
            best = candidate
            continue

        current_priority = priorities.get(candidate["type"], 0)
        best_priority = priorities.get(best["type"], 0)

        if current_priority > best_priority:
            best = candidate
        elif current_priority == best_priority and candidate["date"] > best["date"]:
            best = candidate

    return best


def compute_fatigue_signal(km_last_7_days: float, weekly_average_km: float) -> dict[str, Any]:
    if weekly_average_km <= 0:
        return {
            "status": "unknown",
            "label": "Sin datos suficientes",
            "ratio_7d_vs_avg": 0.0,
            "message": "Aún no hay suficiente entrenamiento reciente para estimar fatiga.",
        }

    ratio = round(km_last_7_days / weekly_average_km, 2)

    if ratio >= 1.35:
        return {
            "status": "red",
            "label": "Fatiga alta",
            "ratio_7d_vs_avg": ratio,
            "message": "Tu carga de 7 días está claramente por encima de tu media. Toca priorizar recuperación.",
        }

    if ratio >= 1.1:
        return {
            "status": "yellow",
            "label": "Fatiga moderada",
            "ratio_7d_vs_avg": ratio,
            "message": "Tu carga reciente está algo por encima de tu media habitual. Vigila sensaciones y descanso.",
        }

    return {
        "status": "green",
        "label": "Fatiga controlada",
        "ratio_7d_vs_avg": ratio,
        "message": "Tu carga reciente está en línea con tu media habitual.",
    }