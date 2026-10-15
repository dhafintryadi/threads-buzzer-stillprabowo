"""Orkestrasi 9 sel (3 split x 3 konfigurasi), urutan."""

from __future__ import annotations

import argparse
import sys

import pandas as pd

import common as C
import m00_checks as M0
import m01_scaling_diagnostics as M1
import m02_imbalance as M2
import m03_tuning as M3
import m04_train_eval as M4


def freeze(cfg: dict) -> dict:
    man = C.read_manifest(cfg)
    if (man.get("evaluation") or {}).get("started_utc"):
        raise C.ModelError("Evaluasi run_id ini sudah berjalan; config tidak boleh dibekukan ulang. Buat run_id baru.")
    history = list(man.get("config_freeze_history", []))
    if man.get("config_sha256"):
        history.append({"config_sha256": man["config_sha256"], "frozen_utc": man.get("config_frozen_utc")})
    sha = C.config_sha256(cfg)
    out = C.update_manifest(cfg, config_sha256=sha, config=C.public(cfg), config_path=cfg["_config_path"],
                            config_frozen_utc=C.utc_now(), config_freeze_history=history,
                            proposals=C.proposals_used(cfg), supersedes=cfg["run"].get("supersedes"),
                            versions=C.versions(), lockfile=_lockfile())
    C.log.info("[freeze] config_sha256=%s", sha)
    return out


def _lockfile() -> dict:
    p = C.ROOT / "requirements.lock.txt"
    return {"path": str(p), "sha256": C.sha256_file(p) if p.exists() else None}


def load_all(cfg: dict) -> dict:
    return {s: C.load_split(cfg, s) for s in cfg["splits"]}


def tune_phase(cfg: dict, data: dict) -> tuple[list[dict], dict]:
    """m02 + m03 untuk 9 sel."""
    cells, cv_rows, best, smote_rows, decisions = [], [], [], [], {}
    for s in cfg["splits"]:
        train = data[s].train
        decision = M2.imbalance_decision(train[cfg["run"]["label_col"]].to_numpy(dtype=int), cfg)
        decisions[s] = decision
        C.cell_log("m02", s, None, n_train=decision["n_train"], minority_share=round(decision["minority_share"], 4),
                   threshold=decision["threshold"], smote=decision["imbalanced"])
        for conf in cfg["feature_configs"]:
            X, y = C.matrix(train, cfg, conf)
            Xr, yr, info = M2.resample(X, y, cfg, decision, C.derive_seed(cfg, "smote", s, conf))
            smote_rows.append({"split": s, "config": conf, **{k: decision[k] for k in
                               ("minority_share", "threshold", "imbalanced")}, **info})
            C.cell_log("m02", s, conf, n_before=info["n_before"], n_after=info["n_after"], synthetic=info["n_synthetic"])

            cv_seed = C.derive_seed(cfg, "cv", s, conf)
            table = M3.cv_literal(Xr, yr, cfg, cv_seed, n_original=len(y))
            sel = M3.select_k(table, cfg)
            cv_rows.append(table.assign(split=s, config=conf, cv_mode="acc_literal", cv_seed=cv_seed))
            best.append({"split": s, "config": conf, "cv_mode": "acc_literal", "cv_seed": cv_seed, **sel})
            C.cell_log("m03", s, conf, n=len(yr), best_k=sel["best_k"], f1_macro=round(sel["best_f1_macro_mean"], 4),
                       weak=sel["weak_k_selection"])
            cells.append({"split": s, "config": conf, "X_train": Xr, "y_train": yr, "k": sel["best_k"],
                          "train_sha256": C.sha256_array(Xr, yr)})

    lead = ["split", "config", "cv_mode", "cv_seed", "k", "fold"]
    out = {
        "cv_results": _lead(pd.concat(cv_rows, ignore_index=True), lead),
        "best_k": pd.DataFrame(best), "smote_log": pd.DataFrame(smote_rows), "decisions": decisions,
    }
    return cells, out


def _lead(df: pd.DataFrame, lead: list[str]) -> pd.DataFrame:
    return df[lead + [c for c in df.columns if c not in lead]]


def write_tuning(cfg: dict, cells: list[dict], out: dict) -> None:
    for name in ("cv_results", "best_k", "smote_log"):
        C.write_csv(cfg, f"{name}.csv", out[name])
    C.update_manifest(cfg, tuning={
        "completed_utc": C.utc_now(), "config_sha256": C.config_sha256(cfg),
        "cv_mode": cfg["tuning"]["cv_mode"],
        "smote_decision_per_split": {str(s): d for s, d in out["decisions"].items()},
        "cells": [{"split": c["split"], "config": c["config"], "k": c["k"], "n_train_fit": len(c["y_train"]),
                   "train_matrix_sha256": c["train_sha256"]} for c in cells],
    })


def tune(cfg: dict) -> pd.DataFrame:
    """Tuning saja (CV pada data latih)."""
    M0.require(cfg)
    M4.check_lock(cfg)
    M1.run(cfg)
    cells, out = tune_phase(cfg, load_all(cfg))
    write_tuning(cfg, cells, out)
    return out["best_k"]


def run(cfg: dict) -> dict:
    M0.require(cfg, need_config_hash=True)
    M4.check_lock(cfg)
    M1.run(cfg)
    data = load_all(cfg)
    cells, out = tune_phase(cfg, data)
    write_tuning(cfg, cells, out)
    return M4.evaluate(cfg, cells, data)


def checks(cfg: dict) -> int:
    res = M0.run_checks(cfg)
    print(M0.format_gates(res))
    data_ok = all(g["status"] == M0.PASS for g in res["gates"][2:6])
    if data_ok:
        M1.run(cfg)
        print(f"\nscaling_diagnostics.csv -> {C.run_dir(cfg)}")
    else:
        print("\nm01 dilewati: gerbang data (3-6) belum lulus.")
    return 0 if res["gates_1_6_passed"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["checks", "freeze", "tune", "run"])
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    C.setup_logging()
    cfg = C.load_config(args.config)
    try:
        if args.command == "checks":
            return checks(cfg)
        if args.command == "freeze":
            freeze(cfg)
            return 0
        if args.command == "tune":
            tune(cfg)
            return 0
        run(cfg)
        return 0
    except C.ModelError as e:
        print(f"\nBERHENTI: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
