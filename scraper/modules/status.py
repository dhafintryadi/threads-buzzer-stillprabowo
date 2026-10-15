"""Laporkan progres checkpoint tiap tahap TANPA menjalankan scraping apa pun (read-only)."""

from __future__ import annotations

import math

import config
import storage
from utils.tab_status import is_censored_tab, is_final_tab
from utils.logging_setup import get_logger

logger = get_logger("status")


def run() -> None:
    print("=" * 60)
    print("STATUS PIPELINE -- threads_scraper (read-only, tidak scraping)")
    print("=" * 60)

    seen_pk = storage.load_checkpoint_set(config.DISCOVERY_CHECKPOINT)
    print(f"\n[1] Discovery : {len(seen_pk)} post unik ditemukan sejauh ini")
    if not seen_pk:
        print("    Belum pernah dijalankan. Mulai dengan: python main.py discovery")
        return

    qualifying = list(storage.read_jsonl(config.QUALIFYING_POSTS_FILE))
    own_match = sum(1 for p in qualifying if p.get("inclusion_criterion") == "own_text_match")
    engaged = sum(1 for p in qualifying if p.get("inclusion_criterion") == "engaged_with_topic")
    print(f"[2] Filter    : {len(qualifying)} post lolos filter tanggal+relevansi "
          f"(qualifying_posts.jsonl) -- {own_match} own_text_match, {engaged} "
          f"engaged_with_topic")
    if not qualifying:
        print("    Belum dijalankan / hasil kosong. Jalankan: python main.py filter")

    seed_done = storage.load_checkpoint_set(config.ENGAGEMENT_CHECKPOINT)
    seed_total = sum(1 for p in qualifying if not p.get("is_reply") and p.get("code"))
    print(f"[2b] Engagement: {len(seed_done)}/{seed_total} post seed sudah di-crawl "
          f"balasannya (engagement_expand.py)")
    if seed_total > len(seed_done):
        remaining = seed_total - len(seed_done)
        sessions_needed = math.ceil(remaining / config.MAX_SEEDS_PER_SESSION) \
            if config.MAX_SEEDS_PER_SESSION else 1
        print(f"     ~{sessions_needed}x jalankan `python main.py engagement` untuk lanjut")

    accounts = storage.read_csv(config.UNIQUE_ACCOUNTS_FILE)
    total_accounts = len(accounts)
    print(f"[3] Accounts  : {total_accounts} akun unik (unique_accounts.csv)")
    if not accounts:
        print("    Belum dijalankan. Jalankan: python main.py accounts")
        return

    profile_done = storage.load_checkpoint_set(config.PROFILE_CHECKPOINT)
    profile_remaining = total_accounts - len(profile_done)
    print(f"\n[4] Profiles  : {len(profile_done)}/{total_accounts} akun selesai "
          f"({profile_remaining} tersisa)")
    if profile_remaining > 0:
        sessions_needed = math.ceil(profile_remaining / config.MAX_ACCOUNTS_PER_SESSION) \
            if config.MAX_ACCOUNTS_PER_SESSION else 1
        print(f"    Perkiraan sesi tersisa (MAX_ACCOUNTS_PER_SESSION="
              f"{config.MAX_ACCOUNTS_PER_SESSION}): ~{sessions_needed}x jalankan "
              f"`python main.py profiles`")

    feed_checkpoint = storage.load_feed_checkpoint(config.FEED_CHECKPOINT)
    feed_accounts = feed_checkpoint.get("accounts", {})

    fully_complete = 0
    partially_done = 0
    not_started = 0
    final_censored = 0
    tab_status_counts: dict[str, dict[str, int]] = {
        tab: {} for tab in config.PROFILE_FEED_TABS
    }

    for row in accounts:
        uid = row["user_id"]
        account_entry = feed_accounts.get(uid)
        if account_entry is None:
            not_started += 1
            continue
        tabs = account_entry.get("tabs", {})
        statuses = [tabs.get(tab, {}).get("status") for tab in config.PROFILE_FEED_TABS]
        for tab in config.PROFILE_FEED_TABS:
            st = tabs.get(tab, {}).get("status", "belum_diproses")
            tab_status_counts[tab][st] = tab_status_counts[tab].get(st, 0) + 1
        if all(is_final_tab(tab, tabs.get(tab)) for tab in config.PROFILE_FEED_TABS):
            fully_complete += 1
            if any(is_censored_tab(tab, tabs.get(tab)) for tab in config.PROFILE_FEED_TABS):
                final_censored += 1
        else:
            partially_done += 1

    feed_remaining = total_accounts - fully_complete
    print(f"\n[5] Feeds     : {fully_complete}/{total_accounts} akun FINAL "
          f"(semua tab complete, atau final-parsial yang tidak akan di-retry)")
    print(f"    {final_censored} di antaranya punya tab final-parsial/disensor "
          f"(cap scroll/waktu atau reposts stalled) -- lower-bound, cek stopped_reason")
    print(f"    {partially_done} akun sebagian (ada tab stalled/stopped_at_cap/invalid/belum diproses)")
    print(f"    {not_started} akun belum tersentuh sama sekali")
    if feed_remaining > 0:
        sessions_needed = math.ceil(feed_remaining / config.MAX_ACCOUNTS_PER_SESSION) \
            if config.MAX_ACCOUNTS_PER_SESSION else 1
        print(f"    Perkiraan sesi tersisa (MAX_ACCOUNTS_PER_SESSION="
              f"{config.MAX_ACCOUNTS_PER_SESSION}): ~{sessions_needed}x jalankan "
              f"`python main.py feeds`")

    print("\n    Rincian status per tab:")
    for tab, counts in tab_status_counts.items():
        detail = ", ".join(f"{k}={v}" for k, v in counts.items()) or "belum ada data"
        print(f"      {tab:8s}: {detail}")

    if config.ACCOUNT_FEATURES_FILE.exists():
        built = storage.read_csv(config.ACCOUNT_FEATURES_FILE)
        print(f"\n[6] Build     : {len(built)} baris di dataset_akun_fitur.csv "
              f"(terakhir dibangun -- jalankan ulang `python main.py build` "
              f"untuk sinkronkan dengan progres terbaru)")
    else:
        print(f"\n[6] Build     : belum pernah dijalankan")

    print("\n" + "=" * 60)
    if profile_remaining == 0 and feed_remaining == 0:
        print("SEMUA AKUN SELESAI. Jalankan `python main.py build` lalu lanjut cleaning.")
    else:
        print("Belum selesai -- jalankan ulang command yang relevan di atas untuk "
              "melanjutkan dari checkpoint (otomatis resume, tidak mengulang dari awal).")
    print("=" * 60)


if __name__ == "__main__":
    run()
