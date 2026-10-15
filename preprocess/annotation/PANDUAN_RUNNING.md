# Panduan Running Pipeline Anotasi

Dari instalasi Label Studio sampai `clean_data_labeled.csv`, dijalankan lewat notebook `annotation_runner.ipynb`.
Semua perintah ditulis untuk **PowerShell** dan dijalankan dari folder `C:\Users\ASUS\Documents\Scriptshiz\code\preprocess`
kecuali disebut lain.

## Gambaran alur

```
Persiapan (sekali)          Notebook                         Label Studio (manual)
------------------          --------                         ---------------------
Python + paket       -->    0  Persiapan
Label Studio                1  Bekukan pedoman (hash)
API key OpenAI              2  A0 + A1  (63 akun subset)  -->  GATE 1: proyek "GATE 1", label 63 akun, ekspor JSON
                            3  A1b  (31 tuning / 32 validation) <--
                            ·  GATE 2: pratinjau prompt v1
                            4  A2 -> A2b -> v2 ... (loop optimasi sampai prompt beku)
                            5  A3  (626 akun)
                            6  A4                          -->  GATE 3: proyek "GATE 3", tinjau akun buzzer-LLM, ekspor JSON
                            7  A4b                          <--
                            8  A5  -> out\clean_data_labeled.csv + laporan
```

Berkas penting:

| Lokasi (di `annotation\`) | Isi |
|---|---|
| `annotation_runner.ipynb` | notebook penjalan |
| `config.yaml`, `rules.yaml`, `pedoman_anotasi.md` | konfigurasi, Tabel 4, pedoman (dibekukan sebelum GATE 1) |
| `prompts\prompt_vN.yaml`, `prompts\fewshot_vN.json` | prompt per versi |
| `state\` | semua hasil antara (subset, log panggilan LLM, ronde evaluasi, tugas Label Studio) |
| `exports\` | tempat Anda menyimpan ekspor Label Studio (`gate1.json`, `gate3.json`, `demo.json`) |
| `demo\` | tugas, template, dan daftar akun demo (Bagian A+) |
| `out\` | hasil akhir dan `run_manifest.json` |
| `label_studio_data\` | database Label Studio (proyek dan anotasi Anda) |

---

## Bagian A — Persiapan (sekali saja)

### A1. Paket Python untuk notebook

Notebook berjalan di Python miniconda Anda (`(base)`, Python 3.13). `json-repair` sudah terpasang; yang belum hanya
`openai`. Pasang semua sekaligus (aman diulang):

```powershell
python -m pip install -r annotation\requirements.txt
```

Pastikan perintah di atas dijalankan di terminal yang menampilkan `(base)`, karena kernel notebook memakai Python itu.

### A2. Label Studio

Label Studio **1.23.0 sudah terpasang** di `code\.venv-label-studio` (lingkungan terpisah agar tidak bentrok dengan
paket lain). Lewati langkah ini kecuali Anda memasang ulang di komputer lain:

```powershell
python -m venv ..\.venv-label-studio
```

```powershell
..\.venv-label-studio\Scripts\python.exe -m pip install "label-studio==1.23.0"
```

### A3. Menjalankan Label Studio

Buka terminal PowerShell **terpisah** (biarkan terbuka selama bekerja di Label Studio):

```powershell
.\annotation\start_label_studio.ps1
```

- Tunggu sampai muncul `Starting development server at http://localhost:8080/` (pertama kali ±45 detik, berikutnya ±12 detik).
- Buka http://localhost:8080 di browser. Saat pertama kali, buat akun lewat **Sign Up** (akun lokal, hanya tersimpan
  di komputer Anda; email ini tercatat sebagai `annotator_id`/`reviewer_id`).
