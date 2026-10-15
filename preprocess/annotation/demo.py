"""Demo pelabelan manual (tanpa membekukan apa pun)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import llm
from .common import (FIELDS, AnnotationError, label_studio_config, ls_task, read_clean_data, read_csv_str,
                     read_ls_export, write_csv, write_json)
from .labels import load_rules


def demo_dir(cfg: dict) -> Path:
    return cfg["_base"] / "demo"


def future_subset_ids(cfg: dict, clean: pd.DataFrame) -> set[str]:
    """Akun yang akan dipilih A1 resmi dengan config dan data saat ini (logika identik dengan a1_sample_subset)."""
    n = round(cfg["subset"]["fraction"] * len(clean))
    return set(clean.sort_values("user_id").sample(n=n, random_state=cfg["subset"]["seed"]).user_id)


def build(cfg: dict, n: int = 12) -> pd.DataFrame:
    """Pilih n akun demo di luar subset resmi."""
    clean, _ = read_clean_data(cfg)
    excluded = future_subset_ids(cfg, clean)
    pool = clean[~clean.user_id.isin(excluded)].sort_values("user_id")
    seed = cfg["subset"]["seed"] + 1
    relevant = pool[pool.caption_text.str.contains("prabowo", case=False)]
    part1 = relevant.sample(n=min(n // 2, len(relevant)), random_state=seed)
    part2 = pool.drop(part1.index).sample(n=n - len(part1), random_state=seed)
    demo = pd.concat([part1, part2]).sample(frac=1, random_state=seed)
    assert not set(demo.user_id) & excluded

    d = demo_dir(cfg)
    write_json(d / "demo_tasks.json", [ls_task(r, cfg) for _, r in demo.iterrows()])
    (d / "label_studio_config_demo.xml").write_text(label_studio_config(cfg, with_ku_ip=True), encoding="utf-8")
    write_csv(demo[["user_id"] + cfg["input"]["annotation_input_columns"]], d / "demo_accounts.csv")
    print(f"{len(demo)} akun demo (di luar {len(excluded)} akun subset resmi) -> {d}")
    print("Label Studio: proyek baru 'DEMO - pelabelan'; template = label_studio_config_demo.xml; impor demo_tasks.json;\n"
          "ekspor JSON ke annotation\\exports\\demo.json, lalu jalankan pemeriksaan demo.")
    return demo


def check(cfg: dict, export_path: Path) -> pd.DataFrame:
    """Periksa ekspor demo: struktur dan enum seperti A1b (gagal -> AnnotationError), lalu Tabel 4 dan IP3 kolom sebagai
    laporan (tidak memblokir)."""
    accounts = demo_dir(cfg) / "demo_accounts.csv"
    if not accounts.exists():
        raise AnnotationError("Demo belum dibuat. Jalankan dulu: python -m annotation demo")
    expected = set(read_csv_str(accounts).user_id)
    df = read_ls_export(Path(export_path), expected, cfg)
    clean, _ = read_clean_data(cfg)
    by_id = clean.set_index("user_id", drop=False)
    rules = load_rules(cfg["_base"] / cfg["rules"]["path"])
    rows = []
    for _, r in df.iterrows():
        rec = {f: (r[f] or None) for f in FIELDS}
        chk = llm.rule_check(rec, by_id.loc[r.user_id], cfg, rules)
        rows.append({"user_id": r.user_id, **{f: r[f] for f in FIELDS}, "label_tabel4": chk["derived_label"],
                     "sesuai_tabel4": not chk["rule_inconsistent"], "ip3_kolom": chk["ip3_code"],
                     "ip3_sesuai": not chk["ip3_mismatch"]})
    out = pd.DataFrame(rows)
    n_bad = int((~out.sesuai_tabel4).sum())
    print(f"{len(out)} akun dianotasi. Label tidak sesuai Tabel 4: {n_bad}"
          f"{' (pada alur resmi, impor akan DITOLAK sampai diperbaiki)' if n_bad else ''}; "
          f"IP3 berbeda dari kolom: {int((~out.ip3_sesuai).sum())}.")
    print("Distribusi label:", out.label.value_counts().to_dict())
    return out


def warn_overlap(cfg: dict, subset_ids: set[str]) -> None:
    """Dipanggil A1 resmi: peringatan bila akun demo ternyata masuk subset (mis. seed atau data berubah)."""
    accounts = demo_dir(cfg) / "demo_accounts.csv"
    if accounts.exists():
        overlap = set(read_csv_str(accounts).user_id) & subset_ids
        if overlap:
            print(f"PERINGATAN: {len(overlap)} akun demo masuk subset resmi ({sorted(overlap)[:5]}). Akun ini sudah "
                  f"pernah Anda labeli dengan pedoman draf; pertimbangkan sebelum GATE 1.")
