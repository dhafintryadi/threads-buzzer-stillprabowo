"""Tahap 2: (nilai hilang Data Akun + penanganan nilai per strata `bound_type`), dan (cascade delete ke Data Teks)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
for _p in (_THIS_DIR, _ROOT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bound_type as bt
import config as cfgmod
import schema
import storage
from manifest import RunManifest


def apply_missing_value_policy(df_a: pd.DataFrame, bt_table: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Hapus baris yang bukan populasi analisis (exact + lower bound only) atau tidak bisa dipakai, dan lampirkan
    `bound_type`."""
    policy = cfg["missing_value_policy"]
    allowed_tab_classes = set(cfg["population"]["allowed_tab_classes"])
    tab_columns = [f"tab_{t}" for t in bt.TAB_NAMES]

    working = df_a.merge(bt_table[["user_id", "bound_type", *tab_columns]], on="user_id", how="left")
    keep = pd.Series(True, index=working.index)
    removed_log: list[dict] = []

    def _remove(mask: pd.Series, column: str, reason, value_col: str | None = None) -> None:
        hit = mask & keep
        for idx in working.index[hit]:
            original = "" if value_col is None else str(working.at[idx, value_col])
            removed_log.append({
                "user_id": working.at[idx, "user_id"],
                "column_causing_removal": column,
                "original_value": original,
                "reason": reason.at[idx] if isinstance(reason, pd.Series) else reason,
            })
        keep.loc[hit] = False

    for col in policy.get("always_drop_if_missing", []):
        _remove(working[col].isna(), col, f"{col} hilang (selalu hapus baris)")

    for col in policy.get("drop_if_zero", []):
        _remove(working[col] == 0, col, f"{col} bernilai 0 (tidak ada item ter-scan; baris dibuang)", value_col=col)

    _remove(
        working["bound_type"].isna(), "bound_type",
        "tidak bisa diklasifikasi dari checkpoint feed (akun belum/tidak lengkap discan)",
        value_col="stopped_reason",
    )

    tab_summary = working[tab_columns].apply(
        lambda row: ";".join(f"{t}={row[f'tab_{t}']}" for t in bt.TAB_NAMES), axis=1
    )
    in_population = working[tab_columns].isin(allowed_tab_classes).all(axis=1)
    _remove(
        ~in_population, "bound_type",
        "bukan populasi analisis (hanya akun exact atau lower-bound-only; tab: " + tab_summary + ")",
        value_col="bound_type",
    )

    for feature in schema.FEED_COUNT_COLUMNS:
        _remove(working[feature].isna(), feature, f"{feature} hilang (Tabel A tidak lengkap)")

    return working.loc[keep].drop(columns=tab_columns).copy(), removed_log


def validate_username_consistency(df_a: pd.DataFrame, df_b: pd.DataFrame) -> list[dict]:
    merged = df_a[["user_id", "username"]].merge(
        df_b[["user_id", "username"]].drop_duplicates(), on="user_id", suffixes=("_a", "_b")
    )
    mismatches = merged[merged["username_a"] != merged["username_b"]]
    return mismatches.to_dict(orient="records")


def build_account_features(df: pd.DataFrame) -> pd.DataFrame:
    """Pilih fitur akun mentah untuk clean_data (tanpa turunan)."""
    out = df.copy()
    out["threads_topik"] = out["topic_threads_count"]
    out["balasan_topik"] = out["topic_replies_count"]

    out = out[schema.TABLE_A_CLEAN_COLUMNS].copy()
    out[schema.COUNT_COLUMNS] = out[schema.COUNT_COLUMNS].astype("Int64")
    return out


def cascade_delete(df_b: pd.DataFrame, surviving_user_ids: set[str]) -> pd.DataFrame:
    return df_b[df_b["user_id"].isin(surviving_user_ids)].copy()


