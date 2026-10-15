"""Pemuatan konfigurasi, resolusi path, dan pemuatan pembersihan bersama dari preprocess."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "feature_config.yaml"


class FeatureEngineeringError(Exception):
    """Pelanggaran kontrak input/konfigurasi: eksekusi dihentikan, tidak ada perbaikan diam-diam."""


def load_config(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FeatureEngineeringError(f"File config tidak ditemukan: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    cfg["_config_path"] = str(p)
    return cfg


def resolve(cfg: dict, key: str) -> Path:
    """Path dari `cfg['paths'][key]`, relatif terhadap folder feature_engineering/."""
    value = cfg["paths"].get(key)
    if value is None:
        raise FeatureEngineeringError(f"paths.{key} tidak ada di config.")
    p = Path(value)
    return p if p.is_absolute() else (ROOT_DIR / p).resolve()


def load_clean_shared(cfg: dict):
    """`clean_shared` dari preprocess/text_streams/shared_clean.py, dimuat lewat path supaya definisinya tunggal dan
    tidak bentrok dengan modul lain bernama `config`/`schema`."""
    path = resolve(cfg, "shared_clean_py")
    if not path.exists():
        raise FeatureEngineeringError(f"shared_clean.py tidak ditemukan: {path}")
    spec = importlib.util.spec_from_file_location("preprocess_shared_clean", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.clean_shared


def seed_for(cfg: dict, test_size: float) -> int:
    seeds = cfg["split"]["seeds"]
    key = f"{test_size:g}"
    if key not in seeds:
        raise FeatureEngineeringError(f"split.seeds tidak punya seed untuk test_size {key}.")
    return int(seeds[key])


def split_name(test_size: float) -> str:
    test_pct = round(test_size * 100)
    return f"split_{100 - test_pct}_{test_pct}"


def all_features(cfg: dict) -> list[str]:
    return list(cfg["features"]["akun"]) + list(cfg["features"]["teks"])
