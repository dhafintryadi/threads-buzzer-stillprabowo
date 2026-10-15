"""Metrik dari hitungan TP/FP/FN/TN."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import f1_score

PER_CLASS = ["presisi_buzzer", "recall_buzzer", "f1_buzzer",
             "presisi_non_buzzer", "recall_non_buzzer", "f1_non_buzzer"]
UNDEF_METRICS = PER_CLASS + ["spesifisitas", "makro_f1", "akurasi"]


def confusion(y_true: np.ndarray, y_pred: np.ndarray, positive: int = 1) -> dict:
    yt, yp = np.asarray(y_true) == positive, np.asarray(y_pred) == positive
    return {"tp": int((yt & yp).sum()), "fp": int((~yt & yp).sum()),
            "fn": int((yt & ~yp).sum()), "tn": int((~yt & ~yp).sum())}


def _ratio(num: int, den: int) -> tuple[float, bool]:
    return (num / den, False) if den else (0.0, True)


def metrics_from_counts(tp: int, fp: int, fn: int, tn: int) -> dict:
    n = tp + fp + fn + tn
    vals, undef = {}, {}
    vals["presisi_buzzer"], undef["presisi_buzzer"] = _ratio(tp, tp + fp)
    vals["recall_buzzer"], undef["recall_buzzer"] = _ratio(tp, tp + fn)
    vals["f1_buzzer"], undef["f1_buzzer"] = _ratio(2 * tp, 2 * tp + fp + fn)
    vals["presisi_non_buzzer"], undef["presisi_non_buzzer"] = _ratio(tn, tn + fn)
    vals["recall_non_buzzer"], undef["recall_non_buzzer"] = _ratio(tn, tn + fp)
    vals["f1_non_buzzer"], undef["f1_non_buzzer"] = _ratio(2 * tn, 2 * tn + fn + fp)
    vals["spesifisitas"], undef["spesifisitas"] = vals["recall_non_buzzer"], undef["recall_non_buzzer"]
    vals["makro_f1"] = (vals["f1_buzzer"] + vals["f1_non_buzzer"]) / 2
    undef["makro_f1"] = undef["f1_buzzer"] or undef["f1_non_buzzer"]
    vals["akurasi"], undef["akurasi"] = _ratio(tp + tn, n)
    out = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n_test": n,
           "support_buzzer": tp + fn, "support_non_buzzer": tn + fp, **vals}
    out.update({f"{k}_tak_terdefinisi": bool(undef[k]) for k in UNDEF_METRICS})
    out["tak_terdefinisi"] = ";".join(k for k in UNDEF_METRICS if undef[k])
    return out


def sklearn_macro_f1(y_true, y_pred) -> float:
    return float(f1_score(y_true, y_pred, labels=[0, 1], average="macro", zero_division=0))


def std_sample(values, ddof: int) -> float:
    """Simpangan baku dengan ddof EKSPLISIT (numpy default ddof=0, pandas default ddof=1)."""
    return float(np.std(np.asarray(values, dtype=float), ddof=ddof))


def majority_baseline(n_pos: int, n_neg: int) -> dict:
    """Prediksi semua = kelas mayoritas."""
    majority = 0 if n_neg >= n_pos else 1
    n = n_pos + n_neg
    if majority == 0:
        m = metrics_from_counts(tp=0, fp=0, fn=n_pos, tn=n_neg)
    else:
        m = metrics_from_counts(tp=n_pos, fp=n_neg, fn=0, tn=0)
    p = max(n_pos, n_neg) / n
    return {"kelas_mayoritas": "non_buzzer" if majority == 0 else "buzzer", "p": p,
            "akurasi_rumus": p, "makro_f1_rumus": p / (1 + p), **m}
