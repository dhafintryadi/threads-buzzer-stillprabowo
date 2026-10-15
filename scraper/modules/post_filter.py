"""Terapkan dua tahap filter terhadap raw_posts_all.jsonl."""

from __future__ import annotations

import config
import storage
from utils.logging_setup import get_logger
from utils.parsing import matches_topic_criteria
from utils.window import format_utc, is_within_window

logger = get_logger("post_filter")

CSV_FIELDNAMES = [
    "pk", "code", "taken_at", "taken_at_utc", "caption_text",
    "user_id", "username", "is_reply", "tag_header_name",
    "reposted_post_pk", "has_media", "like_count",
    "direct_reply_count", "repost_count", "is_partial_schema",
    "inclusion_criterion", "source",
]


def run() -> dict:
    storage.ensure_dirs()

    total = 0
    in_window = 0
    passed = 0

    qualifying: list[dict] = []

    for post in storage.read_jsonl(config.RAW_POSTS_FILE):
        total += 1
        taken_at = post.get("taken_at")
        if not taken_at or not is_within_window(taken_at):
            continue
        in_window += 1

        if matches_topic_criteria(post.get("tag_header_name"), post.get("caption_text", "")):
            passed += 1
            tagged = dict(post)
            tagged["inclusion_criterion"] = "own_text_match"
            qualifying.append(tagged)

    if config.QUALIFYING_POSTS_FILE.exists():
        config.QUALIFYING_POSTS_FILE.unlink()
    storage.append_jsonl(config.QUALIFYING_POSTS_FILE, qualifying)

    csv_rows = []
    for post in qualifying:
        row = dict(post)
        row["taken_at_utc"] = format_utc(post["taken_at"]) if post.get("taken_at") else ""
        csv_rows.append(row)
    storage.write_csv(config.QUALIFYING_POSTS_CSV_FILE, csv_rows, fieldnames=CSV_FIELDNAMES)

    stats = {
        "total_raw": total,
        "in_window": in_window,
        "passed_relevance": passed,
        "yield_in_window_pct": round(100 * in_window / total, 2) if total else 0.0,
        "yield_final_pct": round(100 * passed / total, 2) if total else 0.0,
    }

    logger.info(
        "Filter selesai. Total raw=%d, dalam jendela=%d (%.1f%%), lolos relevansi=%d (%.1f%% dari total).",
        stats["total_raw"], stats["in_window"], stats["yield_in_window_pct"],
        stats["passed_relevance"], stats["yield_final_pct"],
    )
    logger.info(
        "Tabel A ditulis dalam 2 format: %s (jsonl, dipakai modul lain) dan "
        "%s (csv, siap dibuka Excel/pandas dengan kolom taken_at_utc).",
        config.QUALIFYING_POSTS_FILE, config.QUALIFYING_POSTS_CSV_FILE,
    )
    logger.warning(
        "Angka yield ini deskriptif untuk data yang sudah terkumpul sejauh ini -- "
        "JANGAN dijadikan estimasi final tanpa validasi pada sampel yang lebih besar "
        "(lihat dokumen desain bagian 1.7 poin 3)."
    )
    return stats


if __name__ == "__main__":
    run()
