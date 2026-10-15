"""Run manifest: hash input/output tiap tahap, jumlah baris masuk/keluar/dihapus per tahap dengan alasan, versi library,
versi config, dan jumlah event per iterasi anotasi."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import storage

TRACKED_LIBRARIES = ["pandas", "PyYAML", "Sastrawi", "PySastrawi"]


def _library_versions() -> dict:
    versions = {"python": platform.python_version()}
    for lib in TRACKED_LIBRARIES:
        try:
            versions[lib] = importlib_metadata.version(lib)
        except importlib_metadata.PackageNotFoundError:
            versions[lib] = None
    return versions


def _file_hash_entry(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": None}
    return {"path": str(path), "exists": True, "sha256": storage.sha256_file(path)}


class RunManifest:
    def __init__(self, manifest_path: Path, config_path: Path | None = None):
        self.manifest_path = manifest_path
        self.config_path = config_path
        if manifest_path.exists():
            self._data = storage.read_json(manifest_path)
        else:
            self._data = {"stages": []}

    def add_stage(
        self,
        stage_name: str,
        inputs: list[Path],
        outputs: list[Path],
        rows_in: int | None = None,
        rows_out: int | None = None,
        rows_dropped: list[dict] | None = None,
        extra: dict | None = None,
    ) -> None:
        entry = {
            "stage": stage_name,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "inputs": [_file_hash_entry(p) for p in inputs],
            "outputs": [_file_hash_entry(p) for p in outputs],
            "rows_in": rows_in,
            "rows_out": rows_out,
            "rows_dropped": rows_dropped or [],
            "library_versions": _library_versions(),
            "config_sha256": storage.sha256_file(self.config_path) if self.config_path and self.config_path.exists() else None,
            "argv": sys.argv,
            "extra": extra or {},
        }
        self._data["stages"].append(entry)
        storage.write_json(self.manifest_path, self._data)

    def all_stages(self) -> list[dict]:
        return self._data.get("stages", [])
