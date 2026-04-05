from typing import Any


def _share_colors_from_payload(data: dict[str, Any]) -> tuple[str, str, str]:
    chip = str((data.get("one_line") or {}).get("chip") or "").upper()

    if chip == "FATIGA ALTA":
        return ("#06142b", "#122247", "#f59e0b")
    if chip == "POR DETRÁS":
        return ("#2a0f12", "#4a161b", "#ef4444")
    if chip == "POR DELANTE":
        return ("#0a1f17", "#123526", "#22c55e")
    if chip == "EN OBJETIVO":
        return ("#0b1c1f", "#12313a", "#22c55e")
    if chip == "CERCA":
        return ("#1f1a0a", "#3a3012", "#f59e0b")

    return ("#0b1c1f", "#12313a", "#38bdf8")


def _compact_goal_context_from_payload(data: dict[str, Any]) -> str:
    objective = str(data.get("objective") or "").strip().lower()
    race_date = str(data.get("race_date") or "").strip()

    objective_labels = {
        "marathon": "Maratón",
        "half_marathon": "Media maratón",
        "10k": "10K",
        "5k": "5K",
    }
    objective_label = objective_labels.get(objective, "")

    formatted_race_date = ""
    if len(race_date) >= 10 and race_date[4:5] == "-" and race_date[7:8] == "-":
        year, month, day = race_date[:10].split("-")
        formatted_race_date = f"{day}-{month}-{year}"

    if not objective_label:
        return ""

    if formatted_race_date:
        return f"{objective_label} · {formatted_race_date}"

    return objective_label