- Label Studio hanya bisa diakses dari komputer ini (localhost). Hentikan dengan `Ctrl+C` di terminalnya. Proyek dan
  anotasi tetap tersimpan di `annotation\label_studio_data\`.
- Bila muncul `... is not recognized`, terminal tidak berada di folder `code\preprocess`. Dari folder `annotation` jalankan
  `.\start_label_studio.ps1`, atau dari folder mana pun pakai jalur lengkap:
  `& "C:\Users\ASUS\Documents\Scriptshiz\code\preprocess\annotation\start_label_studio.ps1"`
- Bila skrip diblokir oleh kebijakan PowerShell, jalankan:
  `powershell -ExecutionPolicy Bypass -File .\annotation\start_label_studio.ps1`

### A4. API key OpenAI

Siapkan API key dari akun OpenAI Anda. Key **tidak** ditulis ke berkas mana pun: notebook memintanya lewat kolom input
tersembunyi dan hanya menyimpannya selama kernel berjalan.

---

## Bagian A+ — Demo pelabelan (opsional, sebelum pedoman final)

Untuk mencoba pelabelan **sebelum** pedoman dibekukan. Tidak ada yang dibekukan, tidak ada
yang ditulis ke `state\`, dan `guideline.sha256` tetap kosong.

- Akun demo (default 12) dipilih dari **luar** subset resmi, dihitung dengan logika A1 yang sama, sehingga Anda tidak
  melabeli calon label emas dengan pedoman draf. Setengahnya akun yang teksnya menyebut Prabowo/#StillPrabowo agar ada
  contoh yang relevan dengan kampanye.
- Template Label Studio-nya sama persis dengan GATE 1.

Langkah:
1. Notebook: jalankan sel **0. Persiapan**, lalu sel **D** pertama (`demo.build`). Berkas dibuat di `annotation\demo\`.
   (Atau dari terminal: `python -m annotation demo`.)
2. Label Studio: **Create Project** → nama `DEMO - pelabelan` → **Labeling Setup** → **Custom template** → **Code**:
   tempel isi `annotation\demo\label_studio_config_demo.xml` → **Data Import**: `annotation\demo\demo_tasks.json` → **Save**.
3. Labeli seperti GATE 1 (KU, IP1–IP4, label → **Submit**).
4. **Export** → **JSON** → simpan sebagai `annotation\exports\demo.json`.
5. Notebook: jalankan sel **D** kedua (`demo.check`). Tabel menunjukkan isian tiap akun, label menurut Tabel 4
   (`label_tabel4`), apakah label Anda sesuai (`sesuai_tabel4`), dan IP3 menurut kolom. Pada alur resmi, label yang tidak
   sesuai Tabel 4 akan **ditolak**; di demo hanya dilaporkan. (Terminal: `python -m annotation demo-check`.)

Setelah bimbingan dan pedoman final, lanjutkan ke Bagian B. Proyek demo boleh dihapus atau dibiarkan; terpisah dari proyek
resmi. Bila **struktur** kriteria berubah (mis. menambah IP5 atau mengubah nilai KU), kode dan template perlu
disesuaikan dulu; perubahan redaksi atau definisi cukup di pedoman dan prompt. A1 resmi memberi peringatan bila ada akun demo
yang ternyata masuk subset (mis. karena seed atau data berubah).

## Bagian B — Sebelum mulai (finalisasi, sekali)

Urutan ini penting karena A1 membekukan pedoman dan `rules.yaml`.

1. **Pedoman final.** Salin pedoman final Anda ke `annotation\pedoman_anotasi.md` (salinan persis).
2. **Tabel 4 final.** Pastikan `annotation\rules.yaml` sama dengan Tabel 4 pedoman.
3. **Prompt v1.** Periksa `annotation\prompts\prompt_v1.yaml` (sudah berisi teks Anda; `decision_rule` memakai `{{rules}}`
   sehingga otomatis mengikuti `rules.yaml`).
4. **Buka notebook:**

   ```powershell
   jupyter lab annotation\annotation_runner.ipynb
   ```

   (atau buka berkasnya di VS Code dan pilih kernel Python miniconda).

---

## Bagian C — Menjalankan notebook

Jalankan sel dari atas ke bawah dengan `Shift+Enter`. Bila sebuah tahap tidak bisa jalan, muncul pesan
`BERHENTI: ...` yang menjelaskan penyebab dan cara memperbaikinya (bukan error Python). Menjalankan ulang sel aman.

### Langkah 0 — Persiapan

Jalankan sel **0. Persiapan**. Harus tercetak `Mode: PRODUKSI (state/)` dan tahap saat ini. Jalankan sel ini setiap kali
notebook/kernel dibuka ulang. Jangan ubah `USE_MOCK` (hanya untuk uji coba; menulis ke `state_mock\`).

### Langkah 1 — Bekukan pedoman

1. Jalankan sel **1**. Sel mencetak `Hash pedoman saat ini : <64 karakter>`.
2. Salin hash itu ke `annotation\config.yaml`:
   ```yaml
   guideline:
     path: pedoman_anotasi.md
     sha256: <tempel hash di sini>
   ```
3. Jalankan sel 1 lagi sampai tercetak `Cocok`. Mulai saat ini pedoman **tidak boleh diubah**.

### Langkah 2 — A0 + A1 (subset)

Jalankan kedua sel A0 dan A1. Hasil: `Subset: 63 dari 626 akun`, serta berkas
`state\manual_tasks.json` dan `state\label_studio_config_gate1.xml`. `rules.yaml` ikut dibekukan.

### GATE 1 — Pelabelan manual di Label Studio

**Buat proyek:**
1. Di http://localhost:8080 klik **Create Project**.
2. Tab **Project Name**: isi `GATE 1 - Subset manual`.
3. Tab **Labeling Setup**: pilih **Custom template** (kiri bawah), buka tampilan **Code**, hapus isinya, lalu tempel
   seluruh isi `annotation\state\label_studio_config_gate1.xml` (buka dengan Notepad, salin semua). Pratinjau di kanan
   harus menampilkan teks akun, KU, IP1–IP4, dan Label.
4. Tab **Data Import**: unggah `annotation\state\manual_tasks.json`. Harus muncul 63 tugas.
5. Klik **Save**.

**Melabeli:**
- Klik **Label All Tasks** (atau buka tugas satu per satu).
- Untuk setiap akun isi: **KU** (wajib), **IP1–IP4** (boleh dikosongkan bila KU = `tidak`), dan **Label** (wajib).
  Label harus sesuai Tabel 4. Bila tidak, impor di langkah berikut akan ditolak dan menyebut akunnya.
- Klik **Submit**. Untuk mengoreksi, buka tugasnya, ubah, lalu **Update** (jangan membuat anotasi kedua).
- **Jangan** memakai **Skip**: tugas yang di-skip atau punya dua anotasi membuat ekspor ditolak.

**Ekspor:**
1. Di daftar tugas proyek, klik **Export** → pilih **JSON** (bukan JSON-MIN, CSV, atau format lain) → **Export**.
2. Berkas terunduh ke folder Downloads dengan nama seperti `project-1-at-2026-10-....json`.
3. Pindahkan dan ganti namanya menjadi `annotation\exports\gate1.json`.

### Langkah 3 — A1b (impor label manual)

Jalankan sel A1b, lalu sel tabel subset di bawahnya.
- Berhasil: tercetak tabel buzzer/non_buzzer per set (31 tuning, 32 validation) dan berapa TP minimum agar recall ≥ 0,85.
- `BERHENTI ... tidak sesuai Tabel 4`: perbaiki KU/IP atau label akun yang disebut di Label Studio (**Update**), ekspor
  ulang ke `exports\gate1.json` (timpa), jalankan sel A1b lagi.
- `BERHENTI ... Validation set tidak memuat akun buzzer`: subset tidak berisi buzzer di validation; laporkan sebelum lanjut.

### GATE 2 — Pratinjau prompt v1

1. Jalankan sel pratinjau (`VERSION = "v1"`). Periksa pesan **SYSTEM** (bagian beku: peran, konteks, kriteria, aturan,
   respons, opsi) dan pesan **USER** (hanya `# Data akun` + `ANSWER:`). Perhatikan baris
   `bagian beku (system): ... token`; di atas 1.024 token berarti bisa di-*cache* oleh API.
