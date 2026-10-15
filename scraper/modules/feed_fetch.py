"""Koleksi aktivitas profil dari tab Threads, Replies, dan Reposts."""

from __future__ import annotations

import asyncio
import time

from datetime import datetime, timezone

from playwright.async_api import async_playwright, Response

import config
import storage
from models import FeedCounts
from utils.logging_setup import get_logger
from utils.parsing import (
    classify_post_node,
    detect_blocking_signals,
    find_page_info,
    is_feed_list_payload,
    is_pinned_post,
    matches_topic_criteria,
    select_tab_posts,
)
from utils.rate_limit import inter_account_delay, maybe_batch_cooldown, post_navigation_delay, polite_delay
from utils.retry import async_retry
from utils.tab_status import is_final_tab
from utils.window import window_position

logger = get_logger("feed_fetch")


def _is_graphql(response: Response) -> bool:
    return config.GRAPHQL_URL_HINT in response.url or "graphql" in response.url


class _PrivateProfileError(Exception):
    """Sentinel internal -- akun ternyata privat (lihat FeedFetcher._is_private_profile)."""


def _format_tab_summary(statuses: dict) -> str:
    """Ringkasan status+reason per tab untuk log ringkas."""
    parts = [f"{tab}={info.get('status')}({info.get('reason')})" for tab, info in statuses.items()]
    return ", ".join(parts)


