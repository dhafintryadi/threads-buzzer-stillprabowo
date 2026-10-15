"""Gabungkan profiles.jsonl (Modul 4) + feed_counts.jsonl (Modul 5) menjadi satu tabel fitur akun (Tabel B, satu baris
per akun)."""

from __future__ import annotations

import config
import storage
from utils.logging_setup import get_logger

logger = get_logger("dataset_build")

FIELDNAMES = [
    "user_id", "username",
    "follower_count", "view_count",
    "threads_count", "replies_count", "reposts_count", "media_count",
    "topic_threads_count", "topic_replies_count",
    "items_scanned", "unclassifiable_items_count", "stopped_reason",
]

_FEED_METRIC_FIELDS = (
    "threads_count", "replies_count", "reposts_count", "media_count",
    "topic_threads_count", "topic_replies_count", "items_scanned",
    "unclassifiable_items_count",
)


def _counts_from_feed_checkpoint() -> dict[str, dict]:
    """Bangun snapshot count terkini dari checkpoint per-tab."""
    checkpoint = storage.load_feed_checkpoint(config.FEED_CHECKPOINT)
    results: dict[str, dict] = {}
    for user_id, account in checkpoint.get("accounts", {}).items():
        tabs = account.get("tabs", {})
        if not all(isinstance(tabs.get(tab, {}).get("metrics"), dict) for tab in config.PROFILE_FEED_TABS):
            continue
        totals = {field: 0 for field in _FEED_METRIC_FIELDS}
        stopped = []
        for tab_name in config.PROFILE_FEED_TABS:
            tab = tabs[tab_name]
            for field in _FEED_METRIC_FIELDS:
                totals[field] += int(tab["metrics"].get(field, 0) or 0)
            stopped.append(f"{tab_name}:{tab.get('reason', '')}")
        results[str(user_id)] = {"user_id": str(user_id), **totals, "stopped_reason": ";".join(stopped)}
    return results


def run() -> int:
    profiles_path = config.PROCESSED_DIR / "profiles.jsonl"
    counts_path = config.PROCESSED_DIR / "feed_counts.jsonl"

    profiles = {p["user_id"]: p for p in storage.read_jsonl(profiles_path)}
    counts = {c["user_id"]: c for c in storage.read_jsonl(counts_path)}
    counts.update(_counts_from_feed_checkpoint())

    all_ids = set(profiles) | set(counts)
    missing_profile = all_ids - set(profiles)
    missing_counts = all_ids - set(counts)
    if missing_profile:
        logger.warning("%d akun tidak punya data profil (cek log profile_fetch).", len(missing_profile))
    if missing_counts:
        logger.warning("%d akun tidak punya data feed_counts (cek log feed_fetch).", len(missing_counts))

    rows = []
    for uid in sorted(all_ids):
        prof = profiles.get(uid, {})
        cnt = counts.get(uid, {})
        rows.append({
            "user_id": uid,
            "username": prof.get("username") or cnt.get("username") or "",
            "follower_count": prof.get("follower_count"),
            "view_count": prof.get("view_count"),
            "threads_count": cnt.get("threads_count"),
            "replies_count": cnt.get("replies_count"),
            "reposts_count": cnt.get("reposts_count"),
            "media_count": cnt.get("media_count"),
            "topic_threads_count": cnt.get("topic_threads_count"),
            "topic_replies_count": cnt.get("topic_replies_count"),
            "items_scanned": cnt.get("items_scanned"),
            "unclassifiable_items_count": cnt.get("unclassifiable_items_count"),
            "stopped_reason": cnt.get("stopped_reason"),
        })

    storage.write_csv(config.ACCOUNT_FEATURES_FILE, rows, fieldnames=FIELDNAMES)
    logger.info("Dataset fitur akun ditulis: %s (%d baris)", config.ACCOUNT_FEATURES_FILE, len(rows))
    logger.info(
        "Tabel post-level (Tabel A, multi-row per akun) tetap di %s -- "
        "belum di-dedup, proses cleaning (concat caption per akun) dilakukan terpisah.",
        config.QUALIFYING_POSTS_FILE,
    )
    return len(rows)


if __name__ == "__main__":
    run()