2. Tidak boleh ada `PERINGATAN` tentang `decision_rule`.
3. Jalankan sel **API key**, tempel key Anda di kolom input, tekan Enter.
4. (Disarankan, sekali) hapus tanda `#` di sel **probe** lalu jalankan: ±10 panggilan pendek tanpa data akun untuk
   melihat parameter yang diterima GPT-5 Mini. Isi `llm.reasoning_effort` / `llm.max_completion_tokens` di config hanya
   dengan nilai yang DITERIMA (atau biarkan `null`).

### Langkah 4 — Loop optimasi (A2, A2b)

1. Jalankan sel A2 dengan `VERSION = "v1"` (63 panggilan API). Baca baris **Keputusan**:
   - `... >= 0.85` dan `Prompt v1 DIBEKUKAN` → lanjut ke Langkah 5.
   - `Lanjut optimasi` → lanjut ke poin 2.
   - Ada akun gagal (error API/parse) → jalankan ulang sel yang sama; akun yang sudah selesai tidak dipanggil lagi.
2. Jalankan sel tabel ronde (recall per versi + biaya) dan sel **A2b**. Tabel kandidat menampilkan akun tuning yang
   isiannya berbeda dari label manual; kolom `diff_fields` menunjukkan bidang yang keliru (KU/IP/label).
