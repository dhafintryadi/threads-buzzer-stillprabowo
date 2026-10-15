# Pipeline Anotasi Human-LLM

Pelabelan akun buzzer: subset manual, evaluasi prompt LLM, anotasi seluruh akun dengan prompt beku, dan tinjauan
manusia. Masuk: `clean_data.csv` dari `preprocess/` (tidak pernah diubah). Pedoman: `pedoman_anotasi.md`.
Keluar: `out/clean_data_labeled.csv` + laporan. Semua tulisan hanya ke `state/` dan `out/`.

```
pip install -r annotation/requirements.txt
python -m annotation status        # dari folder preprocess/: tahap saat ini dan perintah berikutnya
```

**Notebook:** `annotation_runner.ipynb` menjalankan tahap yang sama lewat sel (satu sel per tahap, sel markdown untuk
tiap GATE, tabel ronde, pratinjau prompt, perkiraan biaya). Notebook hanya memanggil paket ini, jadi notebook dan CLI
memakai `state/` yang sama dan bisa dipakai bergantian. Ekspor Label Studio disimpan di `annotation/exports/`.
Panduan langkah demi langkah (instalasi, Label Studio, notebook): `PANDUAN_RUNNING.md`.
**Demo pelabelan** (latihan): `python -m annotation demo` lalu `demo-check` (atau sel D di notebook);
akun di luar subset resmi, tanpa menulis ke `state/` atau membekukan apa pun.

Kode tidak pernah melewati GATE (pekerjaan manusia) secara otomatis.

## Parameter subset dan label akhir (`config.yaml`)

| Config | Nilai | Akibat |
|---|---|---|
| `subset.split_tuning_fraction` | `0.5` | 63 akun -> 31 tuning / 32 validation; per strata tuning = floor(n/2), sisa ganjil ke validation |
| `subset.stratify_split_by_manual_label` | `true` | kedua set memuat akun buzzer |
| `subset.min_validation_positives` | `0` | tidak memblokir; jumlah buzzer + catatan TP minimum + Wilson dicetak. Validation tanpa buzzer tetap **berhenti** (recall tidak terdefinisi) |
| `final_label.manual_subset_overrides` | `true` (wajib) | akun subset memakai label manual dan **dikeluarkan dari tinjauan GATE 3** |
| `guideline.sha256` | dibekukan | hash pedoman; tidak pernah diisi otomatis. A1 mencetak hash saat ini |

## Flag dan default

| Flag | Default | Arti |
|---|---|---|
| `prompt.layout` | `static_system` | bagian beku di pesan system (identik antar-akun, bisa di-*cache*), data akun saja di pesan user \| `chen`: tata letak lama. `prompt_vN.yaml` boleh menimpanya dengan kunci `layout` |
| `prompt.render_format` | `markdown` | `markdown`: bagian ditandai header markdown \| `json`: bagian yang sama sebagai objek JSON. `prompt_vN.yaml` boleh menimpanya dengan kunci `render_format`; lihat bagian Prompt |
| `optimization.max_optimizations` | `3` | tafsiran "tiga kali optimasi" = v1 + 3 revisi (maks 4 evaluasi) |
| `optimization.freeze_on_limit` | `best_validation` | bila batas tercapai tanpa ambang: versi recall validasi tertinggi (seri -> terbaru) \| `last`. Semua ronde dilaporkan |
| `optimization.eval_repeats` | `1` | pengulangan evaluasi A2; recall dilaporkan per pengulangan, aturan berhenti memakai pengulangan 1 |
| `output_schema.ip_when_ku_not_met` | `"null"` | IP boleh kosong bila `ku = tidak` \| `"filled"` |
| `rules.label_policy` | `llm` | label pipeline = label LLM; Tabel 4 hanya diperiksa (`rule_inconsistent`) \| `derived` |
| `rules.ip3_from_columns` | `true` | IP3 untuk pemeriksaan = `threads_topik + balasan_topik >= 2`; selisih dengan IP3 LLM dicatat |
| `rules.manual_rule_check` | `block` | label manusia (GATE 1, GATE 3) harus sesuai Tabel 4: impor berhenti dan mencantumkan akunnya \| `derive`: label diturunkan dari KU/IP, selisih dilaporkan |
| `review.fill_ku_ip` | `true` | peninjau GATE 3 mengisi KU/IP + label \| `false`: hanya label (lalu Tabel 4 tidak bisa diperiksa) |
| `llm.temperature`, `llm.top_p`, `llm.reasoning_effort`, `llm.max_completion_tokens` | `null` | tidak dikirim; `reasoning_effort` dan `max_completion_tokens` diisi setelah uji coba (lihat `reasoning_tokens`); lihat bagian Parameter API |
| `llm.truncation_policy` | `fail` | caption tidak pernah dipotong; akun yang melewati `max_input_tokens` (1000; terpanjang ±318) menghentikan run |
| Bahasa instruksi prompt | Indonesia | isi `prompt_vN.yaml`; kunci JSON dan label `snake_case` |

