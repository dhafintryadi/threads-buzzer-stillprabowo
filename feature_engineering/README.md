# feature_engineering/ -- rekayasa fitur

Membentuk 8 fitur per akun dari `clean_data_text_preprocessed.csv`, membuat 3 split latih/uji stratified (70:30,
80:20, 90:10), dan menskalakan fitur dengan parameter dari data latih. Keluaran dipakai `../model/`.

## Menjalankan

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe convert_lexicon_csv.py      # hanya bila CSV leksikon berubah
venv\Scripts\python.exe run_features.py
```

Exit code: 0 selesai; 1 validasi/pemeriksaan gagal; 2 berkas leksikon tidak ada. Tidak ada berkas yang ditulis bila
salah satu pemeriksaan gagal.

## Masukan

- `../preprocess/data/processed/clean_data_text_preprocessed.csv`. Nama kolom dipetakan di `config/feature_config.yaml`
  (`columns`); kolom wajib yang hilang menghentikan eksekusi.
- `lexicon/lexicon_a.txt`, `lexicon/lexicon_b.txt`: dibuat oleh `convert_lexicon_csv.py` dari
  `../data_inputs/leksikon_a_b_data_terseleksi.csv` (istilah = `entri` + `varian_pencocokan`). Ubah leksikon di CSV,
  bukan di berkas txt.

## Fitur

| Fitur | Definisi |
|---|---|
| `pengikut` | `follower_count` |
| `rasio_balasan` | `replies_count / items_scanned` |
| `rasio_unggahan_ulang` | `reposts_count / items_scanned` |
| `threads_topik` | `threads_topik` |
| `balasan_topik` | `balasan_topik` |
| `similarity` | rata-rata cosine similarity TF-IDF (`caption_text_clean`) terhadap korpus latih; akun latih tanpa dirinya sendiri |
| `kepadatan_leksikon_a`, `kepadatan_leksikon_b` | total kemunculan istilah leksikon di `caption_text` / jumlah token akun (akun tanpa token -> 0) |

Konfigurasi fitur: `akun` (5 fitur pertama), `teks` (3 fitur terakhir), `gabungan` (8). Scaler di-fit sekali per split
pada 8 fitur; konfigurasi hanya memilih subset kolom.

## Alur

1. Row-wise, sebelum split (`fe/validate.py`, `fe/account_features.py`, `fe/lexicon.py`): validasi, 5 fitur akun,
   kepadatan leksikon. Teks leksikon dibersihkan dengan `clean_shared` dari `../preprocess/text_streams/shared_clean.py`,
   tanpa stopword removal dan stemming; pencocokan urutan token persis, terpanjang dulu, tanpa tumpang tindih, tidak
   melintasi tanda baca.
2. Split (`fe/split.py`): `train_test_split` stratified pada `label`, seed tetap per rasio (`split.seeds`).
3. Per split, di-fit hanya pada data latih (`fe/similarity.py`, `fe/scaling.py`): TF-IDF dan `similarity`; outlier
   Tukey 1,5 IQR; z-score untuk semua fitur bila lebih dari satu fitur ber-IQR > 0 memiliki proporsi outlier > 0,05,
   selain itu min-max.

## Konfigurasi penting (`config/feature_config.yaml`)

- `lexicon.denominator: tokens` -- penyebut kepadatan leksikon.
- `lexicon.version`, `lexicon.frozen`, `lexicon.frozen_sha256` -- leksikon beku; FE menolak berjalan bila isi
  `lexicon/*.txt` berbeda dari SHA-256 beku. Byte kedua berkas dipertahankan di git (`.gitattributes`).
- `scaler.confirmed` -- status aturan penskalaan; diperiksa oleh tahap model.

## Keluaran -- `features_sensitivity_token/`

| Berkas | Isi |
|---|---|
| `split_{70_30,80_20,90_10}/train.csv`, `test.csv` | `user_id`, 8 fitur terskala, `label` |
| `feature_config.json` | daftar fitur per konfigurasi |
| `report.json`, `report.md` | seed, jumlah akun/buzzer per split, distribusi kepadatan leksikon, outlier per fitur, metode dan parameter scaler, pemeriksaan, peringatan, hash input/config/leksikon, `lexicon_freeze`, `scaling_status` |
| `split_manifest.json` | `user_id` latih/uji dan SHA-256 CSV per split |

Pemeriksaan (gagal -> berhenti): rasio dalam [0, 1]; tanpa NaN/inf; latih + uji = jumlah baris dan tanpa `user_id`
ganda; proporsi buzzer latih/uji dalam `split.stratify_tolerance`; TF-IDF dan scaler di-fit pada jumlah sampel latih;
`similarity` dalam [0, 1]. Kepadatan leksikon yang > 50% bernilai 0 hanya dilaporkan.