3. Buat versi berikutnya (jangan mengubah versi yang sudah dievaluasi):
   - Salin `prompts\prompt_v1.yaml` menjadi `prompts\prompt_v2.yaml`, perjelas kriteria yang sering keliru.
   - Opsional few-shot: buat `prompts\fewshot_v2.json` berisi akun **tuning** dari tabel kandidat, mis.
     `[{"user_id": "<user_id_tuning_1>"}, {"user_id": "<user_id_tuning_2>"}]`, lalu di `prompt_v2.yaml` isi
     `fewshot_ref: fewshot_v2.json`.
4. Pratinjau lagi (ubah `VERSION = "v2"` di sel pratinjau), lalu jalankan sel A2 dengan `VERSION = "v2"`.
5. Ulangi sampai prompt dibekukan. Setelah v4 (v1 + 3 revisi) prompt dibekukan otomatis.

> **Pemindahan validation → tuning (pengecualian I2, dicatat).** `python -m annotation move-to-tuning --user-id <id> --reason "<alasan>"` memindahkan akun, mencatatnya di `state/split_moves.csv`, dan menghitung ulang semua ronde pada split baru tanpa panggilan API. Recall validation sesudahnya bias optimistis.

### Langkah 5 — A3 (seluruh akun)

Jalankan sel A3 (±626 panggilan). Ulangi sel yang sama bila ada akun gagal, sampai tercetak `626/626 akun berlabel`.
Sel juga menampilkan ringkasan token dan perkiraan biaya.

### Langkah 6 — A4 (tugas tinjauan)

Jalankan sel A4. Hasil: `state\review_tasks.json` (akun buzzer-LLM **di luar** subset; akun subset tetap memakai label
manual) dan `state\label_studio_config_gate3.xml`.

### GATE 3 — Tinjauan di Label Studio

**Buat proyek baru** (terpisah dari GATE 1):
1. **Create Project** → nama `GATE 3 - Tinjauan buzzer-LLM`.
2. **Labeling Setup** → **Custom template** → **Code**: tempel isi `annotation\state\label_studio_config_gate3.xml`.
3. **Data Import**: unggah `annotation\state\review_tasks.json` → **Save**.
4. Buka **Settings → Annotation**, aktifkan **Use predictions to prelabel tasks**, pilih set prediksi yang tersedia
   (nama model/versi prompt), lalu simpan. Dengan ini label LLM tampil sebagai pra-isian.
