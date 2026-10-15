"""Logika jendela waktu observasi terpusat."""

from __future__ import annotations

from datetime import datetime, timezone

import config


def to_utc_datetime(taken_at: int) -> datetime:
    """Konversi UNIX timestamp (detik) ke datetime UTC eksplisit."""
    return datetime.fromtimestamp(taken_at, tz=timezone.utc)


def format_utc(taken_at: int) -> str:
    """Representasi tanggal yang mudah dibaca manusia (UTC eksplisit), dipakai saat menulis tabel post ke CSV supaya
    tidak perlu konversi manual dari epoch timestamp saat EDA/pelabelan."""
    return to_utc_datetime(taken_at).strftime("%Y-%m-%dT%H:%M:%SZ")


def window_position(taken_at: int) -> str:
    """Posisi taken_at relatif terhadap jendela observasi."""
    dt = to_utc_datetime(taken_at)
    if dt < config.WINDOW_START:
        return "before"
    if dt > config.WINDOW_END:
        return "after"
    return "within"


def is_within_window(taken_at: int) -> bool:
    """Shortcut boolean, dipakai post_filter.py (tidak butuh bedakan before/after, cukup tahu di dalam jendela atau
    tidak)."""
    return window_position(taken_at) == "within"
