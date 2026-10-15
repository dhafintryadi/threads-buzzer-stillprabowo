"""Loader config terpusat."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "pipeline_config.yaml"


class ConfigError(Exception):
    pass


def load_config(config_path: Path | str | None = None) -> dict:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(f"File config tidak ditemukan: {path}")
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_config_path"] = str(path)
    return cfg


def resolve_path(cfg: dict, dotted_key: str) -> Path:
    """Resolusi path relatif dari config terhadap ROOT_DIR."""
    node = cfg
    for part in dotted_key.split("."):
        if part not in node:
            raise ConfigError(f"Key config '{dotted_key}' tidak ditemukan (berhenti di '{part}').")
        node = node[part]
    p = Path(node)
    return p if p.is_absolute() else (ROOT_DIR / p).resolve()


def config_path(cfg: dict) -> Path:
    return Path(cfg["_config_path"])


def require(cfg: dict, dotted_key: str, context: str = "") -> object:
    """Ambil parameter yang WAJIB sudah dikonfirmasi (bukan None/TODO) untuk menjalankan suatu tahap."""
    node = cfg
    for part in dotted_key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            break
    if node is None:
        suffix = f" ({context})" if context else ""
        raise ConfigError(
            f"Parameter config '{dotted_key}' belum dikonfirmasi (masih TODO/null){suffix}. "
            f"Isi nilainya di config/pipeline_config.yaml sebelum menjalankan tahap ini."
        )
    return node