5. Di daftar tugas (Data Manager), sembunyikan kolom `llm_ku` dan `llm_ip1`–`llm_ip4` lewat menu kolom bila tampil,
   agar Anda menilai tanpa melihat penjelasan LLM.

**Meninjau:** untuk setiap akun, isi KU dan IP1–IP4 sendiri, lalu **konfirmasi** label pra-isian atau **koreksi** menjadi
`non_buzzer` sesuai Tabel 4 → **Submit**. Aturan Skip/anotasi ganda sama dengan GATE 1.

**Ekspor:** **Export** → **JSON** → pindahkan dan ganti nama menjadi `annotation\exports\gate3.json`.

### Langkah 7 — A4b

Jalankan sel A4b. Bila ditolak karena label tidak sesuai Tabel 4, perbaiki di Label Studio, ekspor ulang, jalankan lagi.

### Langkah 8 — A5 (hasil akhir)

Jalankan sel A5 dan sel terakhir. Hasil:
- `annotation\out\clean_data_labeled.csv`: seluruh kolom `clean_data.csv` + `label` (1 = buzzer, 0 = non_buzzer) +
  `label_source` (`manual_subset` | `llm_positive_reviewed` | `llm_negative_unreviewed`).
- `annotation\out\annotation_report.md`: ringkasan label, koreksi tinjauan, konfusi LLM vs manual pada subset, semua
  ronde evaluasi, penggunaan token.

---

## Aturan penting selama pengerjaan

- **Jangan mengedit** setelah dibekukan: `pedoman_anotasi.md`, `rules.yaml` (sejak A1), prompt yang sudah dievaluasi,
  dan apa pun di `state\`. Pipeline akan berhenti (invarian I3, I7, I8).
- **Cadangkan** folder `annotation\state\` dan `annotation\label_studio_data\` setelah setiap GATE (salin ke tempat lain).
- `python -m annotation status` (dari folder `code\preprocess`) atau sel terakhir notebook menunjukkan posisi Anda kapan saja.
- Biaya per tahap tercatat dari respons API (sel `biaya()`); nilai sebenarnya baru diketahui setelah run pertama.

## Pemecahan masalah

| Gejala | Penyebab / tindakan |
|---|---|
| `ModuleNotFoundError: openai` saat A2 | jalankan Bagian A1 di terminal `(base)`, lalu restart kernel |
| `BERHENTI: Pedoman belum dibekukan` | isi `guideline.sha256` (Langkah 1) |
| `BERHENTI: I8 ... berubah sejak dibekukan` | pedoman atau `rules.yaml` diubah setelah GATE 1; kembalikan isinya |
| `BERHENTI: Berkas ekspor belum ada` | ekspor dari Label Studio belum dipindah ke `annotation\exports\gate1.json` / `gate3.json` |
| `BERHENTI: ... bukan ekspor JSON Label Studio` | yang diekspor JSON-MIN/CSV; ekspor ulang dengan format **JSON** |
| `BERHENTI: ... anotasi dibatalkan` / `2 anotasi` | ada tugas yang di-Skip atau dianotasi dua kali; perbaiki di Label Studio |
| `BERHENTI: Berkas v1 berubah sejak dievaluasi` | prompt versi itu diedit setelah A2; simpan revisi sebagai versi baru |
| `BERHENTI: ... baris tiruan` | log produksi tercampur mode tiruan; jangan ubah `USE_MOCK`, hubungi pengembang pipeline |
| Label Studio tidak terbuka / port terpakai | tutup Label Studio lain, atau jalankan dengan port lain (`-p 8081` di `start_label_studio.ps1`) |
| Pra-isian label tidak muncul di GATE 3 | aktifkan **Use predictions to prelabel tasks** (GATE 3 langkah 4) |
| Sel notebook tidak menemukan paket `annotation` | buka notebook dari folder `code\preprocess` atau `code\preprocess\annotation` |