## Parameter API

`temperature` dan `top_p` bernilai `null` (tidak dikirim). Parameter yang diterima model diverifikasi secara
empiris:

```
python -m annotation probe     # ±10 panggilan pendek tanpa data akun -> state/api_probe.json
```

`probe` mencoba `temperature` 0/1, `top_p` 1/0.5, `reasoning_effort` minimal/low/medium/high, dan structured output,
lalu mencetak mana yang DITERIMA. Isi config hanya dengan nilai yang diterima. Parameter yang benar-benar dikirim pada
setiap panggilan tercatat di `request_params` di `llm_calls.jsonl`.

## Alur

| Tahap | Perintah | Hasil |
|---|---|---|
| A0 validasi kontrak + token | `a0` | 9 kolom dicek fail-fast; statistik |
| Bekukan pedoman | isi `guideline.sha256` | I8 aktif |
| A1 subset acak ±10% | `a1` | 63 akun (ukuran aktual dicetak). Membekukan hash `rules.yaml` di `state/frozen_inputs.json` |
| **GATE 1** label manual | Label Studio (`label_studio_config_gate1.xml`: KU, IP1-IP4, label) atau CSV | ekspor JSON / CSV |
| A1b impor + bagi | `a1b --labels <berkas>` | `state/manual_subset.csv`; Tabel 4 dicek (`manual_rule_check`); validation tanpa buzzer -> berhenti |
| **GATE 2** tulis prompt | `prompts/prompt_vN.yaml` (+ `fewshot_vN.json`) | |
| A2 evaluasi prompt | `a2 --version vN` | `state/eval_rounds.csv` (per ronde x pengulangan x set); bila lolos/batas: `frozen_prompt.json` |
| A2b kandidat few-shot | `a2b` | akun tuning dengan selisih KU/IP/label LLM vs manual (`diff_fields`) |
| A3 label seluruh akun | `a3` | seluruh N akun termasuk subset; `state/llm_calls.jsonl` |
| A4 ekspor tinjauan | `a4` | akun buzzer-LLM **di luar subset**, acak; `label_studio_config_gate3.xml` |
| **GATE 3** tinjau | Label Studio; pra-anotasi = label LLM; KU/IP LLM tersimpan tetapi tersembunyi | ekspor JSON |
| A4b impor tinjauan | `a4b --export <berkas>` | `state/review_labels.csv`; akun subset ditolak (I9); Tabel 4 dicek |
| A5 label akhir + laporan | `a5` | `out/clean_data_labeled.csv`, `out/annotation_report.{json,md}` |

Loop optimasi: recall validasi (kelas buzzer) >= 0.85 -> bekukan; belum dan revisi < 3 -> `a2b`, versi baru, `a2`;
batas tercapai -> bekukan sesuai `freeze_on_limit`.

**Ambang pada validation kecil.** Untuk n buzzer validation, recall >= 0.85 butuh TP >= ceil(0.85 n): n <= 6 -> semua
harus tertangkap; n = 7-13 -> boleh terlewat satu; n = 14-19 -> boleh terlewat dua. A1b, A2, dan laporan mencetak
angka ini beserta CI Wilson 95%.

