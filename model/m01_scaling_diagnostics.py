"""m01 -- diagnostik penskalaan: DESKRIPTIF SAJA."""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import common as C


def diagnostics_for_split(train: pd.DataFrame, test: pd.DataFrame, method: str, name: str) -> pd.DataFrame:
    rows = []
    for c in C.FEATURES:
        xtr, xte = train[c].to_numpy(dtype=float), test[c].to_numpy(dtype=float)
        std_tr = float(xtr.std(ddof=0))
        constant = bool(np.ptp(xtr) == 0)
        z = xtr if method == "zscore" else (np.zeros_like(xtr) if constant else (xtr - xtr.mean()) / std_tr)
        n_z3 = int((np.abs(z) > 3).sum())
        lo, hi = float(xtr.min()), float(xtr.max())
        n_out = int(((xte < lo) | (xte > hi)).sum())
        rows.append({
            "split": name, "feature": c, "method_fe": method,
            "train_mean": float(xtr.mean()), "train_std": std_tr, "train_min": lo, "train_max": hi,
            "test_mean": float(xte.mean()), "test_std": float(xte.std(ddof=0)),
            "test_min": float(xte.min()), "test_max": float(xte.max()),
            "n_train": len(xtr), "n_test": len(xte),
            "train_abs_z_gt3_n": n_z3, "train_abs_z_gt3_share": n_z3 / len(xtr),
            "train_constant": constant,
            "test_outside_train_range_n": n_out, "test_outside_train_range_share": n_out / len(xte),
        })
    out = pd.DataFrame(rows)
    out["n_constant_features_split"] = int(out["train_constant"].sum())
    return out


def run(cfg: dict) -> pd.DataFrame:
    report = C.read_fe_report(cfg)
    methods = (report.get("scaling_status") or {}).get("method_per_split") or {}
    parts = []
    for s in cfg["splits"]:
        data = C.load_split(cfg, s)
        method = methods.get(data.name)
        if method not in ("zscore", "minmax"):
            raise C.ModelError(f"{data.name}: metode penskalaan FE tidak diketahui di laporan FE ({method!r})")
        d = diagnostics_for_split(data.train, data.test, method, data.name)
        C.cell_log("m01", s, None, method=method, n_train=len(data.train), n_test=len(data.test),
                   constant=int(d["train_constant"].sum()), test_out_of_range=int(d["test_outside_train_range_n"].sum()))
        parts.append(d)
    out = pd.concat(parts, ignore_index=True)
    C.write_csv(cfg, "scaling_diagnostics.csv", out)
    C.update_manifest(cfg, scaling_diagnostics={"written_utc": C.utc_now(), "rows": len(out),
                                                "method_per_split": {s: methods.get(C.split_name(cfg, s)) for s in cfg["splits"]}})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="m01: diagnostik penskalaan (deskriptif)")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    C.setup_logging()
    run(C.load_config(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
