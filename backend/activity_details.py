def enrich_runs_with_activity_details(access_token: str, activities: list[dict]) -> list[dict]:
    if not isinstance(activities, list):
        return []

    enriched = []

    for item in activities:
        if not isinstance(item, dict):
            continue

        if item.get("type") != "Run":
            enriched.append(item)
            continue

        activity_id = item.get("id")
        if not activity_id:
            enriched.append(item)
            continue

        try:
            detail = fetch_activity_details(access_token, activity_id)
            if isinstance(detail, dict):
                merged = {**item, **detail}
                enriched.append(merged)
            else:
                enriched.append(item)
        except Exception:
            enriched.append(item)

    return enriched