**Label Studio:** `.\annotation\start_label_studio.ps1` (http://localhost:8080). Settings -> Labeling Interface -> Code:
tempel berkas `label_studio_config_gate*.xml`; impor tugas; Export -> **JSON** (bukan JSON-MIN). Satu anotasi per tugas.
**GPT-5 Mini:** set `OPENAI_API_KEY` di lingkungan (tidak pernah ditulis ke config/log).

**Mode tiruan:** `set ANNOTATION_MOCK=1` menjalankan alur dengan model tiruan dan menulis **hanya** ke `state_mock/` dan
`out_mock/`. Mode produksi (A2 saat membekukan, A3, A5) menolak berjalan bila `state/llm_calls.jsonl` memuat baris
`model_snapshot = mock`.

## Prompt

`prompts/prompt_vN.yaml`: `system`, `instruction`, `criteria` (`ku`, `ip1`..`ip4`), `decision_rule`, `response_format`,
`options`, `fewshot_ref`.

Tata letak `static_system` (default):

```
SYSTEM: <system>                                  USER: # Data akun
        # Instruksi        <instruction>                follower_count: ...
        # Kriteria         - ku: ... - ip1..ip4          ... (7 kolom) ...
        # Aturan keputusan                               caption_text: ...
        # Contoh           (hanya bila ada few-shot)
        # Respons                                        ANSWER:
        # Opsi
```

Seluruh pesan system identik byte-per-byte antar-akun dalam satu versi (tanpa cap waktu, id, atau nilai lain yang berubah),
sehingga prefiks bisa di-*cache* oleh API. Skema keluaran dan parameter permintaan juga konstan; mengubahnya di tengah
evaluasi mengosongkan cache. *Cache* hanya berlaku untuk prefiks ≥ 1.024 token dan tidak dijamin, jadi ukur lewat
`cached_tokens` (pratinjau di notebook mencetak perkiraan token bagian beku). Tata letak `chen` (lama): data akun di akhir
pesan system, instruksi dan kriteria di pesan user.

- **Format render (`render_format`):** `markdown` (default) seperti diagram di atas. `json` mengirim bagian yang sama
  sebagai objek JSON: pesan `system` = `{"peran", "data_akun"}` (angka tetap angka), pesan `user` =
  `{"instruksi", "kriteria", "aturan_keputusan", "contoh"?, "format_respons", "opsi"}` lalu `ANSWER:` di luar JSON;
  contoh few-shot menjadi daftar `{data_akun, jawaban}`. Format ikut menentukan `prompt_sha256`, jadi varian JSON harus
  disimpan sebagai **versi baru** (mis. `prompt_v3.yaml` dengan `render_format: json`). Menulis `render_format` di berkas
  versi membuat format versi itu tetap walau default di config diubah, sehingga versi markdown dan JSON bisa dibandingkan
  berdampingan dan versi mana pun yang dibekukan tetap bisa dipakai A3. Kolom `render_format` dicatat di `eval_rounds.csv`
  dan `llm_calls.jsonl`. JSON memakai sekitar 20% lebih banyak token daripada markdown (kerangka v1: 412 vs 340).
- **`decision_rule`:** tulis `{{rules}}` agar teks aturan dihasilkan dari `rules.yaml` (selalu konsisten dengan Tabel 4).
  Teks tulisan tangan tetap boleh, tetapi A2 mencetak peringatan beserta teks aturan dari `rules.yaml` untuk dibandingkan.
- **Few-shot:** `fewshot_vN.json` = `[{"user_id": ...}]`, hanya akun tuning; dirender sebagai data akun + jawaban JSON dari
  label manualnya.
- **`prompt_sha256`** tidak bergantung pada akun: pesan system utuh + template pesan user, dengan placeholder data akun (`follower_count: {follower_count}`,
  ..., `caption_text: {caption_text}`) ditambah blok few-shot dan teks aturan yang sudah dirender, lalu SHA-256 atas JSON
  kedua pesan itu. Dua akun berbeda dengan prompt yang sama selalu memiliki hash yang sama. Perubahan apa pun pada bagian
  prompt atau few-shot mengubah hash, jadi revisi harus disimpan sebagai versi baru.

## Keluaran LLM dan parsing

```json
{"alasan": {"ku": "terpenuhi|sebagian|tidak", "ip1": "ya|tidak", "ip2": "...", "ip3": "...", "ip4": "..."},
 "label": "buzzer|non_buzzer"}
```

Structured outputs (skema ketat, enum). Parser: ekstrak JSON -> perbaiki bila rusak (`json-repair`, `repair_applied`)
-> validasi enum -> ulang hingga `max_parse_retries` -> `parse_error`. "ragu"/"tidak dapat dinilai" ditolak. Tanpa label
default (I5). Tabel 4 di `rules.yaml`, dibaca `derive_label`.

## Kamus kolom

- **`state/manual_subset.csv`**: `user_id, manual_ku, manual_ip1..manual_ip4, manual_label, split, annotator_id, labeled_at`
- **`state/llm_calls.jsonl`** (append-only; prefiks diverifikasi lewat `llm_calls.checkpoint.json`): `call_id, run_id,
  stage (eval|full), repeat, prompt_version, render_format, layout, prompt_sha256, user_id, model_requested, model_snapshot, request_params,
  messages, raw_response, parsed_ku, parsed_ip, parsed_label, derived_label, rule_inconsistent, ip3_code, ip3_mismatch,
  repair_applied, prompt_tokens, cached_tokens, completion_tokens, reasoning_tokens, finish_reason, truncated, status (ok|parse_error|api_error), error, attempt, timestamp_utc`.
  Kunci resume: `(prompt_sha256, stage, repeat, user_id)`.
- **`state/eval_rounds.csv`**: `round, repeat, prompt_version, prompt_sha256, render_format, layout, set, n, positives, tp, fp, fn, tn, recall,
  recall_ci_low, recall_ci_high, precision, f1, rule_inconsistent, ip3_mismatch, label_policy, model_snapshot, evaluated_at`
- **`state/frozen_inputs.json`**: hash pedoman dan `rules.yaml` saat A1. **`state/frozen_prompt.json`**: versi + hash prompt beku.
- **`state/review_labels.csv`**: `user_id, review_ku, review_ip1..review_ip4, review_label, reviewer_id, reviewed_at,
  llm_label, review_changed_label` (hanya akun non-subset)
- **`out/clean_data_labeled.csv`**: semua kolom `clean_data.csv` + `label` (1/0) + `label_source` (`manual_subset` |
  `llm_positive_reviewed` | `llm_negative_unreviewed`, tepat satu per akun) + `final_prompt_version` + `review_changed_label`
  (kosong untuk subset dan akun yang tidak ditinjau)
- **`out/annotation_report.{json,md}`**: jumlah per `label_source`, koreksi tinjauan, tabel konfusi label LLM vs manual pada
  subset per set (tuning = in-sample), catatan ambang validation, semua ronde, nilai flag, dan penggunaan token per
  tahap (panggilan, total token, % `cached_tokens`, rata-rata `reasoning_tokens`; bidang yang tidak ada di respons API
  dicatat kosong)
- **`out/run_manifest.json`**: entri append-only per tahap: hash input/output, config, pedoman, `rules.yaml`, versi library

## Invarian (dicek di kode)

I1 tuning dan validation saling lepas dan menutup subset. I2 tidak ada akun validation (ID/teks) di prompt atau few-shot.
I3 anotasi penuh hanya dengan prompt beku (hash render). I4 setiap akun buzzer-LLM **non-subset** tepat satu tinjauan
valid. I5 setiap akun tepat satu isian LLM `ok`. I6 keluaran N baris, `user_id` 1:1, `label` 0/1, tepat satu
`label_source`. I7 `llm_calls.jsonl` hanya bertambah. I8 hash pedoman = `guideline.sha256` dan `rules.yaml` tidak berubah
setelah GATE 1. I9 tidak ada akun subset di `review_tasks.json` maupun `review_labels.csv`.

## Catatan

- Notebook yang berlaku: `annotation_runner.ipynb`.
- Keluaran `out/clean_data_labeled.csv` dibaca tahap 06 `text-preprocess` di `preprocess/`.
- `demo/` (tugas latihan berisi data akun) dan `prompts/fewshot_*.json` (berisi user_id) tidak dilacak git.
