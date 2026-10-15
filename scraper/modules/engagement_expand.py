"""Perluasan populasi lewat engagement: akun yang membalas post seed yang lolos kriteria topik."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright, Response

import config
import storage
from utils.logging_setup import get_logger
from utils.parsing import (
    classify_post_node,
    detect_blocking_signals,
    is_thread_reply_payload,
    matches_topic_criteria,
    walk_post_items,
)
from utils.rate_limit import inter_account_delay, maybe_batch_cooldown, polite_delay, post_navigation_delay
from utils.retry import async_retry
from utils.window import window_position

logger = get_logger("engagement_expand")

CSV_FIELDNAMES = [
    "pk", "code", "taken_at", "taken_at_utc", "caption_text",
    "user_id", "username", "is_reply", "tag_header_name",
    "reposted_post_pk", "has_media", "like_count",
    "direct_reply_count", "repost_count", "is_partial_schema",
    "inclusion_criterion", "source",
]


def _load_seed_posts() -> list[dict]:
    """Ambil post seed dari qualifying_posts.jsonl."""
    seen_pk: set[str] = set()
    seeds: list[dict] = []
    for post in storage.read_jsonl(config.QUALIFYING_POSTS_FILE):
        pk = post.get("pk")
        if pk in seen_pk:
            continue
        if post.get("is_reply"):
            continue
        if not post.get("username") or not post.get("code"):
            continue
        seen_pk.add(pk)
        seeds.append(post)
    return seeds


def _load_existing_pks() -> set[str]:
    return {p["pk"] for p in storage.read_jsonl(config.QUALIFYING_POSTS_FILE) if p.get("pk")}


def _select_replies(candidates: dict[str, dict]) -> list[dict]:
    """Seleksi reply per seed: tier 1 reply yang relevan topik, tier 2 reply lain terurut engagement."""
    all_items = list(candidates.values())

    tier1 = [f for f in all_items if matches_topic_criteria(f["tag_header_name"], f["caption_text"])]
    tier1_sorted = sorted(
        tier1, key=lambda f: (f["like_count"] or 0) + (f["direct_reply_count"] or 0), reverse=True
    )

    cap = config.REPLY_CAP_PER_SEED

    if len(tier1_sorted) >= cap:
        selected = tier1_sorted[:cap]
        for f in selected:
            f["inclusion_criterion"] = "own_text_match"
        return selected

    tier1_pks = {f["pk"] for f in tier1}
    remaining_slots = cap - len(tier1_sorted)
    tier2_candidates = [
        f for f in all_items
        if f["pk"] not in tier1_pks and len(f["caption_text"].strip()) >= config.MIN_REPLY_CAPTION_LENGTH
    ]
    tier2_sorted = sorted(
        tier2_candidates, key=lambda f: (f["like_count"] or 0) + (f["direct_reply_count"] or 0), reverse=True
    )
    tier2_selected = tier2_sorted[:remaining_slots]

    for f in tier1_sorted:
        f["inclusion_criterion"] = "own_text_match"
    for f in tier2_selected:
        f["inclusion_criterion"] = "engaged_with_topic"

    return tier1_sorted + tier2_selected


class EngagementExpander:
    def __init__(self) -> None:
        self.done: set[str] = storage.load_checkpoint_set(config.ENGAGEMENT_CHECKPOINT)
        self._pending_payloads: list[dict] = []
        self._current_seed_pk: str = "unknown"
        self._raw_seq: int = 0
        self._responses_seen: int = 0
        self._responses_matched: int = 0

    async def _on_response(self, response: Response) -> None:
        if "graphql" not in response.url:
            return
        try:
            payload = await response.json()
        except Exception:
            return

        blocked = detect_blocking_signals(payload)
        if blocked:
            logger.error(
                "SINYAL BLOCKING TERDETEKSI saat crawl balasan (%s) -- "
                "pertimbangkan menghentikan sesi manual dan cek akun/IP.", blocked,
            )

        self._responses_seen += 1
        matched = is_thread_reply_payload(payload)

        self._raw_seq += 1
        tag = "matched" if matched else "unmatched"
        storage.dump_raw_response(
            config.ENGAGEMENT_RAW, f"{self._current_seed_pk}_{self._raw_seq:05d}_{tag}", payload
        )

        if matched:
            self._responses_matched += 1
            self._pending_payloads.append(payload)

    @async_retry()
    async def crawl_one_seed(self, page, seed: dict, existing_pks: set[str]) -> list[dict]:
        """Kunjungi satu post seed, kumpulkan balasan dalam jendela waktu."""
        self._pending_payloads = []
        self._current_seed_pk = seed["pk"]
        self._raw_seq = 0
        self._responses_seen = 0
        self._responses_matched = 0
        url = f"{config.BASE_URL}/@{seed['username']}/post/{seed['code']}"
        await page.goto(url, wait_until="domcontentloaded")
        await post_navigation_delay()

        candidates: dict[str, dict] = {}
        scrolls = 0
        stale = 0

        while scrolls < config.MAX_REPLY_THREAD_SCROLLS and stale < config.MAX_STALE_SCROLLS:
            await page.mouse.wheel(0, 3000)
            await polite_delay()
            scrolls += 1

            if not self._pending_payloads:
                stale += 1
                continue
            stale = 0

            for payload in self._pending_payloads:
                for node in walk_post_items(payload):
                    fields = classify_post_node(node, source="thread_reply")
                    pk = fields["pk"]
                    if pk == seed["pk"] or pk in existing_pks or pk in candidates:
                        continue
                    taken_at = fields.get("taken_at")
                    if not taken_at or window_position(taken_at) != "within":
                        continue
                    candidates[pk] = fields
            self._pending_payloads = []

        return _select_replies(candidates)

    async def run(self) -> int:
        seeds_all = [s for s in _load_seed_posts() if s["pk"] not in self.done]
        logger.info("Total seed (is_reply==False, lolos Modul 2): sisa %d untuk di-crawl", len(seeds_all))
        if not seeds_all:
            return 0

        if config.MAX_SEEDS_PER_SESSION is not None and len(seeds_all) > config.MAX_SEEDS_PER_SESSION:
            seeds = seeds_all[: config.MAX_SEEDS_PER_SESSION]
            logger.warning(
                "Batas sesi (MAX_SEEDS_PER_SESSION=%d) tercapai -- memproses %d "
                "dari %d seed tersisa. Jalankan `python main.py engagement` lagi "
                "untuk melanjutkan.", config.MAX_SEEDS_PER_SESSION, len(seeds), len(seeds_all),
            )
        else:
            seeds = seeds_all

        existing_pks = _load_existing_pks()
        new_records: list[dict] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=config.HEADLESS, channel="chrome")
            context = await browser.new_context(
                storage_state=str(config.STORAGE_STATE_PATH)
                if config.STORAGE_STATE_PATH.exists() else None
            )
            page = await context.new_page()
            page.on("response", lambda r: asyncio.create_task(self._on_response(r)))

            consecutive_failures = 0
            for i, seed in enumerate(seeds, start=1):
                try:
                    replies = await self.crawl_one_seed(page, seed, existing_pks)
                except Exception as exc:
                    logger.error(
                        "[%d/%d] seed @%s/post/%s GAGAL total (%s: %s) -- "
                        "dilewati, DITANDAI SELESAI supaya tidak diulang "
                        "terus-menerus. Kalau ini akun/post penting, cek "
                        "manual apakah post masih ada (mungkin dihapus/"
                        "private) sebelum menganggap datanya hilang.",
                        i, len(seeds), seed["username"], seed["code"],
                        type(exc).__name__, exc,
                    )
                    storage.mark_done(config.ENGAGEMENT_CHECKPOINT, seed["pk"])
                    self.done.add(seed["pk"])
                    consecutive_failures += 1
                    if consecutive_failures >= config.MAX_CONSECUTIVE_ENGAGEMENT_FAILURES:
                        logger.error(
                            "%d seed BERTURUT-TURUT gagal total -- kalau ini "
                            "bukan kebetulan beberapa post bermasalah, "
                            "pertimbangkan cek koneksi/sesi login sebelum "
                            "melanjutkan sesi ini.", consecutive_failures,
                        )
                    await inter_account_delay()
                    continue

                consecutive_failures = 0
                for r in replies:
                    existing_pks.add(r["pk"])
                new_records.extend(replies)
                storage.mark_done(config.ENGAGEMENT_CHECKPOINT, seed["pk"])
                self.done.add(seed["pk"])
                logger.info(
                    "[%d/%d] seed @%s/post/%s -> %d akun/post baru (respons GraphQL "
                    "dilihat=%d, cocok bentuk thread-reply=%d)",
                    i, len(seeds), seed["username"], seed["code"], len(replies),
                    self._responses_seen, self._responses_matched,
                )
                await inter_account_delay()
                await maybe_batch_cooldown(i)

            await browser.close()

        if new_records:
            storage.append_jsonl(config.QUALIFYING_POSTS_FILE, new_records)
            _rewrite_csv()
            logger.info(
                "%d baris baru (inclusion_criterion=engaged_with_topic) ditambahkan "
                "ke qualifying_posts.jsonl & .csv. Jalankan `python main.py accounts` "
                "ulang supaya akun-akun baru ini masuk unique_accounts.csv.",
                len(new_records),
            )
        else:
            logger.info("Tidak ada post/akun baru ditemukan dari sesi engagement ini.")

        return len(new_records)


def _rewrite_csv() -> None:
    """Tulis ulang qualifying_posts.csv dari qualifying_posts.jsonl penuh (termasuk baris lama own_text_match + baru
    engaged_with_topic)."""
    from utils.window import format_utc

    rows = []
    for post in storage.read_jsonl(config.QUALIFYING_POSTS_FILE):
        row = dict(post)
        row["taken_at_utc"] = format_utc(post["taken_at"]) if post.get("taken_at") else ""
        rows.append(row)
    storage.write_csv(config.QUALIFYING_POSTS_CSV_FILE, rows, fieldnames=CSV_FIELDNAMES)


async def main() -> None:
    storage.ensure_dirs()
    expander = EngagementExpander()
    await expander.run()


if __name__ == "__main__":
    asyncio.run(main())
