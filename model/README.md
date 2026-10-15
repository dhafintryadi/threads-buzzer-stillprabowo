# model/ -- K-NN: SMOTE, tuning K, pelatihan akhir, evaluasi uji

Melatih dan mengevaluasi K-NN pada 9 sel: split 70:30 / 80:20 / 90:10 x konfigurasi fitur `akun` (5) / `teks` (3) /
`gabungan` (8), dari keluaran `../feature_engineering/features_sensitivity_token/`.

## Alur per sel

1. SMOTE bila pangsa kelas minoritas latih < `imbalance.minority_share_threshold` (`sampling_strategy: auto`,
   `k_neighbors: 5`), hanya pada data latih terskala.
2. Tuning K in {3, 5, 7, 9}: 5-fold StratifiedKFold (shuffle) pada data latih hasil SMOTE; K dipilih menurut rata-rata
   macro-F1, seri -> K lebih besar. Skor CV hanya untuk memilih K.
3. Latih akhir dengan K terpilih pada seluruh data latih hasil SMOTE.
4. Evaluasi sekali pada data uji asli: confusion matrix, accuracy, precision/recall/F1 kelas buzzer, macro-F1, dan
   pembanding "selalu non-buzzer".

Model tidak men-fit scaler; split dan penskalaan dari tahap rekayasa fitur dipakai apa adanya. Seed per sel diturunkan
secara deterministik dari `run.random_state_global`, split, dan konfigurasi.

## Berkas

| Berkas | Isi |
|---|---|
| `config.yaml` | seluruh parameter run; nilai yang terkunci (split, grid K, 5 fold, daftar fitur, Euclidean, macro-F1) divalidasi saat dimuat |
| `common.py` | config + `config_sha256`, loader dengan daftar putih kolom, seed turunan, manifest run |
| `m00_checks.py` | gerbang prasyarat 1-7; membuat `split_manifest.json` cadangan bila tidak ada |
| `m01_scaling_diagnostics.py` | `scaling_diagnostics.csv` (deskriptif, tanpa fit, tanpa label) |
| `m02_imbalance.py` | keputusan ketidakseimbangan per split + SMOTE |
| `m03_tuning.py` | CV, pemilihan K, penanda pemilihan K lemah |
| `m04_train_eval.py` | latih akhir, metrik uji, confusion matrix, prediksi, pembanding |
| `run_all.py` | perintah `checks` / `freeze` / `tune` / `run` |

## Menjalankan

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.lock.txt
venv\Scripts\python.exe run_all.py checks   # gerbang + diagnostik penskalaan; tidak menyentuh data uji
venv\Scripts\python.exe run_all.py freeze   # tulis config_sha256 ke run_manifest.json
venv\Scripts\python.exe run_all.py tune     # tuning saja, tanpa data uji
venv\Scripts\python.exe run_all.py run      # gerbang 1-7 -> diagnostik -> SMOTE -> tuning -> evaluasi
```

Gerbang prasyarat (gagal -> berhenti):

1. Leksikon beku di config FE dan SHA-256 leksikon saat fitur dihasilkan sama dengan SHA-256 beku.
2. `scaler.confirmed: true` di config FE, metode penskalaan per split tercatat.
3. Jumlah akun dan buzzer sesuai `expected`, `user_id` unik dan latih/uji terpisah, penyebut leksikon sesuai
   `input_variant`, isi CSV cocok dengan `split_manifest.json`.
4. Kolom tepat `user_id`, `label`, dan 8 fitur; tanpa NaN/inf.
5. Selisih stratifikasi latih/uji <= 1 akun.
6. Data latih terstandar sesuai metode FE (z-score: mean 0, std 1; min-max: [0, 1]) dan data uji tidak di-fit sendiri.
7. `config_sha256` di manifest sama dengan config saat ini.

Evaluasi uji hanya sekali per `run_id`: kunci ditulis sebelum data uji dibaca. Perubahan config setelah evaluasi
memerlukan `run_id` baru dengan `run.supersedes: {run_id, reason}`. Run `model_v1` sudah dievaluasi.

## Keluaran -- `outputs/{run_id}/`

| Berkas | Isi |
|---|---|
| `cv_results.csv` | skor per K x fold (F1 buzzer, macro-F1, precision, recall, accuracy) |
| `best_k.csv` | K terpilih per sel, rata-rata/SD macro-F1 per K, penanda pemilihan K lemah |
| `smote_log.csv` | ukuran latih sebelum/sesudah SMOTE per sel |
| `scaling_diagnostics.csv` | statistik deskriptif fitur latih/uji per split |
| `test_metrics.csv` | 9 baris: K, TP/FP/FN/TN (hitungan dan persentase), accuracy, precision, recall, F1, macro-F1 |
| `confusion_matrices.csv`, `test_predictions.csv` | confusion matrix per sel; prediksi per akun uji |
| `baselines.csv` | pembanding "selalu non-buzzer" per split |
| `run_manifest.json` | config dan hash-nya, hasil gerbang, hash masukan, versi pustaka, SHA-256 lockfile, K per sel, waktu evaluasi |
