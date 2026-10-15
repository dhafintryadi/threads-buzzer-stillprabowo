"""Konversi MEKANIS leksikon peneliti (CSV) -> lexicon/lexicon_a.txt dan lexicon/lexicon_b.txt."""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = ("leksikon", "id", "entri", "varian_pencocokan")


def convert(csv_path: Path, out_dir: Path) -> dict:
    raw = csv_path.read_bytes()
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    missing = [c for c in REQUIRED if not rows or c not in rows[0]]
    if missing:
        raise SystemExit(f"Kolom wajib hilang di {csv_path.name}: {missing}")
    groups: dict[str, list[str]] = {"A": [], "B": []}
    for r in sorted(rows, key=lambda r: r["id"]):
        if r["leksikon"] not in groups:
            raise SystemExit(f"Entri {r['id']}: leksikon {r['leksikon']!r} bukan A/B.")
        if not r["entri"].strip():
            raise SystemExit(f"Entri {r['id']}: kolom entri kosong.")
        terms = [r["entri"]] + [v for v in (r["varian_pencocokan"] or "").split("|")]
        groups[r["leksikon"]] += [t.strip().lower() for t in terms if t.strip()]

    sha = hashlib.sha256(raw).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for key, terms in groups.items():
        path = out_dir / f"lexicon_{key.lower()}.txt"
        header = [
            f"# Dibuat mekanis dari {csv_path.name} (sha256 {sha[:16]}) oleh convert_lexicon_csv.py, {date.today().isoformat()}.",
            "# Aturan: semua entri leksikon " + key + "; istilah = entri + varian_pencocokan. Jangan edit manual: ubah CSV, lalu jalankan ulang.",
        ]
        path.write_text("\n".join(header + terms) + "\n", encoding="utf-8")
        written[key] = {"path": str(path), "terms": len(terms), "entries": sum(r["leksikon"] == key for r in rows)}
    return written


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, default=ROOT.parent / "data_inputs" / "leksikon_a_b_data_terseleksi.csv")
    p.add_argument("--out", type=Path, default=ROOT / "lexicon")
    args = p.parse_args()
    for key, info in convert(args.csv, args.out).items():
        print(f"leksikon {key}: {info['entries']} entri CSV -> {info['terms']} istilah -> {info['path']}")


if __name__ == "__main__":
    main()
