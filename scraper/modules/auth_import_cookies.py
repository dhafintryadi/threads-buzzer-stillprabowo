"""ALTERNATIF untuk modules/auth.py, dipakai kalau login lewat Playwright (auth.py) terus-menerus terjebak reCAPTCHA."""

from __future__ import annotations

import json
import time

import config
from utils.logging_setup import get_logger

logger = get_logger("auth_import_cookies")

TARGET_DOMAINS = ["threads.com", "threads.net", "instagram.com"]


def _cookiejar_to_playwright_state(cookiejar) -> dict:
    """Konversi http.cookiejar.CookieJar (hasil browser_cookie3) menjadi struktur storage_state yang dipahami Playwright."""
    cookies = []
    for c in cookiejar:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "expires": c.expires if c.expires else -1,
            "httpOnly": bool(getattr(c, "_rest", {}).get("HttpOnly", False)),
            "secure": bool(c.secure),
            "sameSite": "Lax",
        })
    return {"cookies": cookies, "origins": []}


def run() -> None:
    try:
        import browser_cookie3
    except ImportError:
        raise SystemExit(
            "Library browser_cookie3 belum terinstal. Jalankan dulu:\n"
            "    pip install browser-cookie3"
        )

    all_cookies = []
    for domain in TARGET_DOMAINS:
        logger.info("Membaca cookie Chrome untuk domain: %s", domain)
        try:
            cj = browser_cookie3.chrome(domain_name=domain)
        except Exception as exc:
            logger.error(
                "Gagal membaca cookie untuk %s: %s. Coba tutup semua "
                "jendela Chrome dulu, lalu jalankan ulang script ini.",
                domain, exc,
            )
            continue
        state = _cookiejar_to_playwright_state(cj)
        all_cookies.extend(state["cookies"])

    if not all_cookies:
        raise SystemExit(
            "Tidak ada cookie ditemukan untuk threads.net/instagram.com. "
            "Pastikan kamu sudah login manual ke akun dedicated di Chrome "
            "harian SEBELUM menjalankan script ini."
        )

    storage_state = {"cookies": all_cookies, "origins": []}
    with config.STORAGE_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(storage_state, f)

    logger.info(
        "%d cookie berhasil diimpor -> %s",
        len(all_cookies), config.STORAGE_STATE_PATH,
    )
    logger.warning(
        "Sesi ini dibuat dari cookie Chrome harian kamu, BUKAN dari sesi "
        "Playwright. Ini valid selama cookie tersebut valid di Chrome. "
        "Verifikasi dengan menjalankan `python main.py profiles` pada "
        "1-2 akun dulu -- kalau follower_count/view_count terisi, sesi "
        "ini berfungsi."
    )


if __name__ == "__main__":
    run()
