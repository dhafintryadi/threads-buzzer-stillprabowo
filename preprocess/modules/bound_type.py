"""Klasifikasi strata A-E (`bound_type`) per akun dari checkpoint feed scraper."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TAB_NAMES = ("threads", "replies", "reposts")

EXACT = "exact"
CAP = "cap"
STALLED_DATA = "stalled_data"
STALLED_ZERO = "stalled_zero"
UNOBSERVABLE = "unobservable"


class CheckpointFormatError(Exception):
    pass


class SnapshotMismatchError(Exception):
    pass


def load_feed_checkpoint(path: Path) -> dict:
    """Baca checkpoint feed dan kembalikan dict `accounts` (user_id -> entry)."""
    if not path.exists():
        raise CheckpointFormatError(f"Checkpoint feed tidak ditemukan: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, dict):
        raise CheckpointFormatError(
            f"Checkpoint feed {path} tidak punya objek 'accounts' (format tidak dikenali)."
        )
    return accounts


def classify_tab(entry: dict | None, unobservable_reasons: list[str]) -> str | None:
    """Kelas satu tab, atau None kalau tab tidak bisa diklasifikasi (entry hilang, status tidak dikenal mis. 'invalid',
    atau stalled tanpa metrics)."""
    if not entry:
        return None
    status, reason = entry.get("status"), entry.get("reason")
    if reason in unobservable_reasons:
        return UNOBSERVABLE
    if status == "complete":
        return EXACT
    if status == "stopped_at_cap":
        return CAP
    if status == "stalled":
        items = (entry.get("metrics") or {}).get("items_scanned")
        if items is None:
            return None
        return STALLED_DATA if items > 0 else STALLED_ZERO
    return None


def classify_account(tab_classes: dict[str, str]) -> str:
    values = set(tab_classes.values())
    if UNOBSERVABLE in values:
        return "unobservable"
    if STALLED_DATA in values:
        return "stalled_partial"
    if STALLED_ZERO in values:
        return "unknown"
    if CAP in values:
        return "cap"
    return "exact"


def expected_stopped_reason(account: dict) -> str:
    """String `stopped_reason` yang dibangun modules/dataset_build.py scraper dari checkpoint."""
    tabs = account.get("tabs", {})
    return ";".join(f"{t}:{tabs.get(t, {}).get('reason', '')}" for t in TAB_NAMES)


def build_bound_type_table(user_ids, accounts: dict, unobservable_reasons: list[str]) -> pd.DataFrame:
    """Satu baris per user_id: `bound_type` + kelas per tab."""
    rows = []
    for user_id in user_ids:
        tabs = (accounts.get(str(user_id)) or {}).get("tabs", {})
        classes = {t: classify_tab(tabs.get(t), unobservable_reasons) for t in TAB_NAMES}
        bound = None if any(v is None for v in classes.values()) else classify_account(classes)
        rows.append({"user_id": str(user_id), "bound_type": bound, **{f"tab_{t}": classes[t] for t in TAB_NAMES}})
    return pd.DataFrame(rows, columns=["user_id", "bound_type"] + [f"tab_{t}" for t in TAB_NAMES])


def find_snapshot_mismatches(df_a: pd.DataFrame, accounts: dict, bt_table: pd.DataFrame) -> list[dict]:
    """Akun yang terklasifikasi tetapi `stopped_reason` di Tabel A berbeda dengan yang diturunkan dari checkpoint ->
    Tabel A dan checkpoint bukan snapshot yang sama."""
    classified = set(bt_table.loc[bt_table["bound_type"].notna(), "user_id"])
    mismatches = []
    for _, row in df_a.iterrows():
        user_id = str(row["user_id"])
        if user_id not in classified:
            continue
        expected = expected_stopped_reason(accounts[user_id])
        actual = "" if pd.isna(row["stopped_reason"]) else str(row["stopped_reason"])
        if actual != expected:
            mismatches.append({"user_id": user_id, "table_a": actual, "checkpoint": expected})
    return mismatches


def check_snapshot_consistency(df_a: pd.DataFrame, accounts: dict, bt_table: pd.DataFrame, strict: bool) -> list[dict]:
    mismatches = find_snapshot_mismatches(df_a, accounts, bt_table)
    if mismatches and strict:
        examples = "; ".join(f"{m['user_id']}: A={m['table_a']!r} vs ckpt={m['checkpoint']!r}" for m in mismatches[:3])
        raise SnapshotMismatchError(
            f"{len(mismatches)} akun: stopped_reason Tabel A tidak cocok dengan checkpoint feed "
            f"(dua snapshot berbeda? jalankan ulang scraper `build`). Contoh: {examples}. "
            f"Set bound_type.strict_snapshot_check=false hanya jika ketidakcocokan ini disengaja."
        )
    return mismatches


def summarize_bound_types(bt_table: pd.DataFrame) -> dict:
    counts = bt_table["bound_type"].fillna("unclassifiable").value_counts().to_dict()
    tab_class_counts = {
        t: {str(k): int(v) for k, v in bt_table[f"tab_{t}"].fillna("unclassifiable").value_counts().items()}
        for t in TAB_NAMES
    }
    has_zero_tab = (bt_table[[f"tab_{t}" for t in TAB_NAMES]] == STALLED_ZERO).any(axis=1)
    return {
        "bound_type_counts": {str(k): int(v) for k, v in counts.items()},
        "tab_class_counts": tab_class_counts,
        "stalled_partial_with_stalled_zero_tab": int(((bt_table["bound_type"] == "stalled_partial") & has_zero_tab).sum()),
    }
