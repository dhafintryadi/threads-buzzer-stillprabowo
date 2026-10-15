"""Menjalankan seluruh tahap secara berurutan."""

from __future__ import annotations

import asyncio

import storage
from modules import (
    discovery, post_filter, engagement_expand, account_extract,
    profile_fetch, feed_fetch, dataset_build,
)
from utils.logging_setup import get_logger

logger = get_logger("pipeline")

STAGES = ["discovery", "filter", "engagement", "accounts", "profiles", "feeds", "build"]


async def run_stage(stage: str) -> None:
    storage.ensure_dirs()
    logger.info("=== Menjalankan tahap: %s ===", stage)

    if stage == "discovery":
        await discovery.main()
    elif stage == "filter":
        post_filter.run()
    elif stage == "engagement":
        await engagement_expand.main()
    elif stage == "accounts":
        account_extract.run()
    elif stage == "profiles":
        await profile_fetch.main()
    elif stage == "feeds":
        await feed_fetch.main()
    elif stage == "build":
        dataset_build.run()
    else:
        raise ValueError(f"Tahap tidak dikenal: {stage}. Pilihan: {STAGES}")

    logger.info("=== Tahap selesai: %s ===", stage)


async def run_all() -> None:
    for stage in STAGES:
        await run_stage(stage)
    logger.info("Pipeline selesai seluruhnya.")


if __name__ == "__main__":
    asyncio.run(run_all())
