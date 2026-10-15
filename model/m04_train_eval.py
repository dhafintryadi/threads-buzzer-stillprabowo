"""m04 -- pelatihan akhir + evaluasi uji."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score

import common as C
import m00_checks as M0
from m03_tuning import knn


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, cfg: dict) -> dict:
    zd, pos = cfg["evaluation"]["zero_division"], cfg["run"]["positive_label"]
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel())
    n = tp + fp + fn + tn
    return {
        "n_test": n, "n_test_pos": tp + fn, "n_pred_pos": tp + fp,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "tp_pct": 100 * tp / n, "fp_pct": 100 * fp / n, "fn_pct": 100 * fn / n, "tn_pct": 100 * tn / n,
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, pos_label=pos, zero_division=zd),
        "recall": recall_score(y_true, y_pred, pos_label=pos, zero_division=zd),
        "f1": f1_score(y_true, y_pred, pos_label=pos, zero_division=zd),
        "f1_macro": f1_score(y_true, y_pred, labels=[0, 1], average="macro", zero_division=zd),
        "precision_undefined": tp + fp == 0, "recall_undefined": tp + fn == 0,
        "f1_undefined": 2 * tp + fp + fn == 0,
    }


def check_lock(cfg: dict) -> None:
    ev = C.read_manifest(cfg).get("evaluation") or {}
    if ev.get("started_utc"):
        raise C.ModelError(
            f"Evaluasi uji run_id {cfg['run']['run_id']!r} sudah dimulai {ev['started_utc']} (aturan satu kali). "
            "Perubahan setelah melihat metrik uji wajib memakai run_id baru dengan run.supersedes {run_id, reason}."
        )


def check_tuning_matches(cfg: dict) -> None:
    man = C.read_manifest(cfg)
    tuned = (man.get("tuning") or {}).get("config_sha256")
    if tuned != man.get("config_sha256"):
        raise C.ModelError("K dipilih dengan config yang berbeda dari config beku; jalankan ulang tahap tuning")


def evaluate(cfg: dict, cells: list[dict], data: dict) -> dict:
    """cells: keluaran tahap tuning (X/y latih hasil SMOTE + K terpilih)."""
    M0.require(cfg, need_config_hash=True)
    check_lock(cfg)
    check_tuning_matches(cfg)
    C.update_manifest(cfg, evaluation={"started_utc": C.utc_now(), "config_sha256": C.config_sha256(cfg)})

    metrics, cms, preds = [], [], []
    for cell in cells:
        s, conf, k = cell["split"], cell["config"], cell["k"]
        Xte, yte = C.matrix(data[s].test, cfg, conf)
        model = knn(k, cfg).fit(cell["X_train"], cell["y_train"])
        y_pred = model.predict(Xte)
        m = compute_metrics(yte, y_pred, cfg)
        metrics.append({"split": s, "split_name": data[s].name, "config": conf, "k": k,
                        "n_train_fit": len(cell["y_train"]), **m})
        for actual in (1, 0):
            for predicted in (1, 0):
                cms.append({"split": s, "config": conf, "actual": actual, "predicted": predicted,
                            "count": int(((yte == actual) & (y_pred == predicted)).sum())})
        preds.append(pd.DataFrame({"user_id": data[s].test["user_id"].astype(str).to_numpy(), "split": s,
                                   "config": conf, "y_true": yte, "y_pred": y_pred}))
        C.cell_log("m04", s, conf, k=k, n_test=m["n_test"], tp=m["tp"], fp=m["fp"], fn=m["fn"], tn=m["tn"])

    test_metrics = pd.DataFrame(metrics)
    if len(test_metrics) != 9 or test_metrics[["split", "config"]].duplicated().any():
        raise C.ModelError(f"test_metrics harus tepat 9 sel unik, ditemukan {len(test_metrics)}")
    C.write_csv(cfg, "test_metrics.csv", test_metrics)
    C.write_csv(cfg, "confusion_matrices.csv", pd.DataFrame(cms))
    C.write_csv(cfg, "test_predictions.csv", pd.concat(preds, ignore_index=True))

    if cfg["evaluation"]["report_baselines"]:
        base = []
        for s in cfg["splits"]:
            yte = data[s].test[cfg["run"]["label_col"]].to_numpy(dtype=int)
            base.append({"split": s, "split_name": data[s].name, "baseline": "selalu_non_buzzer",
                         **compute_metrics(yte, np.zeros_like(yte), cfg)})
        C.write_csv(cfg, "baselines.csv", pd.DataFrame(base))

    undefined = test_metrics.loc[test_metrics["precision_undefined"] | test_metrics["recall_undefined"],
                                 ["split", "config"]].to_dict("records")
    return C.update_manifest(cfg, evaluation={
        "started_utc": C.read_manifest(cfg)["evaluation"]["started_utc"], "completed_utc": C.utc_now(),
        "config_sha256": C.config_sha256(cfg), "cells": len(test_metrics),
        "undefined_precision_or_recall": undefined,
        "files": ["test_metrics.csv", "confusion_matrices.csv", "test_predictions.csv"]
                 + (["baselines.csv"] if cfg["evaluation"]["report_baselines"] else []),
    })
