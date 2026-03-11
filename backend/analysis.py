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