"""Jeda acak antar-aksi, antar-akun, dan jeda panjang berkala (strategi anti-ban)."""

from __future__ import annotations

import asyncio
import random

import config
from utils.logging_setup import get_logger

logger = get_logger("rate_limit")


async def polite_delay(min_sec: float = config.DELAY_MIN_SEC, max_sec: float = config.DELAY_MAX_SEC) -> None:
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def post_navigation_delay() -> None:
    """Delay khusus setelah page.goto() -- lihat catatan di config.py."""
    await asyncio.sleep(random.uniform(config.POST_NAVIGATION_DELAY_MIN_SEC, config.POST_NAVIGATION_DELAY_MAX_SEC))


async def inter_account_delay() -> None:
    """Jeda lebih panjang khusus di antara akun (bukan di antara aksi dalam satu akun)."""
    await asyncio.sleep(random.uniform(config.INTER_ACCOUNT_DELAY_MIN_SEC, config.INTER_ACCOUNT_DELAY_MAX_SEC))


async def maybe_batch_cooldown(processed_count: int) -> None:
    """Setiap config.BATCH_SIZE_FOR_COOLDOWN akun, ambil jeda panjang (mensimulasikan jeda istirahat manusia), bukan
    mempertahankan ritme scraping yang konstan sepanjang sesi."""
    if config.BATCH_SIZE_FOR_COOLDOWN <= 0:
        return
    if processed_count % config.BATCH_SIZE_FOR_COOLDOWN != 0:
        return
    wait = random.uniform(config.BATCH_COOLDOWN_MIN_SEC, config.BATCH_COOLDOWN_MAX_SEC)
    logger.info(
        "Cooldown periodik setelah %d akun diproses -- jeda %.0f detik "
        "sebelum lanjut (memecah ritme scraping, bukan bug/macet).",
        processed_count, wait,
    )
    await asyncio.sleep(wait)
