"""Konfigurasi terpusat untuk scraper Threads #StillPrabowo."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


# Topik dan jendela observasi
TAG_NAME = "stillprabowo"
WINDOW_START = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 3, 23, 59, 59, tzinfo=timezone.utc)
LITERAL_TAG_PATTERN = re.compile(r"#?\s*still\s*prabowo", re.IGNORECASE)


# URL Threads
BASE_URL = "https://www.threads.com"
SEARCH_URL = f"{BASE_URL}/search?q={TAG_NAME}&serp_type=default"


def profile_url(username: str) -> str:
    return f"{BASE_URL}/@{username}"


PROFILE_TAB_URL_SUFFIX = {
    "threads": "",
    "replies": "/replies",
    "reposts": "/reposts",
}


def profile_tab_path(username: str, tab_name: str) -> str:
    """Path relatif (tanpa domain) ke satu tab profil, mis. "/@user/reposts"."""
    return f"/@{username}{PROFILE_TAB_URL_SUFFIX[tab_name]}"


def profile_tab_url(username: str, tab_name: str) -> str:
    """URL langsung ke satu tab profil."""
    return f"{profile_url(username)}{PROFILE_TAB_URL_SUFFIX[tab_name]}"


GRAPHQL_URL_HINT = "/graphql/query"


# Lokasi data, checkpoint, log, dan sesi login
DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
DISCOVERY_RAW = RAW_DIR / "discovery"
PROFILE_RAW = RAW_DIR / "profile"
FEED_RAW = RAW_DIR / "feed"
ENGAGEMENT_RAW = RAW_DIR / "engagement"
PROCESSED_DIR = DATA_DIR / "processed"
RAW_POSTS_FILE = PROCESSED_DIR / "raw_posts_all.jsonl"
QUALIFYING_POSTS_FILE = PROCESSED_DIR / "qualifying_posts.jsonl"
QUALIFYING_POSTS_CSV_FILE = PROCESSED_DIR / "qualifying_posts.csv"
UNIQUE_ACCOUNTS_FILE = PROCESSED_DIR / "unique_accounts.csv"
ACCOUNT_FEATURES_FILE = PROCESSED_DIR / "dataset_akun_fitur.csv"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
DISCOVERY_CHECKPOINT = CHECKPOINT_DIR / "discovery_seen_pk.json"
PROFILE_CHECKPOINT = CHECKPOINT_DIR / "profile_done_users.json"
FEED_CHECKPOINT = CHECKPOINT_DIR / "feed_done_users.json"
ENGAGEMENT_CHECKPOINT = CHECKPOINT_DIR / "engagement_done_seeds.json"
LOG_DIR = Path("logs")
STORAGE_STATE_PATH = Path("auth_state.json")


# Jeda anti-ban
DELAY_MIN_SEC = 3.0
DELAY_MAX_SEC = 7.0
POST_NAVIGATION_DELAY_MIN_SEC = 4.0
POST_NAVIGATION_DELAY_MAX_SEC = 8.0
PROFILE_NAVIGATION_TIMEOUT_MS = 60_000
INTER_ACCOUNT_DELAY_MIN_SEC = 5.0
INTER_ACCOUNT_DELAY_MAX_SEC = 12.0
BATCH_SIZE_FOR_COOLDOWN = 10
BATCH_COOLDOWN_MIN_SEC = 60.0
BATCH_COOLDOWN_MAX_SEC = 180.0


# Batas per sesi dan toleransi kegagalan beruntun
MAX_ACCOUNTS_PER_SESSION = 52
PARTIAL_ACCOUNT_QUOTA_PER_SESSION = 15
MAX_CONSECUTIVE_PROFILE_FAILURES = 3
MAX_CONSECUTIVE_ENGAGEMENT_FAILURES = 3
MAX_CONSECUTIVE_FEED_FAILURES = 3


# Perluasan populasi lewat reply
MAX_REPLY_THREAD_SCROLLS = 30
REPLY_CAP_PER_SEED = 30
MIN_REPLY_CAPTION_LENGTH = 20
MAX_SEEDS_PER_SESSION = 40


# Batas scroll dan waktu per halaman/tab
MAX_STALE_SCROLLS = 5
SAVE_STALLED_FEED_SCREENSHOT = True
MAX_DISCOVERY_PAGES = 200
MAX_FEED_SCROLLS_PER_ACCOUNT = 150
MAX_TAB_IDLE_SECONDS = 120
MAX_TAB_FETCH_SECONDS = 1200


# Retry dan browser
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SEC = 5.0
HEADLESS = True
PROFILE_FEED_TABS = {
    "threads": "Threads",
    "replies": "Replies",
    "reposts": "Reposts",
}
