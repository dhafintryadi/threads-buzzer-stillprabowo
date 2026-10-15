"""Lapisan I/O bersama: hashing, penulisan CSV deterministik, dan util angka yang aman untuk nilai hilang."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

_QUOTING_MAP = {
    "QUOTE_MINIMAL": csv.QUOTE_MINIMAL,
    "QUOTE_ALL": csv.QUOTE_ALL,
    "QUOTE_NONNUMERIC": csv.QUOTE_NONNUMERIC,
    "QUOTE_NONE": csv.QUOTE_NONE,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_csv_deterministic(
    df: pd.DataFrame,
    path: Path,
    sort_column: str | list[str] | None,
    encoding: str = "utf-8",
    quoting: str = "QUOTE_MINIMAL",
) -> None:
    """Tulis CSV dengan urutan baris deterministik (`.sort_values()` eksplisit sebelum operasi yang urutannya
    berpengaruh) dan quoting eksplisit di config, bukan default pandas yang implisit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df
    if sort_column is not None:
        cols = [sort_column] if isinstance(sort_column, str) else list(sort_column)
        cols = [c for c in cols if c in out.columns]
        if cols:
            out = out.sort_values(by=cols, kind="stable").reset_index(drop=True)
    out.to_csv(
        path,
        index=False,
        encoding=encoding,
        quoting=_QUOTING_MAP.get(quoting, csv.QUOTE_MINIMAL),
    )


def append_csv_row(path: Path, row: dict, fieldnames: list[str], encoding: str = "utf-8") -> None:
    """Append satu baris ke CSV append-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})


def to_numeric_nullable(series: pd.Series) -> pd.Series:
    """Konversi ke numerik dengan string kosong diperlakukan sebagai NaN (bukan 0), supaya kebijakan '0 valid vs missing'
    bisa dibedakan secara eksplisit oleh caller, bukan diam-diam ditimpa pandas."""
    cleaned = series.replace(r"^\s*$", pd.NA, regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
