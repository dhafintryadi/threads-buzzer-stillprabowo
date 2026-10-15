"""A1 -- ambil subset acak ±10% untuk dilabeli manual."""

from __future__ import annotations

from . import demo
from .common import FIELDS, add_manifest, label_studio_config, check_guideline, ls_task, paths, read_clean_data, refuse_overwrite, write_csv, write_json


def run(cfg: dict) -> dict:
    p = paths(cfg)
    refuse_overwrite(p.subset, "subset manual")
    guideline_sha = check_guideline(cfg, freeze=True)
    df, _ = read_clean_data(cfg)
    n = round(cfg["subset"]["fraction"] * len(df))
    seed = cfg["subset"]["seed"]
    subset = df.sort_values("user_id").sample(n=n, random_state=seed).sort_values("user_id")

    demo.warn_overlap(cfg, set(subset.user_id))
    out = subset[["user_id"] + cfg["input"]["annotation_input_columns"]].copy()
    for f in FIELDS:
        out[f"manual_{f}"] = ""
    out["annotator_id"] = ""
    write_csv(out, p.subset)
    write_json(p.manual_tasks, [ls_task(r, cfg) for _, r in subset.iterrows()])
    p.ls_config_manual.write_text(label_studio_config(cfg, with_ku_ip=True), encoding="utf-8")

    add_manifest(cfg, "a1_sample_subset", [p.clean_data, p.guideline, p.rules], [p.subset, p.manual_tasks, p.frozen_inputs],
                 {"n_population": len(df), "n_subset": n, "seed": seed, "method": "simple random sampling",
                  "guideline_sha256": guideline_sha})
    print(f"Subset: {n} dari {len(df)} akun = round({cfg['subset']['fraction']} x {len(df)}) (seed {seed}).")
    print(f"GATE 1 -- labeli subset sesuai pedoman, lewat salah satu jalur:\n"
          f"  Label Studio: config {p.ls_config_manual.name}, impor {p.manual_tasks.name}, ekspor JSON\n"
          f"  CSV         : isi manual_ku, manual_ip1..ip4, manual_label di {p.subset.name}\n"
          f"Lalu: python -m annotation a1b --labels <ekspor.json | subset.csv>")
    return {"n_subset": n}
