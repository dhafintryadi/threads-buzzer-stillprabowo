"""Definisi tunggal "tab final" -- tab yang TIDAK perlu di-fetch ulang."""

from __future__ import annotations

FINAL_CAP_REASONS = frozenset({"max_scroll_cap", "wall_clock_timeout"})


def is_final_tab(tab_name: str, entry: dict | None) -> bool:
    entry = entry or {}
    status, reason = entry.get("status"), entry.get("reason")
    if status == "complete":
        return True
    if status == "stopped_at_cap" and reason in FINAL_CAP_REASONS:
        return True
    if status == "stalled" and tab_name == "reposts" and reason == "stalled_after_valid_feed_payload":
        return True
    return False


def is_censored_tab(tab_name: str, entry: dict | None) -> bool:
    """Final tapi BUKAN complete: datanya lower-bound, jangan dipakai sebagai nilai pasti."""
    return is_final_tab(tab_name, entry) and (entry or {}).get("status") != "complete"