class FeedFetcher:
    _after_items_seen = 0
    _TAB_METRIC_FIELDS = (
        "threads_count", "topic_threads_count", "replies_count", "topic_replies_count",
        "reposts_count", "media_count", "items_scanned", "unclassifiable_items_count",
    )

    def __init__(self) -> None:
        self.checkpoint = storage.load_feed_checkpoint(config.FEED_CHECKPOINT)
        self._pending_payloads: list[tuple[tuple[str, str], dict]] = []
        self._response_tasks: set[asyncio.Task] = set()
        self._active_scope: tuple[str, str] | None = None
        self._responses_seen: dict[tuple, int] = {}
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    def _queue_response(self, response: Response) -> None:
        scope = self._active_scope
        if scope is None or not _is_graphql(response):
            return
        task = asyncio.create_task(self._on_response(response, scope))
        self._response_tasks.add(task)
        task.add_done_callback(self._response_tasks.discard)

    async def _on_response(self, response: Response, scope: tuple[str, str]) -> None:
        try:
            payload = await response.json()
        except Exception:
            return

        self._responses_seen[scope] = self._responses_seen.get(scope, 0) + 1

        blocked = detect_blocking_signals(payload)
        if blocked:
            logger.error(
                "SINYAL BLOCKING TERDETEKSI saat feed fetch akun %s (%s) -- "
                "pertimbangkan menghentikan sesi manual dan cek akun/IP.",
                scope[0], blocked,
            )

        if is_feed_list_payload(payload):
            self._pending_payloads.append((scope, payload))
        elif (
            isinstance(payload, dict)
            and isinstance((payload.get("data") or {}).get("data", {}).get("posts"), list)
        ):
            user_id, tab_name = scope
            storage.dump_raw_response(
                config.FEED_RAW,
                f"{self.run_id}_{user_id}_{tab_name}_unsupported_metrics",
                payload,
            )
        else:
            user_id, tab_name = scope
            storage.dump_raw_response(
                config.FEED_RAW,
                f"{self.run_id}_{user_id}_{tab_name}_unmatched_shape",
                payload,
            )

    async def _settle_responses(self) -> None:
        tasks = tuple(self._response_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _drain_tab(
        self,
        counts: FeedCounts,
        user_id: str,
        username: str,
        tab_name: str,
        seen_pk: set[str],
        response_seq: int,
    ) -> tuple[bool, bool, int]:
        scope = (user_id, tab_name)
        queued = [payload for item_scope, payload in self._pending_payloads if item_scope == scope]
        self._pending_payloads = [item for item in self._pending_payloads if item[0] != scope]
        reached_start = no_next_page = False

        for payload in queued:
            response_seq += 1
            storage.dump_raw_response(
                config.FEED_RAW,
                f"{self.run_id}_{username}_{tab_name}_{response_seq:05d}",
                payload,
            )
            page_info = find_page_info(payload)
            no_next_page = no_next_page or (page_info is not None and page_info.get("has_next_page") is False)

            target_posts = select_tab_posts(payload, tab_name, user_id)
            target_fields = [classify_post_node(post, "feed") for post in target_posts]

            page_has_within = page_has_old = False
            for post, fields in zip(target_posts, target_fields):
                if not fields.get("taken_at"):
                    continue
                position = window_position(fields["taken_at"])
                if position == "within":
                    page_has_within = True
                elif position == "before" and not is_pinned_post(post):
                    page_has_old = True
            if page_has_old and not page_has_within:
                reached_start = True

            for fields in target_fields:
                if fields["pk"] in seen_pk or not fields.get("taken_at"):
                    continue
                seen_pk.add(fields["pk"])
                position = window_position(fields["taken_at"])
                if position == "after":
                    self._after_items_seen += 1
                if position != "within":
                    continue

                if fields["is_partial_schema"]:
                    counts.unclassifiable_items_count += 1
                    continue

                if tab_name == "threads" and fields["is_reply"]:
                    continue
                if tab_name == "replies" and not fields["is_reply"]:
                    continue

                counts.items_scanned += 1
                relevant = matches_topic_criteria(fields["tag_header_name"], fields["caption_text"])
                if tab_name == "threads":
                    counts.threads_count += 1
                    counts.topic_threads_count += int(relevant)
                elif tab_name == "replies":
                    counts.replies_count += 1
                    counts.topic_replies_count += int(relevant)
                else:
                    counts.reposts_count += 1
                if fields["has_media"]:
                    counts.media_count += 1

        return reached_start, no_next_page, response_seq

    async def _save_stalled_screenshot(self, page, username: str, tab_name: str) -> None:
        if not config.SAVE_STALLED_FEED_SCREENSHOT:
            return
        try:
            path = storage.raw_artifact_path(config.FEED_RAW, f"{self.run_id}_{username}_{tab_name}_stalled", "png")
            await page.screenshot(path=str(path))
            logger.info("Screenshot diagnostik tab stalled disimpan: %s", path)
        except Exception as exc:  # noqa: BLE001 -- screenshot murni diagnostik, jangan sampai gagal di sini menjatuhkan tab
            logger.warning("Gagal menyimpan screenshot diagnostik untuk @%s tab %s: %s", username, tab_name, exc)

    @staticmethod
    async def _is_private_profile(page) -> bool:
        """Deteksi teks "This profile is private." di halaman."""
        try:
            return await page.get_by_text("This profile is private", exact=False).count() > 0
        except Exception:  # noqa: BLE001 -- pengecekan murni diagnostik, jangan sampai menjatuhkan tab
            return False

    @staticmethod
    async def _has_empty_tab_marker(page, tab_name: str) -> bool:
        """True kalau halaman menampilkan "No reposts yet." -- tab Reposts yang KOSONG sungguhan."""
        if tab_name != "reposts":
            return False
        try:
            return await page.get_by_text("No reposts yet", exact=False).count() > 0
        except Exception:  # noqa: BLE001 -- pengecekan murni diagnostik
            return False

    _WARMUP_TAB_FOR = {"threads": "reposts", "replies": "threads", "reposts": "threads"}

    async def _open_tab(self, page, user_id: str, username: str, tab_name: str) -> None:
        """Navigasi ke tab profil tertentu, mengaktifkan _active_scope tepat saat respons yang relevan untuk tab_name
        mulai mungkin muncul."""
        if tab_name not in self._WARMUP_TAB_FOR:
            self._active_scope = (user_id, tab_name)
            self._responses_seen[self._active_scope] = 0
            await page.goto(
                config.profile_tab_url(username, tab_name),
                wait_until="domcontentloaded",
                timeout=config.PROFILE_NAVIGATION_TIMEOUT_MS,
            )
            if await self._is_private_profile(page):
                raise _PrivateProfileError(username)
            return

        self._active_scope = None
        await page.goto(
            config.profile_tab_url(username, self._WARMUP_TAB_FOR[tab_name]),
            wait_until="domcontentloaded",
            timeout=config.PROFILE_NAVIGATION_TIMEOUT_MS,
        )
        await post_navigation_delay()

        if await self._is_private_profile(page):
            raise _PrivateProfileError(username)

        self._active_scope = (user_id, tab_name)
        self._responses_seen[self._active_scope] = 0
        try:
            tab_path = config.profile_tab_path(username, tab_name)
            await page.locator(f'a[href="{tab_path}"]').first.click(
                timeout=config.PROFILE_NAVIGATION_TIMEOUT_MS
            )
        except Exception as exc:
            logger.warning(
                "@%s: klik tab %s gagal (%s) -- fallback ke navigasi URL langsung.",
                username, config.PROFILE_FEED_TABS[tab_name], exc,
            )
            await page.goto(
                config.profile_tab_url(username, tab_name),
                wait_until="domcontentloaded",
                timeout=config.PROFILE_NAVIGATION_TIMEOUT_MS,
            )

    async def _collect_tab(self, page, counts: FeedCounts, user_id: str, username: str, tab_name: str) -> dict:
        self._pending_payloads.clear()
        seen_pk: set[str] = set()
        seq = stale = scrolls = 0
        items_scanned_at_start = counts.items_scanned
        self._after_items_seen = 0
        absolute_deadline = time.monotonic() + config.MAX_TAB_FETCH_SECONDS
        last_progress_at = time.monotonic()
        try:
            await self._open_tab(page, user_id, username, tab_name)
            await post_navigation_delay()
            await self._settle_responses()

            while True:
                had_payload = any(scope == self._active_scope for scope, _ in self._pending_payloads)
                if had_payload:
                    last_progress_at = time.monotonic()

                now = time.monotonic()
                if now - last_progress_at >= config.MAX_TAB_IDLE_SECONDS:
                    logger.warning(
                        "@%s tab %s -> berhenti paksa setelah IDLE %ds (tidak ada payload "
                        "valid sama sekali sejak progres terakhir) -- %d scroll tercapai, "
                        "stale=%d/%d, %d respons GraphQL tertangkap. Tab ini TIDAK berhenti "
                        "wajar lewat MAX_STALE_SCROLLS -- retryable, metrics parsial (kalau "
                        "ada) dipertahankan di retry berikutnya.",
                        username, tab_name, config.MAX_TAB_IDLE_SECONDS,
                        scrolls, stale, config.MAX_STALE_SCROLLS,
                        self._responses_seen.get(self._active_scope, 0),
                    )
                    return {"status": "stopped_at_cap", "reason": "idle_timeout"}
                if now >= absolute_deadline:
                    logger.warning(
                        "@%s tab %s -> berhenti paksa setelah batas atas mutlak %ds "
                        "tercapai (masih ada progres, tapi sudah kelamaan) -- %d scroll "
                        "tercapai. Retryable, metrics parsial dipertahankan.",
                        username, tab_name, config.MAX_TAB_FETCH_SECONDS, scrolls,
                    )
                    return {"status": "stopped_at_cap", "reason": "wall_clock_timeout"}

                reached_start, no_next_page, seq = self._drain_tab(
                    counts, user_id, username, tab_name, seen_pk, seq
                )
                if reached_start:
                    return {"status": "complete", "reason": "reached_window_start"}
                if no_next_page:
                    return {"status": "complete", "reason": "no_more_pages"}
                if had_payload:
                    stale = 0
                else:
                    stale += 1
                    if stale >= config.MAX_STALE_SCROLLS:
                        seen_count = self._responses_seen.get(self._active_scope, 0)
                        got_real_data = counts.items_scanned > items_scanned_at_start
                        if seen_count == 0:
                            logger.warning(
                                "@%s tab %s -> 0 respons GraphQL sama sekali setelah %d "
                                "scroll -- akun kemungkinan disabled/dinonaktifkan. "
                                "Ditandai account_unavailable (count=0 BUKAN nol sungguhan), "
                                "TIDAK di-retry.",
                                username, tab_name, config.MAX_STALE_SCROLLS,
                            )
                            return {"status": "complete", "reason": "account_unavailable"}
                        if not got_real_data and self._after_items_seen > 0:
                            logger.warning(
                                "@%s tab %s -> %d item, SEMUANYA lebih baru dari jendela; "
                                "pagination macet sebelum mencapai jendela. Ditandai "
                                "stalled_before_window (count=0 BUKAN nol sungguhan).",
                                username, tab_name, self._after_items_seen,
                            )
                            return {"status": "stalled", "reason": "stalled_before_window"}
                        if got_real_data:
                            logger.warning(
                                "@%s tab %s -> STALLED setelah %d scroll -- %d respons "
                                "tertangkap, SEBAGIAN item berhasil diklasifikasi "
                                "(items_scanned %d->%d) tapi pagination macet sebelum "
                                "selesai. Metrics parsial ini akan dipertahankan di "
                                "retry berikutnya.",
                                username, tab_name, config.MAX_STALE_SCROLLS, seen_count,
                                items_scanned_at_start, counts.items_scanned,
                            )
                            await self._save_stalled_screenshot(page, username, tab_name)
                            return {"status": "stalled", "reason": "stalled_after_valid_feed_payload"}
                        if await self._has_empty_tab_marker(page, tab_name):
                            logger.info(
                                "@%s tab %s -> 'No reposts yet' terdeteksi -- tab kosong "
                                "sungguhan (count=0 valid), bukan kegagalan.",
                                username, tab_name,
                            )
                            return {"status": "complete", "reason": "tab_empty_confirmed"}
                        logger.warning(
                            "@%s tab %s -> status invalid (no_valid_feed_payload) setelah "
                            "%d scroll -- %d respons GraphQL tertangkap TAPI TIDAK ADA "
                            "item yang berhasil diklasifikasi. Raw response ada di %s "
                            "untuk diagnosis manual.",
                            username, tab_name, config.MAX_STALE_SCROLLS, seen_count, config.FEED_RAW,
                        )
                        return {"status": "invalid", "reason": "no_valid_feed_payload"}
                if scrolls >= config.MAX_FEED_SCROLLS_PER_ACCOUNT:
                    return {"status": "stopped_at_cap", "reason": "max_scroll_cap"}
                await page.mouse.wheel(0, 3000)
                scrolls += 1
                await polite_delay()
                await self._settle_responses()
        except _PrivateProfileError:
            logger.info(
                "@%s tab %s -> profil privat (belum di-approve follow) -- "
                "ditandai selesai, count=0, TIDAK di-retry.",
                username, tab_name,
            )
            return {"status": "complete", "reason": "private_profile"}
        except Exception as exc:
            logger.warning("@%s tab %s gagal: %s", username, tab_name, exc)
            return {"status": "invalid", "reason": f"error:{type(exc).__name__}"}
        finally:
            self._responses_seen.pop(self._active_scope, None)
            self._active_scope = None
            self._pending_payloads.clear()

    @staticmethod
    def _merge_retryable_tab_result(existing: dict, current: dict) -> dict:
        """Gabungkan hasil attempt baru (current, status invalid/stalled) dengan hasil attempt SEBELUMNYA (existing)
        untuk tab yang sama -- supaya retry yang lebih buruk (mis. macet lebih awal) TIDAK menghapus metrics parsial
        yang sudah berhasil didapat sebelumnya."""
        existing_metrics = (existing or {}).get("metrics") or {}
        current_metrics = (current or {}).get("metrics") or {}
        all_fields = set(existing_metrics) | set(current_metrics)

        merged_metrics = {}
        retained = False
        for field in all_fields:
            e_val = existing_metrics.get(field, 0) or 0
            c_val = current_metrics.get(field, 0) or 0
            best = max(e_val, c_val)
            merged_metrics[field] = best
            if e_val > c_val:
                retained = True

        result = dict(current)
        result["metrics"] = merged_metrics
        result["last_attempt"] = {"retained_metrics_from_previous": retained}
        return result

    @async_retry()
    async def fetch_one(self, page, user_id: str, username: str) -> tuple[FeedCounts, dict]:
        counts = FeedCounts(user_id=user_id)
        existing_tabs = self.checkpoint["accounts"].get(user_id, {}).get("tabs", {})
        statuses = {}

        for tab_name in config.PROFILE_FEED_TABS:
            existing = existing_tabs.get(tab_name, {})
            if is_final_tab(tab_name, existing) and "metrics" in existing:
                for field in self._TAB_METRIC_FIELDS:
                    setattr(counts, field, getattr(counts, field) + existing["metrics"].get(field, 0))
                statuses[tab_name] = existing
                continue

            before = {f: getattr(counts, f) for f in self._TAB_METRIC_FIELDS}
            result = await self._collect_tab(page, counts, user_id, username, tab_name)
            result["metrics"] = {f: getattr(counts, f) - before[f] for f in self._TAB_METRIC_FIELDS}

            if result["status"] != "complete" and existing.get("metrics"):
                result = self._merge_retryable_tab_result(existing, result)
                for field in self._TAB_METRIC_FIELDS:
                    setattr(counts, field, before[field] + result["metrics"].get(field, 0))

            statuses[tab_name] = result

        counts.stopped_reason = ";".join(f"{tab}:{item['reason']}" for tab, item in statuses.items())
        return counts, statuses

    def _is_complete(self, user_id: str) -> bool:
        account = self.checkpoint["accounts"].get(user_id, {})
        tabs = account.get("tabs", {})
        return all(is_final_tab(tab, tabs.get(tab)) for tab in config.PROFILE_FEED_TABS)

    def _save_status(self, user_id: str, statuses: dict) -> None:
        self.checkpoint["accounts"][user_id] = {
            "tabs": statuses,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        storage.save_feed_checkpoint(config.FEED_CHECKPOINT, self.checkpoint)

    def _prioritized_todo(self, rows: list[dict]) -> tuple[list[dict], int, int]:
        """Scheduler: akun BELUM TERSENTUH (tidak ada entry checkpoint sama sekali) diprioritaskan di atas akun
        "retryable" (sudah tersentuh, sebagian/semua tab belum complete)."""
        untouched: list[dict] = []
        retryable: list[dict] = []
        for row in rows:
            uid = row["user_id"]
            if self._is_complete(uid):
                continue
            if uid in self.checkpoint.get("accounts", {}):
                retryable.append(row)
            else:
                untouched.append(row)
        accounts = self.checkpoint.get("accounts", {})
        retryable.sort(key=lambda r: accounts.get(r["user_id"], {}).get("updated_at_utc", ""))
        return untouched + retryable, len(untouched), len(retryable)

    async def run(self) -> int:
        rows = storage.read_csv(config.UNIQUE_ACCOUNTS_FILE)
        todo_all, untouched_count, retryable_count = self._prioritized_todo(rows)
        logger.info(
            "Total akun: %d, sudah valid: %d, sisa: %d (baru=%d, retryable=%d)",
            len(rows), len(rows) - len(todo_all), len(todo_all), untouched_count, retryable_count,
        )
        if not todo_all:
            return 0

        if config.MAX_ACCOUNTS_PER_SESSION is not None and len(todo_all) > config.MAX_ACCOUNTS_PER_SESSION:
            todo = todo_all[: config.MAX_ACCOUNTS_PER_SESSION]
            logger.warning(
                "Batas sesi (MAX_ACCOUNTS_PER_SESSION=%d) tercapai -- memproses "
                "%d dari %d akun tersisa (diprioritaskan akun baru dulu). "
                "Sisanya BELUM diproses, bukan gagal -- jalankan "
                "`python main.py feeds` lagi untuk melanjutkan.",
                config.MAX_ACCOUNTS_PER_SESSION, len(todo), len(todo_all),
            )
        else:
            todo = todo_all

        processed_count = 0
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=config.HEADLESS, channel="chrome")
            context = await browser.new_context(storage_state=str(config.STORAGE_STATE_PATH) if config.STORAGE_STATE_PATH.exists() else None)
            page = await context.new_page()
            page.on("response", self._queue_response)

            consecutive_failures = 0
            for i, row in enumerate(todo, start=1):
                try:
                    counts, statuses = await self.fetch_one(page, row["user_id"], row["username"])
                except Exception as exc:
                    logger.error(
                        "[%d/%d] @%s GAGAL total (%s: %s) -- dilewati sesi "
                        "ini, TIDAK ditandai selesai (akan dicoba lagi "
                        "otomatis di sesi berikutnya).",
                        i, len(todo), row["username"], type(exc).__name__, exc,
                    )
                    failure_statuses = {
                        tab: {"status": "invalid", "reason": "navigation_failed"}
                        for tab in config.PROFILE_FEED_TABS
                    }
                    self._save_status(row["user_id"], failure_statuses)
                    consecutive_failures += 1
                    if consecutive_failures >= config.MAX_CONSECUTIVE_FEED_FAILURES:
                        logger.error(
                            "%d akun BERTURUT-TURUT gagal total -- kalau ini "
                            "bukan kebetulan beberapa akun bermasalah, "
                            "pertimbangkan cek koneksi/sesi login sebelum "
                            "melanjutkan sesi ini.", consecutive_failures,
                        )
                    await inter_account_delay()
                    continue

                consecutive_failures = 0
                self._save_status(row["user_id"], statuses)
                storage.append_jsonl(config.PROCESSED_DIR / "feed_counts.jsonl", [counts.to_dict()])
                processed_count += 1
                logger.info("[%d/%d] @%s -> %s", i, len(todo), row["username"], _format_tab_summary(statuses))
                await inter_account_delay()
                await maybe_batch_cooldown(i)
            await browser.close()
        return processed_count


async def main() -> None:
    storage.ensure_dirs()
    await FeedFetcher().run()


if __name__ == "__main__":
    asyncio.run(main())
