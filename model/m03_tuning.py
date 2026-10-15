"""m03 -- tuning K dengan 5-fold CV pada data latih."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.neighbors import KNeighborsClassifier

import common as C


def knn(k: int, cfg: dict) -> KNeighborsClassifier:
    p = cfg["knn"]
    return KNeighborsClassifier(n_neighbors=int(k), metric=p["metric"], weights=p["weights"], algorithm=p["algorithm"])


def make_folds(y: np.ndarray, cfg: dict, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    t = cfg["tuning"]
    shuffle = bool(t["cv_shuffle"])
    rs = seed if shuffle else None
    splitter = (StratifiedKFold if t["cv_stratified"] else KFold)(n_splits=int(t["cv_folds"]), shuffle=shuffle, random_state=rs)
    return [(tr, va) for tr, va in splitter.split(np.zeros((len(y), 1)), y)]


def fold_scores(y_true: np.ndarray, y_pred: np.ndarray, cfg: dict) -> dict:
    zd, pos = cfg["evaluation"]["zero_division"], cfg["run"]["positive_label"]
    return {
        "f1": f1_score(y_true, y_pred, pos_label=pos, zero_division=zd),
        "f1_macro": f1_score(y_true, y_pred, labels=[0, 1], average="macro", zero_division=zd),
        "precision": precision_score(y_true, y_pred, pos_label=pos, zero_division=zd),
        "recall": recall_score(y_true, y_pred, pos_label=pos, zero_division=zd),
        "accuracy": accuracy_score(y_true, y_pred),
    }


def cv_literal(X: np.ndarray, y: np.ndarray, cfg: dict, seed: int, n_original: int | None = None) -> pd.DataFrame:
    """CV pada (X, y) apa adanya."""
    rows = []
    folds = make_folds(y, cfg, seed)
    for k in cfg["tuning"]["k_grid"]:
        for i, (tr, va) in enumerate(folds):
            pred = knn(k, cfg).fit(X[tr], y[tr]).predict(X[va])
            rows.append({"k": k, "fold": i, "n_fold_train": len(tr), "n_fold_val": len(va),
                         "n_val_pos": int((y[va] == 1).sum()),
                         "n_val_synthetic": None if n_original is None else int((va >= n_original).sum()),
                         **fold_scores(y[va], pred, cfg)})
    return pd.DataFrame(rows)


def select_k(table: pd.DataFrame, cfg: dict) -> dict:
    """K dengan rata-rata macro-F1 antar-fold tertinggi; seri (< 1e-9) -> tie_break."""
    ddof = int(cfg["tuning"]["weak_selection_std_ddof"])
    g = table.groupby("k")["f1_macro"]
    mean, std = g.mean(), g.std(ddof=ddof)
    ks = [int(k) for k in cfg["tuning"]["k_grid"]]
    best_mean = max(float(mean[k]) for k in ks)
    tied = [k for k in ks if best_mean - float(mean[k]) < C.TIE_EPS]
    best = max(tied) if cfg["tuning"]["tie_break"] == "larger_k" else min(tied)
    others = [k for k in ks if k != best]
    runner = max(others, key=lambda k: (float(mean[k]), k if cfg["tuning"]["tie_break"] == "larger_k" else -k))
    gap = float(mean[best]) - float(mean[runner])
    out = {"best_k": best, "best_f1_macro_mean": float(mean[best]), "best_f1_macro_std": float(std[best]),
           "runner_up_k": runner, "runner_up_f1_macro_mean": float(mean[runner]), "gap_f1_macro": gap,
           "tie_at_best": len(tied) > 1, "weak_k_selection": gap < float(std[best])}
    for k in ks:
        out[f"f1_macro_mean_k{k}"], out[f"f1_macro_std_k{k}"] = float(mean[k]), float(std[k])
    return out
