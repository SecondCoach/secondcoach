from __future__ import annotations

from typing import Any

import requests

from backend.cache import get_cache, set_cache


STRAVA_ACTIVITY_DETAIL_URL = "https://www.strava.com/api/v3/activities/{activity_id}"


def get_activity_detail(activity_id: int, headers: dict[str, str], ttl_seconds: int = 600) -> dict[str, Any]:
    """
    Devuelve el detalle completo de una actividad Strava usando caché temporal.

    Por qué:
    - El listado /athlete/activities no es fiable para detectar bloques finos por split/lap.
    - El detalle /activities/{id} sí incluye splits_metric/laps utilizables.
    - La caché reduce latencia y consumo de cuota.

    Riesgos:
    - Si la actividad cambia muy recientemente, la caché puede servir un dato antiguo durante ttl_seconds.
    - Si Strava devuelve error, se lanza excepción para no ocultar fallos.

    Cómo verificar:
    - Llamando a esta función dos veces seguidas para el mismo activity_id,
      la segunda debería resolverse desde caché.
    """
    cache_key = f"activity_detail:{activity_id}"
    cached = get_cache(cache_key, ttl_seconds=ttl_seconds)
    if cached:
        return cached

    response = requests.get(
        STRAVA_ACTIVITY_DETAIL_URL.format(activity_id=activity_id),
        headers=headers,
        params={"include_all_efforts": "false"},
        timeout=30,
    )
    response.raise_for_status()

    activity = response.json()
    set_cache(cache_key, activity)
    return activity


def enrich_runs_with_activity_details(
    runs: list[dict[str, Any]],
    headers: dict[str, str],
    *,
    min_distance_km: float = 18.0,
    max_candidates: int = 12,
    ttl_seconds: int = 600,
) -> list[dict[str, Any]]:
    """
    Enriquecer solo las candidatas más relevantes para análisis de maratón.

    Criterio:
    - type == Run (se asume filtrado antes o se tolera aquí)
    - distance >= min_distance_km
    - máximo max_candidates actividades, respetando el orden de entrada

    Por qué:
    - Mantiene /api/analysis razonablemente rápido.
    - Evita pedir detalle de todo el histórico.
    - Prioriza tiradas largas y sesiones donde tiene sentido buscar bloques MP.

    Riesgos:
    - Si una sesión importante queda por debajo de min_distance_km, no se enriquecerá.
    - Si max_candidates es muy bajo, podrías dejar fuera una tirada clave más antigua.

    Cómo verificar:
    - Si entran 40 runs y solo 9 cumplen distance >= 18 km, debe devolver 9.
    - Si entran 40 runs y 20 cumplen, debe devolver solo max_candidates.
    """
    candidates: list[dict[str, Any]] = []

    for run in runs:
        if run.get("type") != "Run":
            continue

        distance_km = float(run.get("distance", 0) or 0) / 1000.0
        if distance_km < min_distance_km:
            continue

        candidates.append(run)
        if len(candidates) >= max_candidates:
            break

    enriched_runs: list[dict[str, Any]] = []

    for run in candidates:
        activity_id = run.get("id")
        if not activity_id:
            continue

        detailed = get_activity_detail(
            activity_id=int(activity_id),
            headers=headers,
            ttl_seconds=ttl_seconds,
        )
        enriched_runs.append(detailed)

    return enriched_runs