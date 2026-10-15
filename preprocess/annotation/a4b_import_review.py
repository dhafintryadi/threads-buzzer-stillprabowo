"""A4b -- impor hasil tinjauan akun buzzer-LLM non-subset."""

from __future__ import annotations

from pathlib import Path

from . import llm
from .a3_annotate_full import frozen_prompt
from .a4_export_review import llm_full_labels, review_ids
from .common import FIELDS, POSITIVE, AnnotationError, add_manifest, paths, read_clean_data, read_csv_str, read_export_json, read_ls_export, write_csv


def run(cfg: dict, export_path: Path):
    p = paths(cfg)
    clean, _ = read_clean_data(cfg)
    frozen, _ = frozen_prompt(cfg, clean)
    labels = llm_full_labels(cfg, frozen, clean)
    expected = review_ids(cfg, labels)
    subset = set(read_csv_str(p.manual_subset).user_id)
    in_export = {str(t.get("data", {}).get("user_id", "")) for t in read_export_json(Path(export_path))}
    if in_export & subset:
        raise AnnotationError(f"I9: ekspor tinjauan memuat {len(in_export & subset)} akun subset manual "
                              f"(mis. {sorted(in_export & subset)[:5]}). Akun subset tidak ditinjau.")
    fill = cfg["review"]["fill_ku_ip"]
    df = read_ls_export(Path(export_path), expected, cfg, with_ku_ip=fill).rename(
        columns={**{f: f"review_{f}" for f in FIELDS}, "annotator_id": "reviewer_id", "labeled_at": "reviewed_at"})
    df["llm_label"] = POSITIVE
    df, rule_issues = llm.apply_manual_rules(df, "review_", clean, cfg) if fill else (df, {})
    df["review_changed_label"] = df.review_label != df.llm_label
    write_csv(df, p.review_labels)
    add_manifest(cfg, "a4b_import_review", [Path(export_path)], [p.review_labels],
                 {"n_reviewed": len(df), "n_changed": int(df.review_changed_label.sum()), "rule_check": rule_issues})
    print(f"{len(df)} tinjauan diimpor; {int(df.review_changed_label.sum())} dikoreksi menjadi non_buzzer.")
    print("Lanjut: python -m annotation a5")
    return df
