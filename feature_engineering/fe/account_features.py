"""lima fitur akun, row-wise (tidak ada parameter yang di-fit)."""

from __future__ import annotations

import pandas as pd

ACCOUNT_FEATURES = ["pengikut", "rasio_balasan", "rasio_unggahan_ulang", "threads_topik", "balasan_topik"]


def compute_account_features(df: pd.DataFrame) -> pd.DataFrame:
    """df berkolom standar (lihat validate.REQUIRED) -> user_id + 5 fitur akun."""
    items = df["items_scanned"].astype(float)
    return pd.DataFrame({
        "user_id": df["user_id"].to_numpy(),
        "pengikut": df["follower_count"].astype(float).to_numpy(),
        "rasio_balasan": (df["replies_count"].astype(float) / items).to_numpy(),
        "rasio_unggahan_ulang": (df["repost_count"].astype(float) / items).to_numpy(),
        "threads_topik": df["topic_threads_count"].astype(float).to_numpy(),
        "balasan_topik": df["topic_replies_count"].astype(float).to_numpy(),
    })
