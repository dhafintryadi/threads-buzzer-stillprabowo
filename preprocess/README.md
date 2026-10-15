# preprocess/ -- clean_data, anotasi, text preprocessing

Mengubah keluaran scraper menjadi `clean_data.csv` (tahap 01-04), menerima label dari paket `annotation/`, lalu
menghitung `caption_text_clean` untuk TF-IDF (tahap 06). Rekayasa fitur ada di `../feature_engineering/`.

## Menjalankan

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe main.py all               # 01-04 -> data/processed/clean_data.csv
python -m annotation <perintah>                    # paket anotasi (lihat annotation/README.md)
venv\Scripts\python.exe main.py text-preprocess   # 06 -> data/processed/clean_data_text_preprocessed.csv
```

Tahap juga bisa dijalankan satu per satu: `validate-load`, `clean-account`, `aggregate-text`, `integrate`. Setiap tahap
membaca ulang masukannya dari disk. Semua path dan parameter ada di `config/pipeline_config.yaml`; tahap yang
membutuhkan parameter berhenti bila nilainya `null`.

## Masukan

| Config | Berkas | Isi |
|---|---|---|
| `paths.raw_table_a_akun` | `../scraper/data/processed/dataset_akun_fitur.csv` | data akun (Tabel A) |
| `paths.raw_table_b_teks` | `../scraper/data/processed/qualifying_posts.csv` | data teks unggahan (Tabel B) |
| `paths.raw_feed_checkpoint_json` | `../scraper/data/checkpoints/feed_done_users.json` | status per tab untuk `bound_type` |

Checkpoint dan Tabel A harus berasal dari snapshot yang sama: tahap 01/02 berhenti (`SnapshotMismatchError`) bila
`stopped_reason` Tabel A tidak cocok dengan checkpoint.

## Tahap

| Tahap | Modul | Keluaran (`data/processed/`) |
|---|---|---|
| 01 validasi | `modules/01_validate_load.py` | `data_quality_report.json`; skema kedua CSV dicek fail-fast |
| 02 pembersihan akun | `modules/02_clean_account.py`, `modules/bound_type.py` | `fitur_akun.csv`, `fitur_teks_cascaded.csv`, `removed_rows_log.csv` |
| 03 agregasi teks | `modules/03_aggregate_text.py` | `fitur_teks_aggregated.csv`, `duplicate_diagnostic_report.csv` |
| 04 integrasi | `modules/04_integrate.py` | `clean_data.csv` |
| 06 text preprocessing | `modules/06_text_preprocess_postannotation.py` | `clean_data_text_preprocessed.csv` |

**Populasi.** Setiap tab akun diklasifikasi dari checkpoint: `exact` (complete), `cap` (berhenti di batas scroll/waktu,
nilai batas bawah), `stalled_data` (macet setelah mengumpulkan item, batas bawah), `stalled_zero` (macet tanpa item),
`unobservable` (privat/tidak tersedia). Akun dipertahankan bila semua tab-nya termasuk
`population.allowed_tab_classes` (`exact`, `cap`, `stalled_data`); akun lain dan akun dengan `items_scanned` 0 atau
kosong dicatat di `removed_rows_log.csv`.

**Agregasi teks.** Semua caption akun (post dan balasan) digabung dengan spasi, urut `(taken_at_utc, pk)`; caption
kosong dilewati. Akun tanpa teks dibuang di tahap 04.

**Text preprocessing (aliran T).** `text_streams/shared_clean.py` (lowercase, hapus URL dan mention, hapus `#`,
rapikan spasi), tokenisasi `[a-z]+(?:-[a-z]+)*`, stopword dan stemming Sastrawi kamus bawaan, gabung spasi
(`text_streams/stream_t.py`).

## Kolom

- `clean_data.csv`: `user_id, follower_count, threads_count, replies_count, reposts_count, threads_topik, balasan_topik,
  items_scanned, caption_text`. Hitungan bulat dan tidak pernah kosong.
- `annotation/out/clean_data_labeled.csv` (dibaca, tidak ditulis): kolom `clean_data.csv` + `label` (0/1),
  `label_source`, `final_prompt_version`, `review_changed_label`. Divalidasi saat dibaca (`schema.validate_labeled_contract`):
  `user_id` dan 9 kolom dasar identik dengan `clean_data.csv`, versi prompt sama dengan laporan anotasi.
- `clean_data_text_preprocessed.csv`: semua kolom `clean_data_labeled.csv` + `caption_text_clean`.

## Manifest

`data/processed/run_manifest.json` adalah daftar append-only, satu entri per pemanggilan tahap: SHA-256 masukan dan
keluaran, jumlah baris masuk/keluar/dibuang beserta alasan, versi pustaka, hash config. Tahap 06 juga mencatat hash
`clean_data_labeled.csv`, `clean_data.csv`, laporan anotasi, versi dan hash prompt beku, serta hash kamus Sastrawi.

## Struktur

```
main.py                      CLI
config.py, config/           loader dan parameter
schema.py                    kontrak kolom dan validasi
storage.py                   I/O deterministik dan hashing
manifest.py                  run manifest append-only
modules/                     tahap 01-04 dan 06
text_streams/                pembersihan bersama, aliran T, stemmer
annotation/                  paket anotasi Human-LLM
```
