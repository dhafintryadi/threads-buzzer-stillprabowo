"""A4 -- ekspor semua akun berlabel buzzer oleh LLM yang TIDAK ada di subset manual ke Label Studio."""

from __future__ import annotations

import pandas as pd

from . import llm
from .a3_annotate_full import frozen_prompt
from .common import (IP_FIELDS, POSITIVE, AnnotationError, add_manifest, label_studio_config, ls_task, paths, read_clean_data,
                     read_csv_str, write_json)


def llm_full_labels(cfg: dict, frozen: dict, clean: pd.DataFrame) -> pd.DataFrame:
    """Label anotasi penuh untuk setiap akun."""
    done = llm.ok_labels(cfg, frozen["prompt_sha256"], "full")
    missing = sorted(set(clean.user_id) - set(done.user_id))
    if missing:
        raise AnnotationError(f"I5: {len(missing)} akun belum punya label LLM ok dari prompt beku "
                              f"(mis. {missing[:5]}). Jalankan ulang: python -m annotation a3")
    return done[done.user_id.isin(set(clean.user_id))]


def review_ids(cfg: dict, labels: pd.DataFrame) -> set[str]:
    """Set tinjauan: akun buzzer-LLM di luar subset manual (I4, I9)."""
    subset = set(read_csv_str(paths(cfg).manual_subset).user_id)
    return set(labels.user_id[labels.label == POSITIVE]) - subset


def run(cfg: dict) -> int:
    p = paths(cfg)
    clean, _ = read_clean_data(cfg)
    frozen, _ = frozen_prompt(cfg, clean)
    labels = llm_full_labels(cfg, frozen, clean)
    ids = review_ids(cfg, labels)
    pos = labels.set_index("user_id")
    rows = clean[clean.user_id.isin(ids)].sort_values("user_id")
    rows = rows.sample(frac=1, random_state=cfg["review"]["shuffle_seed"])
    show_label, show_ku_ip = cfg["review"]["show_llm_label"], cfg["review"]["show_llm_ku_ip"]
    tasks = []
    for _, r in rows.iterrows():
        llm_fields = {f: pos.loc[r.user_id, f] for f in ("ku", *IP_FIELDS)}
        pred = ({"label": POSITIVE} if show_label else {}) | (llm_fields if show_ku_ip else {})
        tasks.append(ls_task(r, cfg, pred, f"{cfg['llm']['model']}/{frozen['prompt_version']}",
                             hidden={f"llm_{f}": v for f, v in llm_fields.items()}))
    write_json(p.review_tasks, tasks)
    p.ls_config_review.write_text(label_studio_config(cfg, with_ku_ip=cfg["review"]["fill_ku_ip"]), encoding="utf-8")
    n_subset_pos = int((labels.label == POSITIVE).sum()) - len(ids)
    add_manifest(cfg, "a4_export_review", [p.llm_calls, p.frozen, p.manual_subset], [p.review_tasks],
                 {"n_review": len(tasks), "llm_buzzer_in_subset_not_reviewed": n_subset_pos})
    print(f"{len(tasks)} akun buzzer-LLM di luar subset diekspor ke {p.review_tasks.name} "
          f"({n_subset_pos} akun buzzer-LLM lain ada di subset dan memakai label manual).")
    print(f"GATE 3 -- di Label Studio: config {p.ls_config_review.name}, impor {p.review_tasks.name}, "
          f"{'isi KU/IP lalu ' if cfg['review']['fill_ku_ip'] else ''}konfirmasi/koreksi label, ekspor JSON.\n"
          f"Lalu: python -m annotation a4b --export <ekspor.json>")
    return len(tasks)
