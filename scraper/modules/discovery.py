"""Buka halaman pencarian tag "stillprabowo", scroll berulang, tangkap tiap response GraphQL yang berbentuk hasil
pencarian, ekstrak post di dalamnya, dedup by pk, simpan raw JSON + tulis ke raw_posts_all.jsonl."""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Page, Response

import config
import storage
from models import RawPost
from utils.logging_setup import get_logger
from utils.parsing import walk_post_items, find_page_info, classify_post_node, detect_blocking_signals
from utils.rate_limit import polite_delay, post_navigation_delay
from utils.retry import async_retry

logger = get_logger("discovery")


def _looks_like_search_payload(payload: dict) -> bool:
    text = str(payload)
    return "searchResults" in text or "tag_info" in text


class DiscoverySession:
    def __init__(self) -> None:
        self.seen_pk: set[str] = storage.load_checkpoint_set(config.DISCOVERY_CHECKPOINT)
        self._response_seq = 0
        self._pending_payloads: list[dict] = []

    async def _on_response(self, response: Response) -> None:
        if config.GRAPHQL_URL_HINT not in response.url and "graphql" not in response.url:
            return
        try:
            payload = await response.json()
        except Exception:
            return

        blocked = detect_blocking_signals(payload)
        if blocked:
            logger.error(
                "SINYAL BLOCKING TERDETEKSI saat discovery (%s) -- pertimbangkan "
                "menghentikan sesi manual dan cek akun/IP sebelum lanjut.", blocked,
            )

        if _looks_like_search_payload(payload):
            self._pending_payloads.append(payload)

    async def _drain_payloads(self) -> tuple[list[RawPost], Optional[dict]]:
        """Proses semua payload yang tertangkap sejak drain terakhir."""
        new_posts: list[RawPost] = []
        last_page_info = None

        for payload in self._pending_payloads:
            self._response_seq += 1
            storage.dump_raw_response(
                config.DISCOVERY_RAW, f"search_{self._response_seq:05d}", payload
            )

            page_info = find_page_info(payload)
            if page_info is not None:
                last_page_info = page_info

            for node in walk_post_items(payload):
                fields = classify_post_node(node, source="search")
                if fields["pk"] in self.seen_pk:
                    continue
                self.seen_pk.add(fields["pk"])
                new_posts.append(RawPost(**fields))

        self._pending_payloads.clear()
        return new_posts, last_page_info

    @async_retry()
    async def run(self) -> int:
        """Jalankan sesi discovery penuh."""
        total_new = 0
        stale_scrolls = 0
        pages_scrolled = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=config.HEADLESS, channel="chrome")
            context = await browser.new_context(
                storage_state=str(config.STORAGE_STATE_PATH)
                if config.STORAGE_STATE_PATH.exists()
                else None
            )
            page: Page = await context.new_page()
            page.on("response", lambda r: asyncio.create_task(self._on_response(r)))

            logger.info("Membuka halaman pencarian: %s", config.SEARCH_URL)
            await page.goto(config.SEARCH_URL, wait_until="domcontentloaded")
            await post_navigation_delay()

            while pages_scrolled < config.MAX_DISCOVERY_PAGES:
                await page.mouse.wheel(0, 3000)
                await polite_delay()

                new_posts, page_info = await self._drain_payloads()
                total_new += len(new_posts)
                pages_scrolled += 1

                if new_posts:
                    storage.append_jsonl(config.RAW_POSTS_FILE, (p.to_dict() for p in new_posts))
                    stale_scrolls = 0
                    logger.info(
                        "Scroll #%d: +%d post baru (total sejauh ini %d)",
                        pages_scrolled, len(new_posts), len(self.seen_pk),
                    )
                else:
                    stale_scrolls += 1
                    logger.info(
                        "Scroll #%d: tidak ada post baru (stale %d/%d)",
                        pages_scrolled, stale_scrolls, config.MAX_STALE_SCROLLS,
                    )

                if page_info is not None and page_info.get("has_next_page") is False:
                    logger.info("has_next_page=False -- discovery selesai.")
                    break
                if stale_scrolls >= config.MAX_STALE_SCROLLS:
                    logger.info(
                        "Berhenti: %d scroll berturut-turut tanpa data baru "
                        "(kemungkinan sudah mentok atau kena throttle).",
                        stale_scrolls,
                    )
                    break

            storage.save_checkpoint_set(config.DISCOVERY_CHECKPOINT, self.seen_pk)
            await browser.close()

        logger.info("Discovery selesai. Total post unik terkumpul: %d", len(self.seen_pk))
        return total_new


async def main() -> None:
    storage.ensure_dirs()
    session = DiscoverySession()
    await session.run()


if __name__ == "__main__":
    asyncio.run(main())
