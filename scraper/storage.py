"""Lapisan penyimpanan."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import config


def ensure_dirs() -> None:
    for d in (
        config.DISCOVERY_RAW,
        config.PROFILE_RAW,
        config.FEED_RAW,
        config.ENGAGEMENT_RAW,
        config.PROCESSED_DIR,
        config.CHECKPOINT_DIR,
        config.LOG_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def dump_raw_response(directory: Path, identifier: str, payload: dict) -> Path:
    """Simpan response GraphQL mentah apa adanya."""
    directory.mkdir(parents=True, exist_ok=True)
    out_path = directory / f"{identifier}.json"
    if out_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out_path = directory / f"{identifier}_{stamp}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return out_path


def raw_artifact_path(directory: Path, identifier: str, suffix: str) -> Path:
    """Kembalikan path artefak raw yang tidak menimpa bukti sebelumnya."""
    directory.mkdir(parents=True, exist_ok=True)
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    out_path = directory / f"{identifier}{normalized_suffix}"
    if out_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out_path = directory / f"{identifier}_{stamp}{normalized_suffix}"
    return out_path


def append_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_checkpoint_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        return set(json.load(f))


def save_checkpoint_set(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


def mark_done(path: Path, identifier: str) -> None:
    """Tambahkan satu identifier ke checkpoint dan langsung simpan."""
    seen = load_checkpoint_set(path)
    seen.add(identifier)
    save_checkpoint_set(path, seen)


def unmark_done(path: Path, identifier: str) -> None:
    """Kebalikan mark_done -- hapus identifier dari checkpoint."""
    seen = load_checkpoint_set(path)
    seen.discard(identifier)
    save_checkpoint_set(path, seen)


def load_feed_checkpoint(path: Path) -> dict:
    """Muat status feed per akun/tab; checkpoint list legacy dianggap kosong."""
    if not path.exists():
        return {"version": 2, "accounts": {}}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), dict):
        return {"version": 2, "accounts": {}}
    return payload


def save_feed_checkpoint(path: Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2, sort_keys=True)
