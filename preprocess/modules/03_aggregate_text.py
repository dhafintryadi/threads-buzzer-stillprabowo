"""Tahap 3: (diagnostik duplikasi."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
for _p in (_THIS_DIR, _ROOT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as cfgmod
import schema
import storage
from manifest import RunManifest


def build_duplicate_diagnostic_report(df_b: pd.DataFrame) -> pd.DataFrame:
    """: identifikasi akun dengan >1 unggahan."""
    counts = df_b.groupby("user_id").size().reset_index(name="post_count")
    return counts.sort_values(["post_count", "user_id"], ascending=[False, True]).reset_index(drop=True)


def dedup_pk(df_b: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    dup_cfg = cfg["duplicate_handling"]
    mode = dup_cfg["pk_duplicate_mode"]

    if mode == "identical_rows_only":
        return df_b.drop_duplicates(keep="first").copy()

    if mode == "tie_break":
        priority = {src: i for i, src in enumerate(dup_cfg["tie_break_source_priority"])}
        working = df_b.copy()
        working["_source_priority"] = working["source"].map(priority).fillna(len(priority))
        working = working.sort_values(
            by=["_source_priority", "taken_at_utc", "code"],
            ascending=[True, True, True],
            kind="stable",
        )
        deduped = working.drop_duplicates(subset=["pk"], keep="first")
        return deduped.drop(columns=["_source_priority"])

    raise ValueError(f"duplicate_handling.pk_duplicate_mode tidak dikenali: {mode!r}")


def aggregate_text(df_b: pd.DataFrame, separator: str) -> pd.DataFrame:
    working = df_b.copy()
    working["caption_text"] = working["caption_text"].fillna("")
    working = working[working["caption_text"].str.strip() != ""]
    working = working.sort_values(by=["taken_at_utc", "pk"], kind="stable")

    grouped = (
        working.groupby("user_id")["caption_text"]
        .apply(lambda texts: separator.join(texts))
        .reset_index()
    )
    return grouped[schema.TABLE_B_AGGREGATED_COLUMNS]


def run(cfg: dict) -> dict:
    table_a_path = cfgmod.resolve_path(cfg, "paths.table_a_clean_csv")
    table_b_path = cfgmod.resolve_path(cfg, "paths.table_b_cascaded_csv")

    df_a = schema.read_and_validate_csv(table_a_path, schema.TABLE_A_CLEAN_COLUMNS, ["user_id"], "Tabel A bersih")
    df_b = schema.read_and_validate_csv(table_b_path, schema.TABLE_B_TEKS_COLUMNS, schema.TABLE_B_STRING_COLUMNS, "Tabel B cascaded")

    dup_report = build_duplicate_diagnostic_report(df_b)
    deduped_b = dedup_pk(df_b, cfg)
    aggregated = aggregate_text(deduped_b, cfg["text_features"]["post_boundary_marker"])

    accounts_without_text = sorted(set(df_a["user_id"]) - set(aggregated["user_id"]))
    if accounts_without_text:
        print(
            f"PERINGATAN: {len(accounts_without_text)} akun cascaded "
            f"tanpa teks (tidak ada baris, atau semua caption kosong) -- akan dibuang di 04_integrate.py."
        )

    io_cfg = cfg["csv_io"]
    dup_report_out = cfgmod.resolve_path(cfg, "paths.duplicate_diagnostic_report_csv")
    aggregated_out = cfgmod.resolve_path(cfg, "paths.table_b_aggregated_csv")
    storage.write_csv_deterministic(dup_report, dup_report_out, "user_id", io_cfg["encoding"], io_cfg["quoting"])
    storage.write_csv_deterministic(aggregated, aggregated_out, io_cfg["sort_column"], io_cfg["encoding"], io_cfg["quoting"])

    manifest_path = cfgmod.resolve_path(cfg, "paths.run_manifest_json")
    manifest = RunManifest(manifest_path, config_path=cfgmod.config_path(cfg))
    manifest.add_stage(
        stage_name="03_aggregate_text",
        inputs=[table_a_path, table_b_path],
        outputs=[dup_report_out, aggregated_out],
        rows_in=len(df_b),
        rows_out=len(aggregated),
        rows_dropped=[],
        extra={
            "pk_duplicate_mode": cfg["duplicate_handling"]["pk_duplicate_mode"],
            "post_boundary_marker": cfg["text_features"]["post_boundary_marker"],
            "rows_before_pk_dedup": len(df_b),
            "rows_after_pk_dedup": len(deduped_b),
            "accounts_with_gt1_post": int((dup_report["post_count"] > 1).sum()),
            "accounts_without_text_after_cascade": accounts_without_text,
        },
    )

    return {"duplicate_report": dup_report, "aggregated": aggregated, "accounts_without_text": accounts_without_text}


def main() -> None:
    cfg = cfgmod.load_config()
    result = run(cfg)
    print(f"Akun teragregasi: {len(result['aggregated'])} baris.")
    print(f"Diagnostik duplikasi ditulis ke duplicate_diagnostic_report.csv.")
    if result["accounts_without_text"]:
        print(f"Akun tanpa teks: {len(result['accounts_without_text'])} (lihat manifest untuk daftar lengkap).")


if __name__ == "__main__":
    main()
