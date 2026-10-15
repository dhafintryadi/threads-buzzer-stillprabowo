"""Untuk tiap akun unik di unique_accounts.csv: buka halaman profil, tangkap follower_count & view_count."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from playwright.async_api import async_playwright, Response

import config
import storage
from models import AccountProfile
from utils.logging_setup import get_logger
from utils.parsing import (
    detect_blocking_signals,
    extract_embedded_json_candidates,
    extract_profile_fields,
    looks_like_user_profile_payload,
)
from utils.rate_limit import inter_account_delay, maybe_batch_cooldown, polite_delay, post_navigation_delay
from utils.retry import async_retry

logger = get_logger("profile_fetch")


class ProfileFetcher:
    def __init__(self) -> None:
        self.done: set[str] = storage.load_checkpoint_set(config.PROFILE_CHECKPOINT)
        self._captured: dict | None = None

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
                "SINYAL BLOCKING TERDETEKSI saat profile fetch (%s) -- "
                "pertimbangkan menghentikan sesi manual dan cek akun/IP.", blocked,
            )

        if looks_like_user_profile_payload(payload):
            fields = extract_profile_fields(payload)
            if fields is not None:
                self._captured = fields

    async def _try_embedded_html_fallback(self, page) -> dict | None:
        """Jalur 2: cari JSON ter-embed di HTML halaman (dugaan SSR)."""
        try:
            html = await page.content()
        except Exception as exc:
            logger.warning("Gagal mengambil page.content() untuk fallback HTML: %s", exc)
            return None

        for candidate in extract_embedded_json_candidates(html):
            fields = extract_profile_fields(candidate)
            if fields is not None:
                return fields
        return None

    @async_retry()
    async def fetch_one(self, page, user_id: str, username: str) -> AccountProfile:
        self._captured = None
        url = config.profile_url(username)
        await page.goto(url, wait_until="domcontentloaded")
        await post_navigation_delay()

        source = "network_response"
        if self._captured is None:
            fallback = await self._try_embedded_html_fallback(page)
            if fallback is not None:
                self._captured = fallback
                source = "embedded_html"

        if self._captured is None:
            logger.warning(
                "Tidak menemukan payload profil untuk @%s lewat network maupun "
                "HTML ter-embed -- dump HTML mentah untuk diagnosis.", username,
            )
            try:
                html = await page.content()
            except Exception:
                html = None
            storage.dump_raw_response(
                config.PROFILE_RAW,
                f"{username}_FAILED_html_dump",
                {"error": "not_found", "username": username, "html_snapshot": html},
            )
            source = "not_found"

        storage.dump_raw_response(
            config.PROFILE_RAW, username, self._captured or {"error": "not_found", "username": username}
        )
        if self._captured is not None:
            logger.info("Profil @%s ditemukan via jalur: %s", username, source)

        return AccountProfile(
            user_id=user_id,
            username=username,
            follower_count=(self._captured or {}).get("follower_count"),
            view_count=(self._captured or {}).get("view_count"),
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    async def run(self) -> int:
        rows = storage.read_csv(config.UNIQUE_ACCOUNTS_FILE)
        todo_all = [r for r in rows if r["user_id"] not in self.done]
        logger.info("Total akun: %d, sudah selesai: %d, sisa: %d", len(rows), len(self.done), len(todo_all))

        if not todo_all:
            return 0

        if config.MAX_ACCOUNTS_PER_SESSION is not None and len(todo_all) > config.MAX_ACCOUNTS_PER_SESSION:
            todo = todo_all[: config.MAX_ACCOUNTS_PER_SESSION]
            logger.warning(
                "Batas sesi (MAX_ACCOUNTS_PER_SESSION=%d) tercapai -- memproses "
                "%d dari %d akun tersisa. %d akun BELUM diproses, bukan gagal -- "
                "jalankan `python main.py profiles` lagi (idealnya di sesi lain/"
                "hari lain) untuk melanjutkan dari checkpoint.",
                config.MAX_ACCOUNTS_PER_SESSION, len(todo), len(todo_all),
                len(todo_all) - len(todo),
            )
        else:
            todo = todo_all

        results: list[dict] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=config.HEADLESS, channel="chrome")
            context = await browser.new_context(
                storage_state=str(config.STORAGE_STATE_PATH)
                if config.STORAGE_STATE_PATH.exists()
                else None
            )
            page = await context.new_page()
            page.on("response", lambda r: asyncio.create_task(self._on_response(r)))

            consecutive_failures = 0
            failure_streak_ids: list[str] = []
            for i, row in enumerate(todo, start=1):
                try:
                    profile = await self.fetch_one(page, row["user_id"], row["username"])
                except Exception as exc:
                    logger.error(
                        "[%d/%d] @%s GAGAL total (%s: %s) -- dilewati sesi "
                        "ini, TIDAK ditandai selesai (akan dicoba lagi "
                        "otomatis di sesi berikutnya).",
                        i, len(todo), row["username"], type(exc).__name__, exc,
                    )
                    consecutive_failures += 1
                    if consecutive_failures >= config.MAX_CONSECUTIVE_PROFILE_FAILURES:
                        logger.error(
                            "CIRCUIT BREAKER: %d akun BERTURUT-TURUT gagal (None "
                            "maupun exception timeout). PENYEBAB TIDAK PASTI --"
                            "bisa sesi login kedaluwarsa, TAPI kalau auth baru "
                            "saja diulang dan tetap terjadi, kemungkinan besar "
                            "BUKAN itu. Kandidat lain: wait_until=\"networkidle\" "
                            "macet karena trafik latar belakang Threads (lihat "
                            "README A.10), atau IP/koneksi mulai dibatasi "
                            "server (lihat dokumen desain 3.3). Menghentikan "
                            "sesi ini SEKARANG.",
                            consecutive_failures,
                        )
                        for uid in failure_streak_ids:
                            storage.unmark_done(config.PROFILE_CHECKPOINT, uid)
                            self.done.discard(uid)
                            results[:] = [r for r in results if r["user_id"] != uid]
                        break
                    await inter_account_delay()
                    continue

                results.append(profile.to_dict())
                storage.mark_done(config.PROFILE_CHECKPOINT, row["user_id"])
                self.done.add(row["user_id"])
                logger.info(
                    "[%d/%d] @%s -> follower=%s, views=%s",
                    i, len(todo), row["username"], profile.follower_count, profile.view_count,
                )

                if profile.follower_count is None and profile.view_count is None:
                    consecutive_failures += 1
                    failure_streak_ids.append(row["user_id"])
                else:
                    consecutive_failures = 0
                    failure_streak_ids = []

                if consecutive_failures >= config.MAX_CONSECUTIVE_PROFILE_FAILURES:
                    logger.error(
                        "CIRCUIT BREAKER: %d akun BERTURUT-TURUT gagal profile fetch "
                        "(follower/views tetap None). Kemungkinan besar sesi login "
                        "(auth_state.json) sudah kedaluwarsa -- BUKAN masalah akun "
                        "individual. Menghentikan sesi ini SEKARANG supaya tidak "
                        "membuang sisa kuota sesi untuk data kosong.",
                        consecutive_failures,
                    )
                    for uid in failure_streak_ids:
                        storage.unmark_done(config.PROFILE_CHECKPOINT, uid)
                        self.done.discard(uid)
                        results[:] = [r for r in results if r["user_id"] != uid]
                    logger.error(
                        "Jalankan `python main.py auth` ulang, lalu lanjutkan dengan "
                        "`python main.py profiles` lagi -- %d akun yang baru gagal "
                        "SUDAH dikembalikan ke antrean (bukan permanen kosong).",
                        len(failure_streak_ids),
                    )
                    break

                await inter_account_delay()
                await maybe_batch_cooldown(i)

            await browser.close()

        profiles_path = config.PROCESSED_DIR / "profiles.jsonl"
        storage.append_jsonl(profiles_path, results)
        return len(results)


async def main() -> None:
    storage.ensure_dirs()
    fetcher = ProfileFetcher()
    await fetcher.run()


if __name__ == "__main__":
    asyncio.run(main())
