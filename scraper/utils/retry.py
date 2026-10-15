"""Retry dengan exponential backoff untuk aksi async yang rawan gagal."""

from __future__ import annotations

import asyncio
import functools
import random
from typing import Callable, TypeVar

import config
from utils.logging_setup import get_logger

logger = get_logger("retry")

T = TypeVar("T")


def async_retry(max_retries: int = config.MAX_RETRIES):
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 -- retry generik disengaja di sini
                    last_exc = exc
                    wait = config.RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1))
                    wait += random.uniform(0, 1.5)
                    logger.warning(
                        "%s gagal (percobaan %d/%d): %s -- retry dalam %.1fs",
                        fn.__name__, attempt, max_retries, exc, wait,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(wait)
            logger.error("%s tetap gagal setelah %d percobaan", fn.__name__, max_retries)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
