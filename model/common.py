"""Bersama untuk m00-m04: config + hash, validasi keputusan terkunci, pemuatan data (daftar putih), seed turunan,
manifest run, logging."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata as md
import json
import logging
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.yaml"

LOCKED_SPLITS = [70, 80, 90]
LOCKED_K_GRID = [3, 5, 7, 9]
LOCKED_CV_FOLDS = 5
LOCKED_FEATURE_CONFIGS = {
    "akun": ["pengikut", "rasio_balasan", "rasio_unggahan_ulang", "threads_topik", "balasan_topik"],
    "teks": ["similarity", "kepadatan_leksikon_a", "kepadatan_leksikon_b"],
}
LOCKED_FEATURE_CONFIGS["gabungan"] = LOCKED_FEATURE_CONFIGS["akun"] + LOCKED_FEATURE_CONFIGS["teks"]
FEATURES = LOCKED_FEATURE_CONFIGS["gabungan"]
LOCKED_KNN = {"metric": "euclidean", "weights": "uniform"}

VARIANTS = {"penyebut_token": "tokens"}

DECIDED_ITEMS = {1: "2026-10-15", 3: "2026-10-15", 4: "2026-10-15", 5: "2026-10-15", 11: "2026-10-15", 12: "2026-10-15"}

PROPOSALS = {
    "imbalance.minority_share_threshold": 2,
    "smote.sampling_strategy": 3,
    "smote.k_neighbors": 3,
    "tuning.selection_metric": 4,
    "tuning.cv_stratified": 5,
    "tuning.cv_shuffle": 5,
    "tuning.cv_mode": 5,
    "tuning.tie_break": 6,
    "tuning.weak_selection_std_ddof": None,
    "evaluation.report_baselines": 8,
    "run.random_state_global": 9,
}

TIE_EPS = 1e-9
SCALE_TOL = 1e-6

log = logging.getLogger("model")


class ModelError(Exception):
    """Kontrak/konfigurasi dilanggar: berhenti dengan pesan jelas, tanpa perbaikan diam-diam."""


class GateError(ModelError):
    pass


def setup_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        raise ModelError(f"Config tidak ditemukan: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    cfg["_config_path"] = str(p.resolve())
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    errors = []
    run = cfg.get("run", {})
    if run.get("input_variant") not in VARIANTS:
        errors.append(f"run.input_variant harus salah satu {sorted(VARIANTS)}")
    if run.get("positive_label") != 1:
        errors.append("run.positive_label harus 1 (buzzer)")
    if list(cfg.get("splits", [])) != LOCKED_SPLITS:
        errors.append(f"splits harus {LOCKED_SPLITS} (terkunci)")
    if sorted(cfg["input"]["split_dirs"]) != LOCKED_SPLITS:
        errors.append("input.split_dirs harus memetakan tepat 70, 80, 90")
    fc = cfg.get("feature_configs", {})
    if list(fc) != list(LOCKED_FEATURE_CONFIGS) or any(list(fc[k]) != v for k, v in LOCKED_FEATURE_CONFIGS.items()):
        errors.append(f"feature_configs harus tepat {LOCKED_FEATURE_CONFIGS} (terkunci)")
    t = cfg.get("tuning", {})
    if list(t.get("k_grid", [])) != LOCKED_K_GRID:
        errors.append(f"tuning.k_grid harus {LOCKED_K_GRID} (terkunci)")
    if t.get("cv_folds") != LOCKED_CV_FOLDS:
        errors.append(f"tuning.cv_folds harus {LOCKED_CV_FOLDS} (terkunci)")
    if t.get("cv_mode") != "acc_literal":
        errors.append("tuning.cv_mode harus acc_literal (in_fold tidak dipakai; keputusan 15 Okt 2026)")
    if t.get("selection_metric") != "f1_macro":
        errors.append("tuning.selection_metric harus f1_macro (terkunci)")
    if t.get("tie_break") not in ("larger_k", "smaller_k"):
        errors.append("tuning.tie_break harus larger_k | smaller_k")
    if t.get("weak_selection_std_ddof") not in (0, 1):
        errors.append("tuning.weak_selection_std_ddof harus 0 atau 1")
    for key, val in LOCKED_KNN.items():
        if cfg.get("knn", {}).get(key) != val:
            errors.append(f"knn.{key} harus {val!r} (terkunci)")
    if cfg.get("scaling", {}).get("performed_in") != "feature_engineering":
        errors.append("scaling.performed_in harus feature_engineering")
    k_smote = cfg.get("smote", {}).get("k_neighbors")
    if not isinstance(k_smote, int) or k_smote < 1:
        errors.append("smote.k_neighbors harus bilangan bulat >= 1")
    if not 0 < float(cfg.get("imbalance", {}).get("minority_share_threshold", -1)) <= 0.5:
        errors.append("imbalance.minority_share_threshold harus di (0, 0.5]")
    sup = run.get("supersedes")
    if sup is not None and not (isinstance(sup, dict) and sup.get("run_id") and sup.get("reason")):
        errors.append("run.supersedes harus null atau {run_id, reason}")
    if errors:
        raise ModelError("Config tidak valid:\n  - " + "\n  - ".join(errors))


def public(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


def config_sha256(cfg: dict) -> str:
    """SHA-256 isi config yang dinormalisasi (kunci terurut, tanpa komentar/format YAML)."""
    text = json.dumps(public(cfg), sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        node = node[part]
    return node


def proposals_used(cfg: dict) -> list[dict]:
    return [{"parameter": k, "value": get(cfg, k), "nomor_parameter": n,
             "status": f"diputuskan {DECIDED_ITEMS[n]}" if n in DECIDED_ITEMS else "usulan"}
            for k, n in PROPOSALS.items()]


def resolve(cfg: dict, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (Path(cfg["_config_path"]).parent / p).resolve()


def run_dir(cfg: dict) -> Path:
    return resolve(cfg, cfg["output_dir"]) / cfg["run"]["run_id"]


def split_name(cfg: dict, split: int) -> str:
    return cfg["input"]["split_dirs"][split]


def split_paths(cfg: dict, split: int) -> dict:
    d = resolve(cfg, cfg["input"]["root"]) / split_name(cfg, split)
    return {"train": d / cfg["input"]["train_file"], "test": d / cfg["input"]["test_file"]}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_array(*arrays) -> str:
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode() + str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def derive_seed(cfg: dict, *parts) -> int:
    """Seed deterministik dari seed global + tahap/split/konfigurasi (tidak bergantung PYTHONHASHSEED)."""
    key = "|".join(str(p) for p in (cfg["run"]["random_state_global"], *parts))
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:4], "big")


def versions() -> dict:
    out = {"python": platform.python_version()}
    for lib in ("scikit-learn", "imbalanced-learn", "numpy", "pandas", "PyYAML"):
        try:
            out[lib] = md.version(lib)
        except md.PackageNotFoundError:
            out[lib] = None
    return out


@dataclass(frozen=True)
class SplitData:
    split: int
    name: str
    train: pd.DataFrame
    test: pd.DataFrame
    paths: dict


def read_frame(path: Path, label_col: str) -> pd.DataFrame:
    if not Path(path).exists():
        raise ModelError(f"Berkas masukan tidak ditemukan: {path}")
    return pd.read_csv(path, dtype={"user_id": str})


def contract_problems(df: pd.DataFrame, cfg: dict, where: str) -> list[str]:
    """Pelanggaran daftar putih kolom, label, dan nilai fitur."""
    label = cfg["run"]["label_col"]
    allowed = ["user_id", label, *FEATURES]
    out = []
    extra = [c for c in df.columns if c not in allowed]
    missing = [c for c in allowed if c not in df.columns]
    if extra:
        out.append(f"{where}: kolom di luar daftar putih {extra}")
    if missing:
        out.append(f"{where}: kolom wajib tidak ada {missing}")
    if len(set(df.columns)) != len(df.columns):
        out.append(f"{where}: nama kolom ganda")
    if label in df.columns:
        vals = set(pd.unique(df[label]))
        if not vals <= {0, 1} or not pd.api.types.is_integer_dtype(df[label]):
            out.append(f"{where}: label harus bilangan bulat 0/1, ditemukan {sorted(map(str, vals))}")
    present = [c for c in FEATURES if c in df.columns]
    if present:
        try:
            x = df[present].to_numpy(dtype=float)
        except (TypeError, ValueError):
            out.append(f"{where}: fitur non-numerik")
        else:
            bad = {c: int((~np.isfinite(x[:, i])).sum()) for i, c in enumerate(present) if (~np.isfinite(x[:, i])).any()}
            if bad:
                out.append(f"{where}: NaN/inf pada fitur {bad}")
    if "user_id" in df.columns and df["user_id"].isna().any():
        out.append(f"{where}: user_id kosong")
    return out


def load_split(cfg: dict, split: int) -> SplitData:
    paths = split_paths(cfg, split)
    label = cfg["run"]["label_col"]
    train, test = read_frame(paths["train"], label), read_frame(paths["test"], label)
    problems = contract_problems(train, cfg, f"{split_name(cfg, split)}/train") + \
        contract_problems(test, cfg, f"{split_name(cfg, split)}/test")
    if not problems and set(pd.unique(pd.concat([train[label], test[label]]))) != {0, 1}:
        problems.append(f"{split_name(cfg, split)}: label harus memuat tepat {{0, 1}}")
    if problems:
        raise ModelError("Kontrak berkas FE dilanggar:\n  - " + "\n  - ".join(problems))
    return SplitData(split, split_name(cfg, split), train, test, paths)


def matrix(df: pd.DataFrame, cfg: dict, config: str) -> tuple[np.ndarray, np.ndarray]:
    """Matriks fitur hanya dari nama kolom eksplisit konfigurasi (tanpa memutasi df)."""
    cols = cfg["feature_configs"][config]
    return df[cols].to_numpy(dtype=float, copy=True), df[cfg["run"]["label_col"]].to_numpy(dtype=int, copy=True)


def read_fe_report(cfg: dict) -> dict:
    p = resolve(cfg, cfg["input"]["fe_manifest"])
    if not p.exists():
        raise ModelError(f"Laporan/manifest FE tidak ditemukan: {p} (input.fe_manifest)")
    return json.loads(p.read_text(encoding="utf-8"))


def manifest_path(cfg: dict) -> Path:
    return run_dir(cfg) / "run_manifest.json"


def read_manifest(cfg: dict) -> dict:
    p = manifest_path(cfg)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def update_manifest(cfg: dict, **fields) -> dict:
    data = read_manifest(cfg)
    data.setdefault("run_id", cfg["run"]["run_id"])
    data.setdefault("input_variant", cfg["run"]["input_variant"])
    data.setdefault("created_utc", utc_now())
    data.update(copy.deepcopy(fields))
    data["updated_utc"] = utc_now()
    p = manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return data


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    return str(o)


def write_csv(cfg: dict, name: str, df: pd.DataFrame) -> Path:
    p = run_dir(cfg) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return p


def cell_log(stage: str, split, config: str | None = None, **kv) -> None:
    parts = " ".join(f"{k}={v}" for k, v in kv.items())
    log.info("[%s] split=%s config=%s %s", stage, split, config or "-", parts)
