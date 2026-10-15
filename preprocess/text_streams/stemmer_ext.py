"""Stemmer Sastrawi: bawaan (aliran T) dan kamus diperluas (aliran L), plus golden check kamus."""

from __future__ import annotations

import hashlib
import importlib.metadata as importlib_metadata
from dataclasses import dataclass, field
from functools import lru_cache

from Sastrawi.Dictionary.ArrayDictionary import ArrayDictionary
from Sastrawi.Stemmer.Stemmer import Stemmer
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory

DEFAULT_EXTRA_ROOTS = ("goblog", "mahasewa", "aseng", "soros", "proksi")


class StemmerSetupError(Exception):
    pass


def dict_hash(words, extra_roots) -> str:
    """SHA-256 (16 karakter pertama) dari kata-kata terurut: kamus bawaan + extra_roots."""
    merged = sorted(set(words) | set(extra_roots))
    return hashlib.sha256("\n".join(merged).encode()).hexdigest()[:16]


def pysastrawi_version() -> str | None:
    for name in ("PySastrawi", "Sastrawi"):
        try:
            return f"{name}=={importlib_metadata.version(name)}"
        except importlib_metadata.PackageNotFoundError:
            continue
    return None


@dataclass
class StemmerBundle:
    stemmer_t: Stemmer
    stemmer_l: Stemmer
    stopwords_t: frozenset
    words: frozenset
    extra_roots: tuple
    extra_added: list
    dict_hash: str
    version: str | None
    _cache_t: dict = field(default_factory=dict, repr=False)
    _cache_l: dict = field(default_factory=dict, repr=False)

    def stem_t(self, token: str) -> str:
        if token not in self._cache_t:
            self._cache_t[token] = self.stemmer_t.stem(token)
        return self._cache_t[token]

    def stem_l(self, token: str) -> str:
        if token not in self._cache_l:
            self._cache_l[token] = self.stemmer_l.stem(token)
        return self._cache_l[token]


@lru_cache(maxsize=None)
def _build(extra_roots: tuple, expected_dict_hash: str | None) -> StemmerBundle:
    factory = StemmerFactory()
    words = factory.get_words()
    wordset = frozenset(words)
    added = [w for w in extra_roots if w not in wordset]
    got = dict_hash(wordset, extra_roots)
    if expected_dict_hash and got != expected_dict_hash:
        raise StemmerSetupError(
            f"Hash kamus {got} != golden {expected_dict_hash} (versi: {pysastrawi_version()}). Hentikan dan "
            f"laporkan: kamus Sastrawi berbeda dari yang dikunci; jangan lanjut diam-diam."
        )
    return StemmerBundle(
        stemmer_t=factory.create_stemmer(),
        stemmer_l=Stemmer(ArrayDictionary(list(words) + added)),
        stopwords_t=frozenset(StopWordRemoverFactory().get_stop_words()),
        words=wordset,
        extra_roots=tuple(extra_roots),
        extra_added=added,
        dict_hash=got,
        version=pysastrawi_version(),
    )


def build_stemmers(extra_roots=DEFAULT_EXTRA_ROOTS, expected_dict_hash: str | None = None) -> StemmerBundle:
    """Bangun (dan cache) stemmer T + L."""
    return _build(tuple(extra_roots), expected_dict_hash)
