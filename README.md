# Klasifikasi Akun Buzzer Threads #StillPrabowo -- K-NN dan Analisis Ablasi Fitur

Pipeline dari pengumpulan data Threads sampai analisis ablasi tiga konfigurasi fitur K-NN (akun, teks, gabungan) pada
tiga rasio split (70:30, 80:20, 90:10).

## Struktur

| Folder | Tahap | Keluaran utama |
|---|---|---|
| `scraper/` | pengumpulan post #StillPrabowo, profil, dan aktivitas akun | `data/processed/dataset_akun_fitur.csv`, `qualifying_posts.csv` |
| `preprocess/` | validasi, pembersihan, agregasi teks, integrasi (01-04) | `data/processed/clean_data.csv` (626 akun) |
| `preprocess/annotation/` | anotasi Human-LLM (subset manual, prompt beku, tinjauan) | `out/clean_data_labeled.csv` (89 buzzer) |
| `preprocess/` | text preprocessing aliran T (06) | `data/processed/clean_data_text_preprocessed.csv` |
| `feature_engineering/` | 8 fitur, 3 split stratified, penskalaan pada data latih | `features_sensitivity_token/split_*/{train,test}.csv` |
| `model/` | SMOTE, tuning K (macro-F1, 5-fold CV), evaluasi uji sekali jalan | `outputs/model_v1/` |
| `ablation/` | analisis ablasi dari prediksi uji (hanya membaca keluaran model) | `output/model_v1/` |
| `data_inputs/` | leksikon A/B susunan peneliti | `leksikon_a_b_data_terseleksi.csv` |

Setiap folder memiliki README sendiri berisi rincian parameter, kontrak data, dan keluaran.

## Alur data

```
Threads
  -> scraper/data/processed/{dataset_akun_fitur.csv, qualifying_posts.csv}, checkpoints/feed_done_users.json
  -> preprocess 01-04            -> preprocess/data/processed/clean_data.csv
  -> preprocess/annotation A0-A5 -> preprocess/annotation/out/clean_data_labeled.csv
  -> preprocess 06               -> preprocess/data/processed/clean_data_text_preprocessed.csv
  -> feature_engineering         -> feature_engineering/features_sensitivity_token/   (+ data_inputs/ -> lexicon/*.txt)
  -> model                       -> model/outputs/model_v1/
  -> ablation                    -> ablation/output/model_v1/
```

## Lingkungan (Python 3.13)

| Tahap | Lingkungan | Dependensi |
|---|---|---|
| scraper | `scraper/venv` | `scraper/requirements.txt` + `playwright install chromium` |
| preprocess | `preprocess/venv` | `preprocess/requirements.txt` |
| anotasi | Python dengan `preprocess/annotation/requirements.txt` | `OPENAI_API_KEY` untuk tahap A2/A3 |
| feature_engineering | `feature_engineering/venv` | `feature_engineering/requirements.txt` |
| model | `model/venv` | `model/requirements.lock.txt` |
| ablation | Python dengan `ablation/requirements.txt` | -- |

## Menjalankan ulang

```
cd preprocess
venv\Scripts\python.exe main.py all                 # 01-04 -> clean_data.csv
python -m annotation a5                             # label akhir dari state anotasi yang dibekukan
venv\Scripts\python.exe main.py text-preprocess     # 06

cd ..\feature_engineering
venv\Scripts\python.exe run_features.py

cd ..\model
venv\Scripts\python.exe run_all.py checks           # gerbang prasyarat + diagnostik penskalaan

cd ..
python -m ablation.run --run-id model_v1
```

Run model final `model_v1` sudah dievaluasi dan terkunci (evaluasi uji sekali per `run_id`); `run_all.py run` hanya
untuk `run_id` baru. Scraping tidak dapat direproduksi persis karena bergantung pada platform; data hasil scraping
adalah titik awal yang dibekukan.

## Reproduksibilitas

- Seed tetap: split 20261015/20261016/20261017; model `random_state_global` 42 dengan seed turunan per sel.
- Masukan beku diperiksa lewat SHA-256: leksikon `v1` (FE dan gerbang model), pedoman anotasi dan `rules.yaml`
  (anotasi), config model (`config_sha256` di manifest run).
- Setiap tahap menulis manifest berisi SHA-256 masukan/keluaran, parameter, dan versi pustaka.
- Menjalankan ulang preprocess sampai ablasi menghasilkan berkas data yang identik byte demi byte (selain metadata
  stempel waktu).
- `.gitattributes` mempertahankan byte berkas yang di-hash (`*.yaml`, `data_inputs/`, `lexicon/*.txt`, pedoman).

## Tidak dilacak git

- Data berisi data pribadi pengguna Threads (user_id, username, caption): `scraper/data/`, `preprocess/data/processed/`,
  `preprocess/annotation/{state,out,exports,demo}/`, `preprocess/annotation/prompts/fewshot_*.json`, fitur, serta
  keluaran model dan ablasi.
- Rahasia: `auth_state.json`, `browser_profile/`, `.env`, `label_studio_data/`.
