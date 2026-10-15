"""Kontrak kolom untuk setiap tabel yang mengalir lewat pipeline preprocessing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class SchemaValidationError(Exception):
    """Skema input/output tidak cocok dengan kontrak yang didefinisikan di sini."""


TABLE_A_AKUN_COLUMNS = [
    "user_id", "username", "follower_count", "view_count",
    "threads_count", "replies_count", "reposts_count", "media_count",
    "topic_threads_count", "topic_replies_count",
    "items_scanned", "stopped_reason",
]

FEED_COUNT_COLUMNS = [
    "threads_count", "replies_count", "reposts_count",
    "topic_threads_count", "topic_replies_count",
]

TABLE_B_TEKS_COLUMNS = [
    "pk", "code", "taken_at", "taken_at_utc", "caption_text", "user_id",
    "username", "is_reply", "tag_header_name", "reposted_post_pk",
    "has_media", "like_count", "direct_reply_count", "repost_count",
    "inclusion_criterion", "source",
]

TABLE_A_STRING_COLUMNS = ["user_id", "username", "stopped_reason"]
TABLE_B_STRING_COLUMNS = [
    "pk", "code", "taken_at", "taken_at_utc", "caption_text", "user_id",
    "username", "tag_header_name", "reposted_post_pk",
    "inclusion_criterion", "source",
]


TABLE_A_CLEAN_COLUMNS = [
    "user_id", "follower_count",
    "threads_count", "replies_count", "reposts_count",
    "threads_topik", "balasan_topik", "items_scanned",
]

COUNT_COLUMNS = [c for c in TABLE_A_CLEAN_COLUMNS if c != "user_id"]

TABLE_B_AGGREGATED_COLUMNS = ["user_id", "caption_text"]

CLEAN_DATA_COLUMNS = TABLE_A_CLEAN_COLUMNS + ["caption_text"]

CLEAN_DATA_LABELED_EXTRA_COLUMNS = [
    "label", "label_source", "final_prompt_version", "review_changed_label",
]
CLEAN_DATA_LABELED_COLUMNS = CLEAN_DATA_COLUMNS + CLEAN_DATA_LABELED_EXTRA_COLUMNS

LABEL_VALUES = (0, 1)
LABEL_SOURCES = ("manual_subset", "llm_positive_reviewed", "llm_negative_unreviewed")

LABELED_STRING_COLUMNS = ["user_id", "caption_text", "label_source", "final_prompt_version", "review_changed_label"]
LABELED_INT_COLUMNS = COUNT_COLUMNS + ["label"]

TEXT_PREPROCESS_EXTRA_COLUMNS = ["caption_text_clean"]
CLEAN_DATA_TEXT_COLUMNS = CLEAN_DATA_LABELED_COLUMNS + TEXT_PREPROCESS_EXTRA_COLUMNS


def validate_columns(df: pd.DataFrame, required_columns: list[str], table_name: str) -> None:
    """Fail-fast kalau kolom wajib hilang."""
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise SchemaValidationError(
            f"Skema '{table_name}' tidak cocok kontrak. Kolom hilang: {missing}. "
            f"Kolom yang ditemukan: {list(df.columns)}"
        )


def read_and_validate_csv(
    path: Path,
    required_columns: list[str],
    string_columns: list[str],
    table_name: str,
    int_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Baca CSV dengan kolom id/kode dipaksa string (hindari presisi float / leading-zero hilang), lalu validasi skema."""
    if not path.exists():
        raise SchemaValidationError(f"File input '{table_name}' tidak ditemukan: {path}")

    header = pd.read_csv(path, nrows=0, encoding="utf-8").columns.tolist()
    dtype_map = {c: str for c in string_columns if c in header}
    df = pd.read_csv(path, dtype=dtype_map, encoding="utf-8", keep_default_na=True)
    validate_columns(df, required_columns, table_name)
    for col in int_columns or []:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def _first_ids(ids, n: int = 5) -> str:
    ids = list(ids)
    return ", ".join(map(str, ids[:n])) + (f" ... (+{len(ids) - n})" if len(ids) > n else "")


def validate_labeled_contract(labeled: pd.DataFrame, clean_data: pd.DataFrame) -> None:
    """Fail-fast kontrak serah terima anotasi -> text preprocessing."""
    name = "clean_data_labeled.csv"

    dup = labeled.loc[labeled["user_id"].duplicated(keep=False), "user_id"].unique()
    if len(dup):
        raise SchemaValidationError(f"{name}: user_id tidak unik ({len(dup)} id ganda, mis. {_first_ids(dup)}).")

    bad_label = labeled["label"].isna() | ~labeled["label"].isin(LABEL_VALUES)
    if bad_label.any():
        raise SchemaValidationError(
            f"{name}: kolom label harus 0 atau 1 tanpa sel kosong; {int(bad_label.sum())} baris melanggar "
            f"(mis. user_id {_first_ids(labeled.loc[bad_label, 'user_id'])})."
        )

    bad_source = ~labeled["label_source"].isin(LABEL_SOURCES)
    if bad_source.any():
        found = sorted(map(str, labeled.loc[bad_source, "label_source"].unique()))
        raise SchemaValidationError(
            f"{name}: label_source di luar {list(LABEL_SOURCES)}: {found} "
            f"({int(bad_source.sum())} baris, mis. user_id {_first_ids(labeled.loc[bad_source, 'user_id'])})."
        )

    versions = labeled["final_prompt_version"].dropna().unique()
    if labeled["final_prompt_version"].isna().any() or len(versions) != 1:
        raise SchemaValidationError(
            f"{name}: final_prompt_version harus satu nilai yang sama untuk semua baris dan tidak kosong; "
            f"ditemukan {sorted(map(str, versions))}"
            f"{' + sel kosong' if labeled['final_prompt_version'].isna().any() else ''}."
        )

    ids_l, ids_c = set(labeled["user_id"]), set(clean_data["user_id"])
    if ids_l != ids_c:
        raise SchemaValidationError(
            f"{name}: himpunan user_id berbeda dari clean_data.csv "
            f"(hanya di labeled: {len(ids_l - ids_c)}, mis. {_first_ids(sorted(ids_l - ids_c))}; "
            f"hanya di clean_data: {len(ids_c - ids_l)}, mis. {_first_ids(sorted(ids_c - ids_l))}). "
            f"clean_data.csv kemungkinan dibangun ulang setelah anotasi."
        )

    lab = labeled[CLEAN_DATA_COLUMNS].reset_index(drop=True).astype(str)
    cln = clean_data[CLEAN_DATA_COLUMNS].reset_index(drop=True).astype(str)
    if not lab["user_id"].equals(cln["user_id"]):
        raise SchemaValidationError(f"{name}: urutan user_id berbeda dari clean_data.csv.")
    diff_cols = [c for c in CLEAN_DATA_COLUMNS if not lab[c].equals(cln[c])]
    if diff_cols:
        rows = (lab[diff_cols] != cln[diff_cols]).any(axis=1)
        raise SchemaValidationError(
            f"{name}: isi kolom bawaan clean_data tidak identik dengan clean_data.csv "
            f"(kolom {diff_cols}; {int(rows.sum())} baris, mis. user_id {_first_ids(lab.loc[rows, 'user_id'])}). "
            f"clean_data.csv kemungkinan dibangun ulang setelah anotasi."
        )
