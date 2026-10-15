"""Metrik dan keputusan loop optimasi (fungsi murni)."""

from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd

from .common import POSITIVE


def confusion(y_true, y_pred) -> dict:
    pairs = list(zip(y_true, y_pred))
    return {"tp": sum(t == POSITIVE and p == POSITIVE for t, p in pairs),
            "fp": sum(t != POSITIVE and p == POSITIVE for t, p in pairs),
            "fn": sum(t == POSITIVE and p != POSITIVE for t, p in pairs),
            "tn": sum(t != POSITIVE and p != POSITIVE for t, p in pairs)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - w) / d, (c + w) / d


def set_metrics(y_true, y_pred) -> dict:
    """Recall kelas buzzer (gerbang) + metrik pelaporan."""
    m = confusion(y_true, y_pred)
    pos = m["tp"] + m["fn"]
    recall = m["tp"] / pos if pos else math.nan
    precision = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else math.nan
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else math.nan
    lo, hi = wilson(m["tp"], pos)
    return {"n": len(list(y_true)), "positives": pos, **m, "recall": recall,
            "recall_ci_low": lo, "recall_ci_high": hi, "precision": precision, "f1": f1}


def min_tp_for_recall(n_pos: int, threshold: float) -> int:
    """TP minimum agar recall >= ambang pada n_pos positif (aritmetika desimal, tanpa galat float)."""
    return math.ceil(Decimal(str(threshold)) * n_pos)


def threshold_note(n_pos: int, threshold: float) -> str:
    if n_pos == 0:
        return "0 buzzer: recall tidak terdefinisi"
    k = min_tp_for_recall(n_pos, threshold)
    lo, _ = wilson(n_pos, n_pos)
    return (f"{n_pos} buzzer: recall >= {threshold} butuh TP >= {k} (boleh terlewat {n_pos - k}); "
            f"bahkan bila semua tertangkap, CI Wilson 95% recall = {lo:.2f}-1.00")


def decide(rounds: pd.DataFrame, threshold: float, max_optimizations: int, freeze_on_limit: str = "best_validation") -> dict:
    """Keputusan setelah ronde terakhir, dari eval_rounds."""
    if "repeat" in rounds:
        rounds = rounds[rounds["repeat"].fillna(1).astype(int) == 1]
    val = rounds[rounds["set"] == "validation"].sort_values("round")
    last = val.iloc[-1]
    n_opt = len(val) - 1
    if float(last["recall"]) >= threshold:
        return {"action": "freeze", "threshold_met": True, "prompt_version": last["prompt_version"],
                "prompt_sha256": last["prompt_sha256"], "recall_validation": float(last["recall"]),
                "reason": f"recall validasi {float(last['recall']):.3f} >= {threshold}"}
    if n_opt >= max_optimizations:
        if freeze_on_limit == "last":
            best, how = last, "versi terakhir"
        else:
            best = val.assign(_r=val["recall"].astype(float).fillna(-1)).sort_values(["_r", "round"]).iloc[-1]
            how = "recall validasi tertinggi (seri -> terbaru)"
        return {"action": "freeze", "threshold_met": False, "prompt_version": best["prompt_version"],
                "prompt_sha256": best["prompt_sha256"], "recall_validation": float(best["recall"]),
                "reason": f"batas {max_optimizations} optimasi tercapai; dipilih {how}"}
    return {"action": "continue", "n_opt": n_opt,
            "reason": f"recall validasi {float(last['recall']):.3f} < {threshold}; optimasi {n_opt}/{max_optimizations}"}
