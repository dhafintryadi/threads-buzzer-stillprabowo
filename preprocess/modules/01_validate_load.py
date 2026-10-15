"""Tahap 1: validasi skema kedua raw CSV (fail-fast), hash SHA-256 input (termasuk checkpoint feed) ke run manifest, dan
laporan kualitas data awal -- SEBELUM ada mutasi apa pun."""

from __future__ import annotations

import sys
from pathlib import Path

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


def build_quality_report(df_a, df_b, bound_summary: dict | None = None) -> dict:
    missing_per_column_a = {c: int(df_a[c].isna().sum()) for c in df_a.columns}

    counts_per_account_b = df_b["user_id"].value_counts()
    accounts_with_multiple_posts = int((counts_per_account_b > 1).sum())

    fully_identical_duplicate_rows_b = int(df_b.duplicated(keep="first").sum())

    report = {
        "table_a_akun": {
            "row_count": int(len(df_a)),
            "missing_per_column": missing_per_column_a,
        },
        "table_b_teks": {
            "row_count": int(len(df_b)),
            "accounts_with_gt1_post": accounts_with_multiple_posts,
            "fully_identical_duplicate_rows": fully_identical_duplicate_rows_b,
        },
    }
    if bound_summary is not None:
        report["feed_bound_type"] = bound_summary
    return report


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

    bt_cfg = cfg["bound_type"]
    accounts = bt.load_feed_checkpoint(checkpoint_path)
    bt_table = bt.build_bound_type_table(df_a["user_id"], accounts, bt_cfg["unobservable_reasons"])
    mismatches = bt.check_snapshot_consistency(df_a, accounts, bt_table, bt_cfg["strict_snapshot_check"])

    bound_summary = bt.summarize_bound_types(bt_table)
    bound_summary["snapshot_mismatch_count"] = len(mismatches)
    report = build_quality_report(df_a, df_b, bound_summary)
    report_path = cfgmod.resolve_path(cfg, "paths.data_quality_report_json")
    storage.write_json(report_path, report)

    manifest_path = cfgmod.resolve_path(cfg, "paths.run_manifest_json")
    manifest = RunManifest(manifest_path, config_path=cfgmod.config_path(cfg))
    manifest.add_stage(
        stage_name="01_validate_load",
        inputs=[raw_a_path, raw_b_path, checkpoint_path],
        outputs=[report_path],
        rows_in=len(df_a) + len(df_b),
        rows_out=len(df_a) + len(df_b),
        rows_dropped=[],
        extra={"quality_report_summary": report},
    )

    return {"df_a": df_a, "df_b": df_b, "report": report}


def main() -> None:
    cfg = cfgmod.load_config()
    result = run(cfg)
    print(f"Tabel A (akun): {len(result['df_a'])} baris -- skema valid.")
    print(f"Tabel B (teks): {len(result['df_b'])} baris -- skema valid.")
    print(f"Laporan kualitas data ditulis ke {cfgmod.resolve_path(cfg, 'paths.data_quality_report_json')}")
    summary = result["report"]["feed_bound_type"]
    print("Sebaran bound_type:")
    for value, count in sorted(summary["bound_type_counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {value}: {count}")
    print(f"  (stalled_partial dengan tab stalled tanpa data: {summary['stalled_partial_with_stalled_zero_tab']})")


if __name__ == "__main__":
    main()
