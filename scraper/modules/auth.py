"""Login SATU KALI secara manual (browser non-headless), lalu simpan sesi (cookies + local storage) ke `auth_state.json`."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright
from playwright._impl._errors import TargetClosedError

import config
from utils.logging_setup import get_logger

logger = get_logger("auth")


async def interactive_login() -> None:
    profile_dir = str(config.DATA_DIR / "browser_profile")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            channel="chrome",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(config.BASE_URL)

        print(
            "\n=== LOGIN MANUAL ===\n"
            "1. Login ke akun dedicated di jendela browser yang terbuka.\n"
            "2. Pastikan sudah masuk ke halaman utama Threads (bukan halaman login).\n"
            "3. JANGAN tutup jendela browser sebelum menekan Enter di sini.\n"
            "4. Kembali ke terminal ini, lalu tekan Enter untuk menyimpan sesi.\n"
        )
        input("Tekan Enter setelah login selesai...")

        try:
            await context.storage_state(path=str(config.STORAGE_STATE_PATH))
            logger.info("Sesi login disimpan ke %s", config.STORAGE_STATE_PATH)
        except TargetClosedError:
            logger.error(
                "Browser sudah tertutup sebelum sesi sempat disimpan -- "
                "kemungkinan kamu menutup jendela browser secara manual "
                "(mis. karena macet di captcha) sebelum menekan Enter. "
                "Sesi TIDAK tersimpan. Jalankan ulang `python main.py auth` "
                "dan pastikan jendela browser tetap terbuka sampai proses "
                "ini benar-benar selesai. Kalau captcha terus berulang, "
                "lihat `modules/auth_import_cookies.py` sebagai alternatif "
                "(login manual di Chrome harian, bukan lewat Playwright)."
            )
            return

        try:
            await context.close()
        except (TargetClosedError, asyncio.CancelledError) as exc:
            logger.warning(
                "Browser tidak tertutup mulus (%s) -- TIDAK masalah, sesi "
                "login SUDAH tersimpan sebelum ini terjadi. Aman lanjut ke "
                "modul berikutnya.", type(exc).__name__,
            )


if __name__ == "__main__":
    asyncio.run(interactive_login())


if __name__ == "__main__":
    asyncio.run(interactive_login())