def run(cfg: dict) -> dict:
    raw_a_path = cfgmod.resolve_path(cfg, "paths.raw_table_a_akun")
    raw_b_path = cfgmod.resolve_path(cfg, "paths.raw_table_b_teks")
    checkpoint_path = cfgmod.resolve_path(cfg, "paths.raw_feed_checkpoint_json")

    df_a = schema.read_and_validate_csv(
        raw_a_path, schema.TABLE_A_AKUN_COLUMNS, schema.TABLE_A_STRING_COLUMNS, "Tabel A (Data Akun)"
    )
    df_b = schema.read_and_validate_csv(
        raw_b_path, schema.TABLE_B_TEKS_COLUMNS, schema.TABLE_B_STRING_COLUMNS, "Tabel B (Data Teks)"
    )
    for col in schema.FEED_COUNT_COLUMNS + ["items_scanned", "follower_count"]:
        df_a[col] = storage.to_numeric_nullable(df_a[col])

    bt_cfg = cfg["bound_type"]
    accounts = bt.load_feed_checkpoint(checkpoint_path)
    bt_table = bt.build_bound_type_table(df_a["user_id"], accounts, bt_cfg["unobservable_reasons"])
    bt.check_snapshot_consistency(df_a, accounts, bt_table, bt_cfg["strict_snapshot_check"])

    cleaned_a, removed_log = apply_missing_value_policy(df_a, bt_table, cfg)
    mismatches = validate_username_consistency(cleaned_a, df_b)
    kept_bound_type_counts = {str(k): int(v) for k, v in cleaned_a["bound_type"].value_counts().items()}
    features_a = build_account_features(cleaned_a)

    surviving_ids = set(features_a["user_id"])
    cascaded_b = cascade_delete(df_b, surviving_ids)

    io_cfg = cfg["csv_io"]
    table_a_out = cfgmod.resolve_path(cfg, "paths.table_a_clean_csv")
    table_b_out = cfgmod.resolve_path(cfg, "paths.table_b_cascaded_csv")
    removed_log_out = cfgmod.resolve_path(cfg, "paths.removed_rows_log_csv")

    storage.write_csv_deterministic(features_a, table_a_out, io_cfg["sort_column"], io_cfg["encoding"], io_cfg["quoting"])
    storage.write_csv_deterministic(cascaded_b, table_b_out, io_cfg["sort_column"], io_cfg["encoding"], io_cfg["quoting"])
    removed_df = pd.DataFrame(removed_log, columns=["user_id", "column_causing_removal", "original_value", "reason"])
    storage.write_csv_deterministic(removed_df, removed_log_out, "user_id", io_cfg["encoding"], io_cfg["quoting"])

    removed_by_column = removed_df["column_causing_removal"].value_counts().to_dict()
    excluded_by_bound_type = (
        removed_df.loc[removed_df["column_causing_removal"] == "bound_type", "original_value"].value_counts().to_dict()
    )
    manifest_path = cfgmod.resolve_path(cfg, "paths.run_manifest_json")
    manifest = RunManifest(manifest_path, config_path=cfgmod.config_path(cfg))
    manifest.add_stage(
        stage_name="02_clean_account",
        inputs=[raw_a_path, raw_b_path, checkpoint_path],
        outputs=[table_a_out, table_b_out, removed_log_out],
        rows_in=len(df_a),
        rows_out=len(features_a),
        rows_dropped=[{"reason": r["reason"], "user_id": r["user_id"]} for r in removed_log],
        extra={
            "rows_removed_count": len(removed_log),
            "bound_type_counts_kept": kept_bound_type_counts,
            "rows_removed_by_column": {str(k): int(v) for k, v in removed_by_column.items()},
            "excluded_by_bound_type": {str(k): int(v) for k, v in excluded_by_bound_type.items()},
            "table_b_rows_before_cascade": len(df_b),
            "table_b_rows_after_cascade": len(cascaded_b),
            "username_mismatches": mismatches,
        },
    )

    if mismatches:
        print(f"PERINGATAN: {len(mismatches)} user_id punya username tidak konsisten antara Tabel A dan Tabel B.")
    return {
        "table_a_clean": features_a, "table_b_cascaded": cascaded_b, "removed_log": removed_df,
        "kept_bound_type_counts": kept_bound_type_counts,
    }


def main() -> None:
    cfg = cfgmod.load_config()
    result = run(cfg)
    print(f"Tabel A bersih: {len(result['table_a_clean'])} baris (dari {len(result['table_a_clean']) + len(result['removed_log'])} sebelum pembersihan).")
    print(f"Baris dihapus: {len(result['removed_log'])} -- lihat removed_rows_log.csv")
    print("Jenis akun yang dipertahankan (hanya dicatat di manifest, bukan kolom output):")
    for value, count in result["kept_bound_type_counts"].items():
        print(f"  {value}: {count}")
    print(f"Tabel B setelah cascade delete: {len(result['table_b_cascaded'])} baris.")


if __name__ == "__main__":
    main()
