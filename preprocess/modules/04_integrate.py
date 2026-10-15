"""Tahap 4: join Tabel A hasil+ dengan hasil agregasi teks pada `user_id`, menghasilkan `clean_data.csv`."""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
for _p in (_THIS_DIR, _ROOT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as cfgmod
import schema
import storage
from manifest import RunManifest


def integrate(df_a_clean, df_b_aggregated, join_type: str):
    merged = df_a_clean.merge(df_b_aggregated, on="user_id", how=join_type)
    return merged[schema.CLEAN_DATA_COLUMNS]


def drop_rows_without_caption(clean_data):
    """Baris dengan caption_text kosong (NaN / spasi saja) TIDAK disertakan di clean_data."""
    caption = clean_data["caption_text"]
    has_text = caption.notna() & (caption.astype(str).str.strip() != "")
    return clean_data[has_text].copy(), clean_data.loc[~has_text, "user_id"].tolist()


def run(cfg: dict) -> dict:
    table_a_path = cfgmod.resolve_path(cfg, "paths.table_a_clean_csv")
    table_b_agg_path = cfgmod.resolve_path(cfg, "paths.table_b_aggregated_csv")

    df_a = schema.read_and_validate_csv(table_a_path, schema.TABLE_A_CLEAN_COLUMNS, ["user_id"], "Tabel A bersih", int_columns=schema.COUNT_COLUMNS)
    df_b_agg = schema.read_and_validate_csv(table_b_agg_path, schema.TABLE_B_AGGREGATED_COLUMNS, ["user_id", "caption_text"], "Tabel B teragregasi")

    join_type = cfgmod.require(cfg, "integration.join_type", context="join Tabel A + teks agregasi")
    clean_data = integrate(df_a, df_b_agg, join_type)
    rows_before_caption_filter = len(clean_data)
    clean_data, dropped_without_caption = drop_rows_without_caption(clean_data)

    io_cfg = cfg["csv_io"]
    out_path = cfgmod.resolve_path(cfg, "paths.clean_data_csv")
    storage.write_csv_deterministic(clean_data, out_path, io_cfg["sort_column"], io_cfg["encoding"], io_cfg["quoting"])

    manifest_path = cfgmod.resolve_path(cfg, "paths.run_manifest_json")
    manifest = RunManifest(manifest_path, config_path=cfgmod.config_path(cfg))
    manifest.add_stage(
        stage_name="04_integrate",
        inputs=[table_a_path, table_b_agg_path],
        outputs=[out_path],
        rows_in=rows_before_caption_filter,
        rows_out=len(clean_data),
        rows_dropped=[{"reason": "caption_text kosong (akun tanpa teks)", "user_id": u} for u in dropped_without_caption],
        extra={
            "join_type": join_type,
            "rows_dropped_without_caption": len(dropped_without_caption),
        },
    )

    return {"clean_data": clean_data, "dropped_without_caption": dropped_without_caption}


def main() -> None:
    cfg = cfgmod.load_config()
    result = run(cfg)
    print(f"clean_data.csv ditulis: {len(result['clean_data'])} baris.")
    if result["dropped_without_caption"]:
        print(f"  ({len(result['dropped_without_caption'])} akun dibuang karena caption_text kosong -- id ada di manifest.)")


if __name__ == "__main__":
    main()
