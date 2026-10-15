"""Tahap A langkah 1: muat input, petakan nama kolom, dan validasi."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .settings import FeatureEngineeringError

REQUIRED = [
    "user_id", "follower_count", "replies_count", "repost_count", "topic_threads_count",
    "topic_replies_count", "items_scanned", "caption_text", "caption_text_stream_t", "label",
]
COUNT_COLUMNS = ["follower_count", "replies_count", "repost_count", "topic_threads_count", "topic_replies_count", "items_scanned"]


def _ids(frame: pd.DataFrame, limit: int = 10) -> str:
    ids = frame["user_id"].astype(str).tolist()
    return ", ".join(ids[:limit]) + (f" ... (+{len(ids) - limit})" if len(ids) > limit else "")


def load_input(path: Path, cfg: dict) -> pd.DataFrame:
    """Baca input dan kembalikan frame dengan nama kolom standar (pemetaan `columns` di config)."""
    if not path.exists():
        raise FeatureEngineeringError(f"Input tidak ditemukan: {path}")
    mapping = cfg["columns"]
    unmapped = [c for c in REQUIRED if c not in mapping]
    if unmapped:
        raise FeatureEngineeringError(f"config.columns tidak memetakan kolom wajib: {unmapped}")
    raw = pd.read_csv(path, dtype={mapping["user_id"]: str}, encoding="utf-8")
    missing = {spec: actual for spec, actual in mapping.items() if spec in REQUIRED and actual not in raw.columns}
    if missing:
        raise FeatureEngineeringError(
            f"Kolom wajib tidak ditemukan di {path.name}: {missing} (nama standar -> nama di config). Header: {list(raw.columns)}"
        )
    return raw[[mapping[c] for c in REQUIRED]].set_axis(REQUIRED, axis=1)


def validate(df: pd.DataFrame, expected_rows: int | None) -> dict:
    """Validasi kontrak input; berhenti dengan daftar baris yang melanggar."""
    problems = []
    must_fill = [c for c in REQUIRED if c != "caption_text_stream_t"]
    nan = df[must_fill].isna()
    if nan.any().any():
        problems.append(f"nilai kosong pada kolom wajib {sorted(nan.columns[nan.any()])}: user_id {_ids(df[nan.any(axis=1)])}")

    numeric = df[COUNT_COLUMNS + ["label"]].apply(pd.to_numeric, errors="coerce")
    bad_num = numeric.isna() & ~nan[COUNT_COLUMNS + ["label"]]
    if bad_num.any().any():
        problems.append(f"nilai bukan angka pada {sorted(bad_num.columns[bad_num.any()])}: user_id {_ids(df[bad_num.any(axis=1)])}")
    else:
        checks = {
            "items_scanned > 0": numeric["items_scanned"] > 0,
            "0 <= replies_count <= items_scanned": numeric["replies_count"].between(0, numeric["items_scanned"]),
            "0 <= repost_count <= items_scanned": numeric["repost_count"].between(0, numeric["items_scanned"]),
            "hitungan lain >= 0": (numeric[["follower_count", "topic_threads_count", "topic_replies_count"]] >= 0).all(axis=1),
            "label di {0, 1}": numeric["label"].isin([0, 1]),
        }
        for name, ok in checks.items():
            ok = ok.fillna(False)
            if not ok.all():
                problems.append(f"{name} dilanggar: user_id {_ids(df[~ok])}")

    dup = df[df["user_id"].duplicated(keep=False)]
    if len(dup):
        problems.append(f"user_id tidak unik: {_ids(dup.drop_duplicates('user_id'))}")
    if expected_rows is not None and len(df) != expected_rows:
        problems.append(f"jumlah baris {len(df)} != expected_rows {expected_rows}")

    if problems:
        raise FeatureEngineeringError("Validasi input gagal (tidak diperbaiki otomatis):\n- " + "\n- ".join(problems))

    return {
        "rows": int(len(df)),
        "buzzer": int((df["label"] == 1).sum()),
        "non_buzzer": int((df["label"] == 0).sum()),
        "empty_caption_text_stream_t": int(df["caption_text_stream_t"].isna().sum()),
    }
