from __future__ import annotations


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _distance_km(run: dict) -> float:
    return round(_safe_float(run.get("distance")) / 1000.0, 1)


def _run_quality_km(run: dict, quality_blocks: list[dict]) -> float:
    run_id = run.get("id")
    total = 0.0

    for block in quality_blocks or []:
        if block.get("activity_id") == run_id:
            total += _safe_float(block.get("km"))

    return round(total, 1)


def _name_lower(run: dict) -> str:
    return str(run.get("name") or "").strip().lower()


def _extract_units(run: dict) -> list[dict]:
    splits = run.get("splits_metric")
    if isinstance(splits, list) and splits:
        return splits

    laps = run.get("laps")
    if isinstance(laps, list) and laps:
        return laps

    return []


def _unit_pace_sec_per_km(unit: dict) -> float:
    moving_time = _safe_float(unit.get("moving_time"))
    distance_km = _safe_float(unit.get("distance")) / 1000.0

    if moving_time <= 0 or distance_km <= 0:
        return 9999.0

    return moving_time / distance_km


def _is_progressive_run(run: dict) -> bool:
    units = _extract_units(run)
    if len(units) < 9:
        return False

    paces = [_unit_pace_sec_per_km(u) for u in units]
    third = len(paces) // 3

    if third < 3:
        return False

    first_avg = sum(paces[:third]) / len(paces[:third])
    last_avg = sum(paces[-third:]) / len(paces[-third:])

    # Menor tiempo/km = más rápido. Exigimos mejora clara.
    return (first_avg - last_avg) >= 10


def _is_race_or_test(run: dict) -> bool:
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

    # Distancias típicas de competición / test
    typical = [5.0, 10.0, 21.1, 42.2]
    return any(abs(km - t) <= 0.4 for t in typical)


def classify_run(run: dict, quality_blocks: list[dict]) -> str:
    km = _distance_km(run)
    quality_km = _run_quality_km(run, quality_blocks)

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


def _session_priority(session_type: str) -> int:
    priorities = {
        "marathon_specific": 5,
        "long_run": 4,
        "progressive_run": 3,
        "race_or_test": 2,
        "aerobic_run": 1,
        "short_run": 0,
    }
    return priorities.get(session_type, 0)


def detect_last_key_session(runs: list[dict], quality_blocks: list[dict]):
    if not runs:
        return None

    runs_sorted = sorted(
        runs,
        key=lambda r: r.get("start_date") or r.get("start_date_local") or "",
        reverse=True,
    )

    best = None

    for run in runs_sorted:
        km = _distance_km(run)

        if km < 8:
            continue

        session_type = classify_run(run, quality_blocks)
        candidate = {
            "type": session_type,
            "date": (run.get("start_date_local") or run.get("start_date") or "")[:10],
            "distance_km": km,
        }

        if best is None:
            best = candidate
            continue

        current_priority = _session_priority(candidate["type"])
        best_priority = _session_priority(best["type"])

        if current_priority > best_priority:
            best = candidate
            continue

        if current_priority == best_priority and candidate["date"] > best["date"]:
            best = candidate

    return best