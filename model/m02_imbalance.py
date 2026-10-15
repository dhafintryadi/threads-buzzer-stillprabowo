"""m02 -- cek ketidakseimbangan kelas dan SMOTE bersyarat."""

from __future__ import annotations

import numpy as np

import common as C


def imbalance_decision(y: np.ndarray, cfg: dict) -> dict:
    """Keputusan per split dari label latih (sama untuk ketiga konfigurasi)."""
    pos = cfg["run"]["positive_label"]
    n_pos, n = int((y == pos).sum()), len(y)
    counts = {0: n - n_pos, 1: n_pos}
    minority = min(counts, key=lambda k: (counts[k], k))
    share = counts[minority] / n
    thr = float(cfg["imbalance"]["minority_share_threshold"])
    return {"n_train": n, "n_pos": n_pos, "n_neg": n - n_pos, "minority_class": minority,
            "minority_share": share, "threshold": thr, "imbalanced": share < thr}


def smote_class():
    try:
        from imblearn.over_sampling import SMOTE
    except ImportError as e:  # pragma: no cover - bergantung lingkungan
        raise C.ModelError(
            "imbalanced-learn belum terpasang, padahal SMOTE dibutuhkan (data latih tidak seimbang). "
            "Pasang dependensi dari requirements.lock.txt."
        ) from e
    return SMOTE


def apply_smote(X: np.ndarray, y: np.ndarray, cfg: dict, seed: int) -> tuple[np.ndarray, np.ndarray]:
    k = int(cfg["smote"]["k_neighbors"])
    n_min = int(min((y == 0).sum(), (y == 1).sum()))
    if n_min <= k:
        raise C.ModelError(f"SMOTE: jumlah kelas minoritas latih ({n_min}) harus > k_neighbors ({k})")
    smote = smote_class()(sampling_strategy=cfg["smote"]["sampling_strategy"], k_neighbors=k, random_state=seed)
    Xr, yr = smote.fit_resample(np.array(X, dtype=float, copy=True), np.array(y, copy=True))
    return np.asarray(Xr, dtype=float), np.asarray(yr, dtype=int)


def resample(X: np.ndarray, y: np.ndarray, cfg: dict, decision: dict, seed: int) -> tuple[np.ndarray, np.ndarray, dict]:
    """SMOTE bersyarat."""
    if decision["imbalanced"]:
        Xr, yr = apply_smote(X, y, cfg, seed)
        if not np.array_equal(Xr[: len(X)], X) or not np.array_equal(yr[: len(y)], y):
            raise C.ModelError("SMOTE mengubah sampel asli; urutan keluaran imbalanced-learn tidak sesuai harapan")
    else:
        Xr, yr = np.array(X, copy=True), np.array(y, copy=True)
    info = {
        "smote_applied": bool(decision["imbalanced"]), "smote_seed": seed if decision["imbalanced"] else None,
        "n_before": len(y), "n_after": len(yr), "n_synthetic": len(yr) - len(y),
        "n_pos_before": int((y == 1).sum()), "n_neg_before": int((y == 0).sum()),
        "n_pos_after": int((yr == 1).sum()), "n_neg_after": int((yr == 0).sum()),
        "pos_share_after": float((yr == 1).mean()),
    }
    return Xr, yr, info
