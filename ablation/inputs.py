"""Penemuan dan validasi masukan."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from .config import Settings


class AblationError(Exception):
    """Ketidakcocokan data/masukan: berhenti, tanpa menebak atau mengisi nilai diam-diam."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _header(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return fh.readline().strip().split(",")


def discover(s: Settings) -> dict:
    """Telusuri direktori run, temukan berkas prediksi per akun, petakan 9 sel -> (path, filter, jumlah baris)."""
    run_dir = s.run_dir
    if not run_dir.is_dir():
        raise AblationError(f"Direktori run modeling tidak ditemukan: {run_dir}")
    need = {s.col_user_id, s.col_y_true, s.col_y_pred}
    candidates = sorted(p for p in run_dir.rglob("*.csv") if need <= set(_header(p)))
    if not candidates:
        raise AblationError(
            f"Prediksi per akun uji tidak tersedia di {run_dir} (tidak ada CSV dengan kolom {sorted(need)}). "
            "Ablasi tidak menjalankan inferensi sendiri; keluaran modeling harus diperluas terpisah.")
    chosen = [p for p in candidates if p.name == s.predictions_file]
    if len(chosen) != 1:
        raise AblationError(f"Berkas prediksi {s.predictions_file!r} tidak tunggal/tidak ada; kandidat: "
                            f"{[str(p.relative_to(run_dir)) for p in candidates]}")
    path = chosen[0]
    if not {s.col_split, s.col_config} <= set(_header(path)):
        raise AblationError(f"{path.name}: kolom {s.col_split!r}/{s.col_config!r} tidak ada; sel tidak dapat dipetakan")
    df = read_predictions(path, s)
    mapping = {}
    for sl, sv in s.splits.items():
        for cl, cv in s.configs.items():
            n = int(((df[s.col_split] == sv) & (df[s.col_config] == cv)).sum())
            mapping[(sl, cl)] = {"path": str(path.relative_to(run_dir)),
                                 "filter": {s.col_split: sv, s.col_config: cv}, "n_rows": n}
    return {"path": path, "frame": df, "cells": mapping, "candidates": [str(p.relative_to(run_dir)) for p in candidates]}


def read_predictions(path: Path, s: Settings) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={s.col_user_id: str, s.col_config: str})
    split_dtype = type(next(iter(s.splits.values())))
    try:
        df[s.col_split] = df[s.col_split].astype(split_dtype)
    except (TypeError, ValueError) as e:
        raise AblationError(f"{path.name}: kolom split tidak dapat dibaca sebagai {split_dtype.__name__}") from e
    return df


def validate(df: pd.DataFrame, s: Settings) -> dict:
    """Gagal keras pada pelanggaran Mengembalikan sel -> DataFrame (user_id, y_true, y_pred) yang tervalidasi."""
    errors = []
    known_split, known_conf = set(s.splits.values()), set(s.configs.values())
    unknown = df[~df[s.col_split].isin(known_split) | ~df[s.col_config].isin(known_conf)]
    if len(unknown):
        pairs = sorted({(str(a), str(b)) for a, b in zip(unknown[s.col_split], unknown[s.col_config])})
        errors.append(f"pasangan split/konfigurasi tidak dikenal di config: {pairs}")
    cells = {}
    for sl, sv in s.splits.items():
        for cl, cv in s.configs.items():
            part = df[(df[s.col_split] == sv) & (df[s.col_config] == cv)]
            name = f"{sl} x {cl}"
            if part.empty:
                errors.append(f"sel {name} tidak ditemukan")
                continue
            uid, yt, yp = part[s.col_user_id], part[s.col_y_true], part[s.col_y_pred]
            if uid.isna().any() or (uid.astype(str).str.strip() == "").any():
                errors.append(f"sel {name}: user_id kosong")
            if uid.duplicated().any():
                errors.append(f"sel {name}: user_id duplikat ({int(uid.duplicated().sum())})")
            for col, v in ((s.col_y_true, yt), (s.col_y_pred, yp)):
                if v.isna().any() or not v.isin([0, 1]).all():
                    errors.append(f"sel {name}: {col} kosong atau bernilai selain {{0, 1}}")
            cells[(sl, cl)] = pd.DataFrame({"user_id": uid.astype(str).to_numpy(),
                                            "y_true": pd.to_numeric(yt, errors="coerce").to_numpy(),
                                            "y_pred": pd.to_numeric(yp, errors="coerce").to_numpy()})
    if errors:
        raise AblationError("Validasi masukan gagal:\n  - " + "\n  - ".join(errors))

    for sl in s.splits:
        frames = {cl: cells[(sl, cl)].set_index("user_id") for cl in s.configs}
        ref_name, ref = next(iter(frames.items()))
        for cl, f in frames.items():
            if set(f.index) != set(ref.index):
                errors.append(f"split {sl}: himpunan user_id uji {cl} != {ref_name} "
                              f"({len(set(f.index) ^ set(ref.index))} akun berbeda)")
            elif not (f.loc[ref.index, "y_true"].to_numpy() == ref["y_true"].to_numpy()).all():
                errors.append(f"split {sl}: y_true per akun {cl} != {ref_name}")
    if errors:
        raise AblationError("Validasi masukan gagal:\n  - " + "\n  - ".join(errors))
    return {k: v.astype({"y_true": int, "y_pred": int}) for k, v in cells.items()}


def read_optional_csv(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path) if path.exists() else None
