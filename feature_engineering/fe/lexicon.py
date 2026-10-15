"""kepadatan leksikon A dan B."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .settings import FeatureEngineeringError

_SEG = re.compile(r"[^a-z0-9\-\s]+|\n+")
_REDUP2 = re.compile(r"\b([a-z]+)2\b")
_TOK = re.compile(r"[a-z]+(?:-[a-z]+)*")


class LexiconMissingError(FeatureEngineeringError):
    pass


def segments(cleaned: str) -> list[list[str]]:
    out = []
    for seg in _SEG.split(cleaned):
        toks = _TOK.findall(_REDUP2.sub(r"\1-\1", seg))
        if toks:
            out.append(toks)
    return out


@dataclass
class Lexicon:
    name: str
    path: str
    sha256: str
    terms: list[tuple[str, ...]]
    n_lines: int
    duplicates: list[str]

    @property
    def n_entries(self) -> int:
        return len(self.terms)


def load_lexicon(path: Path, name: str, clean) -> Lexicon:
    if not path.exists():
        raise LexiconMissingError(
            f"Berkas leksikon {name} tidak ditemukan: {path}. Leksikon disusun terpisah oleh peneliti "
            f"(satu istilah per baris); pipeline berhenti di tahap leksikon dan tidak membangunnya sendiri."
        )
    raw = path.read_bytes()
    lines = [ln.strip() for ln in raw.decode("utf-8-sig").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    terms, seen, duplicates = [], set(), []
    for line in lines:
        segs = segments(clean(line))
        if not segs:
            raise FeatureEngineeringError(f"Leksikon {name}: istilah {line!r} tidak menghasilkan token (cek ejaan/karakter).")
        if len(segs) > 1:
            raise FeatureEngineeringError(
                f"Leksikon {name}: istilah {line!r} mengandung tanda baca pemisah segmen; tidak akan pernah cocok."
            )
        toks = tuple(segs[0])
        if toks in seen:
            duplicates.append(line)
            continue
        seen.add(toks)
        terms.append(toks)
    if not terms:
        raise FeatureEngineeringError(f"Leksikon {name} ({path.name}) kosong.")
    return Lexicon(name=name, path=str(path), sha256=hashlib.sha256(raw).hexdigest(), terms=terms,
                   n_lines=len(lines), duplicates=duplicates)


def build_index(terms: list[tuple[str, ...]]) -> dict[str, list[tuple[str, ...]]]:
    """token pertama -> istilah, diurutkan panjang menurun (pencocokan terpanjang lebih dulu)."""
    idx: dict[str, list[tuple[str, ...]]] = {}
    for t in terms:
        idx.setdefault(t[0], []).append(t)
    for k in idx:
        idx[k].sort(key=lambda t: (-len(t), t))
    return idx


def count_matches(segs: list[list[str]], idx: dict) -> list[str]:
    """Kemunculan (istilah yang cocok, digabung spasi) -- terpanjang dulu, kiri ke kanan, tanpa tumpang tindih."""
    hits = []
    for toks in segs:
        i = 0
        while i < len(toks):
            for term in idx.get(toks[i], ()):
                n = len(term)
                if tuple(toks[i:i + n]) == term:
                    hits.append(" ".join(term))
                    i += n
                    break
            else:
                i += 1
    return hits


DENOMINATORS = ("entries", "tokens")


def lexicon_density(texts: pd.Series, lexicons: dict[str, Lexicon], clean, denominator: str = "entries") -> tuple[pd.DataFrame, dict]:
    """texts (caption_text) -> kolom `kepadatan_leksikon_{a,b}` + hitungan audit."""
    if denominator not in DENOMINATORS:
        raise FeatureEngineeringError(f"Penyebut kepadatan {denominator!r} tidak dikenal (pilihan: {DENOMINATORS}).")
    indexes = {k: build_index(lx.terms) for k, lx in lexicons.items()}
    rows, term_totals = [], {k: {} for k in lexicons}
    for text in texts:
        segs = segments(clean(None if pd.isna(text) else text))
        n_tokens = sum(len(s) for s in segs)
        row = {"n_tokens": n_tokens}
        for key, lx in lexicons.items():
            hits = count_matches(segs, indexes[key])
            for h in hits:
                term_totals[key][h] = term_totals[key].get(h, 0) + 1
            row[f"n_match_{key}"] = len(hits)
            denom = lx.n_entries if denominator == "entries" else n_tokens
            row[f"kepadatan_leksikon_{key}"] = len(hits) / denom if denom else 0.0
        rows.append(row)
    return pd.DataFrame(rows, index=texts.index), term_totals


def distribution(values: pd.Series) -> dict:
    zero = int((values == 0).sum())
    return {
        "n": int(len(values)),
        "n_zero": zero,
        "pct_zero": round(100 * zero / len(values), 2) if len(values) else None,
        "min": float(values.min()),
        "median": float(values.median()),
        "max": float(values.max()),
    }
