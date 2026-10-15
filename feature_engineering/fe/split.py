"""split acak, terpisah per rasio (bukan bersarang), stratified pada label, seed tetap per split."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .settings import seed_for, split_name


def make_splits(df: pd.DataFrame, cfg: dict) -> list[dict]:
    """Kembalikan daftar split: nama, test_size, seed, indeks posisi train/test (urut naik)."""
    positions = np.arange(len(df))
    labels = df["label"].astype(int).to_numpy()
    out = []
    for test_size in cfg["split"]["test_sizes"]:
        seed = seed_for(cfg, test_size)
        train_pos, test_pos = train_test_split(
            positions, test_size=test_size, random_state=seed, shuffle=True, stratify=labels
        )
        out.append({
            "name": split_name(test_size), "test_size": test_size, "seed": seed,
            "train_pos": np.sort(train_pos), "test_pos": np.sort(test_pos),
        })
    return out


def split_summary(df: pd.DataFrame, split: dict) -> dict:
    labels = df["label"].astype(int).to_numpy()
    tr, te = labels[split["train_pos"]], labels[split["test_pos"]]
    return {
        "seed": split["seed"],
        "test_size": split["test_size"],
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "buzzer_train": int(tr.sum()), "buzzer_test": int(te.sum()),
        "prop_buzzer_train": round(float(tr.mean()), 4), "prop_buzzer_test": round(float(te.mean()), 4),
    }
