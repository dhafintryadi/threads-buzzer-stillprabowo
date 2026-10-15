"""Ambil daftar akun UNIK dari qualifying_posts.jsonl."""

from __future__ import annotations

import config
import storage
from utils.logging_setup import get_logger

logger = get_logger("account_extract")


def run() -> int:
    storage.ensure_dirs()

    accounts: dict[str, str] = {}
    for post in storage.read_jsonl(config.QUALIFYING_POSTS_FILE):
        uid = post.get("user_id")
        uname = post.get("username")
        if uid and uid not in accounts:
            accounts[uid] = uname or ""

    rows = [{"user_id": uid, "username": uname} for uid, uname in accounts.items()]
    storage.write_csv(config.UNIQUE_ACCOUNTS_FILE, rows, fieldnames=["user_id", "username"])

    logger.info("Ditemukan %d akun unik -> %s", len(rows), config.UNIQUE_ACCOUNTS_FILE)
    return len(rows)


if __name__ == "__main__":
    run()
