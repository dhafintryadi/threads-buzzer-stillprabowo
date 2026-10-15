"""Aliran T (TF-IDF): pembersihan bersama -> tokenisasi -> stopword Sastrawi -> stem -> gabung spasi."""

from __future__ import annotations

import re

from .shared_clean import clean_shared
from .stemmer_ext import StemmerBundle, build_stemmers

TOKEN_T = re.compile(r"[a-z]+(?:-[a-z]+)*")


def stream_t(text: str | None, bundle: StemmerBundle | None = None, extended_dictionary: bool = False) -> str:
    """Kamus stemmer bawaan secara default; `extended_dictionary=True` memakai kamus aliran L."""
    bundle = bundle or build_stemmers()
    stem = bundle.stem_l if extended_dictionary else bundle.stem_t
    tokens = [t for t in TOKEN_T.findall(clean_shared(text)) if t not in bundle.stopwords_t]
    return " ".join(stem(t) for t in tokens)
