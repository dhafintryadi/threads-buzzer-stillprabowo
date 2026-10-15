# scraper/ -- pengumpulan data Threads #StillPrabowo

Mengumpulkan post bertagar/literal #StillPrabowo dalam jendela observasi 20 Agu - 3 Sep 2026 (UTC), memperluas
populasi lewat balasan pada post yang relevan, lalu menghitung fitur aktivitas tiap akun. Semua parameter
(tanggal, kriteria topik, batas sesi, jeda anti-ban, path) ada di `config.py`.

## Instalasi

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m playwright install chromium
```

## Login

```
python main.py auth                      # login manual di browser, sesi disimpan ke auth_state.json
python -m modules.auth_import_cookies    # alternatif bila login Playwright terhalang reCAPTCHA
```

Gunakan akun khusus, bukan akun pribadi. `auth_state.json` dan `data/browser_profile/` tidak boleh di-commit.

## Menjalankan

```
python main.py discovery    # 1  pencarian tagar -> data/processed/raw_posts_all.jsonl
python main.py filter       # 2  filter jendela waktu + relevansi topik -> qualifying_posts.jsonl/.csv
python main.py engagement   # 1b perluasan populasi lewat balasan pada post seed
python main.py accounts     # 3  akun unik -> unique_accounts.csv
python main.py profiles     # 4  follower_count dan view_count -> profiles.jsonl
python main.py feeds        # 5  hitungan threads/replies/reposts dalam jendela -> feed_counts.jsonl
python main.py build        # 6  tabel fitur akun -> dataset_akun_fitur.csv
python main.py status       # progres checkpoint (read-only)
```

Setiap tahap melanjutkan dari `data/checkpoints/` bila dijalankan ulang; `profiles`, `feeds`, dan `engagement`
berhenti sendiri saat batas per sesi tercapai, jalankan ulang perintah yang sama pada sesi berikutnya.
`python main.py all` menjalankan semua tahap sekali berurutan (tanpa pengulangan lintas sesi).

## Keluaran untuk preprocess

| Berkas | Isi |
|---|---|
| `data/processed/dataset_akun_fitur.csv` | satu baris per akun: follower, hitungan aktivitas, `items_scanned`, `stopped_reason` |
| `data/processed/qualifying_posts.csv` | satu baris per post/balasan yang lolos kriteria |
| `data/checkpoints/feed_done_users.json` | status per tab per akun (sumber `bound_type` di preprocess) |

Scraping bergantung pada platform yang berubah sehingga tidak dapat direproduksi persis; data hasil scraping
(`data/`) adalah titik awal pipeline yang dibekukan dan tidak dilacak git.
