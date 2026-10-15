# ablation/ -- analisis ablasi

Membandingkan konfigurasi fitur `akun`, `teks`, dan `gabungan` dari prediksi uji run model. Kode ini hanya membaca
`../model/outputs/<run_id>/`: tidak melatih ulang, tidak menjalankan inferensi, dan tidak membaca skor CV. Keluaran
berupa tabel, gambar, dan ringkasan angka.

## Menjalankan

Dari folder induk (`code/`), dengan Python yang memiliki paket di `requirements.txt`:

```
python -m ablation.run [--run-id model_v1] [--features-path PATH] [--cross-split]
```

Exit code 0 = selesai; 1 = validasi atau cross-check gagal (berhenti tanpa menulis keluaran).

## Masukan (pemetaan di `config.py`)

| Data | Sumber di run model |
|---|---|
| prediksi per akun uji (`user_id`, `y_true`, `y_pred`), 9 sel | `test_predictions.csv` (sel = filter `split` x `config`) |
| cross-check metrik (TP/FP/FN/TN, akurasi, P/R/F1 buzzer, makro-F1) | `test_metrics.csv` (opsional) |
| cross-check baseline mayoritas | `baselines.csv` (opsional) |
| K per sel (hanya metadata manifest) | `test_metrics.csv` kolom `k` |

Validasi (gagal -> berhenti): 9 sel ada; `user_id` unik per sel; `y_true`/`y_pred` bernilai {0, 1} tanpa nilai kosong;
pasangan split/konfigurasi dikenal; per split, himpunan `user_id` dan `y_true` per akun identik di ketiga konfigurasi;
TP+FP+FN+TN = `n_test`. Makro-F1 dicek terhadap `sklearn` dan metrik model (toleransi 1e-9).

## Keluaran -- `output/<run_id>/`

| Berkas | Isi |
|---|---|
| `ablasi_tabel_9sel.csv` | per sel: n_test, support, TP/FP/FN/TN, makro-F1, akurasi, `tak_terdefinisi` |
| `ablasi_agregat.csv` | per konfigurasi x metrik: mean, std (ddof=1), min, maks, nilai per split; + baris `baseline_mayoritas` |
| `ablasi_delta.csv` | `kontribusi_teks`, `kontribusi_akun`, `akun_vs_teks` per split + mean, std (ddof=1) |
| `ablasi_perkelas.csv` | P/R/F1 buzzer dan non-buzzer, spesifisitas, TP/FP/FN/TN per sel + agregat buzzer |
| `ablasi_peringkat.csv` | peringkat makro-F1 per split (seri < 1e-12 = peringkat sama) + jumlah juara per konfigurasi |
| `ablasi_baseline.csv` | baseline mayoritas per split: akurasi = p, makro-F1 = p / (1 + p) |
| `ablasi_pola_error_per_akun.csv` | `ringkasan_pola` (jumlah akun per split x y_true x 8 pola benar/salah) dan `per_akun` (dengan `kode_anonim`) |
| `ablasi_mapping_anonim.csv` | internal: `user_id` -> `kode_anonim` |
| `fig_makrof1_per_konfigurasi.png`, `fig_perkelas_buzzer.png` | 300 dpi, konfigurasi dibedakan dengan pola isi/penanda |
| `ablasi_ringkasan.md` | tabel angka hasil |
| `manifest.json` | waktu, checksum masukan/keluaran, pemetaan sel, hasil cross-check, ddof, K per sel, versi pustaka |

Opsional: `--cross-split` -> `ablasi_lintas_split.csv` (per `kode_anonim`: jumlah split uji dan jumlah salah per
konfigurasi). `--features-path` -> `ablasi_fitur_mentah_pola_menarik.csv` (8 fitur mentah untuk akun yang benar hanya
oleh satu konfigurasi atau salah di ketiganya); fitur yang sudah diskalakan dilaporkan dan tidak di-inverse.

`user_id`, `username`, dan `caption_text` tidak muncul di keluaran selain berkas mapping. Dua kali jalan menghasilkan
berkas identik (kecuali stempel waktu di `manifest.json`).
