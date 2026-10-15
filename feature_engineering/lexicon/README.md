# lexicon/

`lexicon_a.txt` dan `lexicon_b.txt` (path di `../config/feature_config.yaml`) dibuat oleh `../convert_lexicon_csv.py`
dari `../../data_inputs/leksikon_a_b_data_terseleksi.csv`. Format: satu istilah per baris, huruf kecil, boleh frasa
multi-kata; baris kosong dan baris berawalan `#` diabaikan. Duplikat (setelah pembersihan dan tokenisasi yang sama
dengan teks) dibuang sebelum menghitung jumlah entri; istilah yang mengandung tanda baca pemisah segmen ditolak.

Bila salah satu berkas tidak ada, `run_features.py` berhenti di tahap leksikon (exit code 2) tanpa menulis keluaran.
