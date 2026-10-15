"""deteksi outlier (Tukey, pada data latih) dan pemilihan + fitting scaler pada data latih."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from .settings import FeatureEngineeringError


def outlier_summary(train: pd.DataFrame, features: list[str], cfg: dict) -> dict:
    o = cfg["outlier"]
    if o["rule"] != "tukey":
        raise FeatureEngineeringError(f"outlier.rule {o['rule']!r} tidak didukung (hanya 'tukey').")
    k = float(o["iqr_multiplier"])
    out = {}
    for f in features:
        v = train[f].astype(float)
        q1, q3 = float(v.quantile(0.25)), float(v.quantile(0.75))
        iqr = q3 - q1
        lo, hi = q1 - k * iqr, q3 + k * iqr
        prop = float(((v < lo) | (v > hi)).mean())
        out[f] = {
            "q1": q1, "q3": q3, "iqr": iqr, "lower": lo, "upper": hi,
            "outlier_prop": round(prop, 4), "eligible": iqr > 0,
            "above_threshold": bool(iqr > 0 and prop > float(o["prop_threshold"])),
        }
    return out


def choose_method(summary: dict, cfg: dict) -> dict:
    if cfg["scaler"]["rule"] != "more_than_one_outlier_feature_zscore_else_minmax":
        raise FeatureEngineeringError(f"scaler.rule {cfg['scaler']['rule']!r} tidak dikenal.")
    eligible = [f for f, s in summary.items() if s["eligible"]]
    above = [f for f in eligible if summary[f]["above_threshold"]]
    method = "zscore" if len(above) > 1 else "minmax"
    return {
        "method": method,
        "eligible_features": eligible,
        "excluded_iqr_zero": [f for f, s in summary.items() if not s["eligible"]],
        "above_threshold": above,
        "rule_note": f"{len(above)} dari {len(eligible)} fitur memenuhi syarat punya proporsi outlier > ambang",
    }


def fit_transform(train: pd.DataFrame, test: pd.DataFrame, features: list[str], method: str):
    scaler = StandardScaler() if method == "zscore" else MinMaxScaler()
    scaler.fit(train[features].to_numpy(dtype=float))
    tr = pd.DataFrame(scaler.transform(train[features].to_numpy(dtype=float)), columns=features, index=train.index)
    te = pd.DataFrame(scaler.transform(test[features].to_numpy(dtype=float)), columns=features, index=test.index)
    if method == "zscore":
        params = {f: {"mean": float(m), "std": float(s)} for f, m, s in zip(features, scaler.mean_, scaler.scale_)}
    else:
        params = {f: {"min": float(lo), "max": float(hi)} for f, lo, hi in zip(features, scaler.data_min_, scaler.data_max_)}
    for name, frame in (("train", tr), ("test", te)):
        if not np.isfinite(frame.to_numpy()).all():
            raise FeatureEngineeringError(f"NaN/inf pada fitur terskala ({name}).")
    return tr, te, params, scaler
