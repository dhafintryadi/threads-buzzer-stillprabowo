"""Pembersihan bersama (sebelum fork aliran T / aliran L)."""

from __future__ import annotations

import re

_URL = re.compile(r"https?://\S+|www\.\S+")
_MENTION = re.compile(r"@\w+")
_SPACES = re.compile(r"[ \t\r\f\v]+")


def clean_shared(text: str | None) -> str:
    """lowercase -> hapus URL -> hapus mention -> hapus simbol '#' (kata tagar dipertahankan) -> rapikan spasi/tab."""
    t = ("" if text is None else str(text)).lower()
    t = _URL.sub(" ", t)
    t = _MENTION.sub(" ", t)
    t = t.replace("#", "")
    t = _SPACES.sub(" ", t)
    return t.strip()
