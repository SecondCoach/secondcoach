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
