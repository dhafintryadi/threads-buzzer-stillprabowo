**PEDOMAN ANOTASI AKUN BUZZER DAN NON-BUZZER PADA TAGAR #STILLPRABOWO DI PLATFORM THREADS**

Pedoman ini disusun untuk menjaga konsistensi pemberian label _buzzer_ dan non-_buzzer_ pada dataset clean_data.csv. Penyusunan mengikuti ketentuan bahwa pedoman anotasi memuat deskripsi tugas, deskripsi setiap label, dan contoh penerapan (Stollenwerk dkk., 2023).

Pedoman digunakan pada seluruh tahap anotasi dalam Subbab 3.1.4, yaitu pelabelan manual subset awal (±10%) sekitar 63 akun, penyusunan dan optimasi _prompt_ oleh LLM, serta tinjauan manual terhadap akun yang dilabeli _buzzer_ oleh LLM. Definisi label, kriteria pengambilan keputusan, dan format keluaran pada pedoman ini menjadi dasar penyusunan _prompt_. Unit anotasi adalah satu akun yang direpresentasikan oleh satu baris dalam data.

# A. Definisi Operasional

## A.1. Narasi Kampanye

Narasi kampanye adalah pesan yang menyatakan dukungan kepada Presiden Prabowo dan pemerintah dalam tagar #StillPrabowo, serta pesan yang mendiskreditkan kritik dan tuntutan pihak oposisi dalam konteks tersebut.

## A.2. Kelas _Buzzer_

_Buzzer_ adalah akun yang terindikasi mengamplifikasi narasi kampanye #StillPrabowo secara terkoordinasi. Rumusan ini sejalan dengan peran _buzzer_ sebagai pihak yang memperkuat penyebaran pesan dan menggiring opini (Sugiono, 2020), serta dengan karakteristik akun _buzzer_ berupa tingkat aktivitas tinggi dan pola konten yang redundan untuk memperluas narasi tertentu ketimbang menyampaikan opini pribadi (Rizki dkk., 2024).

## A.3. Kelas Non-_Buzzer_

Non-_buzzer_ adalah seluruh akun yang tidak memenuhi kriteria pada Bagian C, termasuk:

1. pendukung organik, yaitu akun yang menyampaikan dukungan melalui opini personal yang bervariasi;
2. pengkritik, termasuk akun yang menggunakan bahasa kasar atau stigmatisasi balik;
3. akun yang bersikap sarkastik terhadap kampanye;
4. akun kontra-mobilisasi, misalnya yang mengajak pemblokiran atau pelaporan massal akun _buzzer_.

Sikap politik akun bukan penentu kelas, karena yang dinilai adalah pola amplifikasi narasi kampanye, bukan apakah akun mendukung atau mengkritik.

# B. Data yang Dinilai

Penilaian dilakukan terhadap kolom pada Tabel 1. Isi teks akun merupakan bukti utama, sedangkan kolom numerik berfungsi sebagai konteks.

**Tabel 1.** Kolom dataset terintegrasi dan fungsi dalam penilaian

| **Kolom**        | **Keterangan**                                                                 | **Fungsi**                          |
| ---------------- | ------------------------------------------------------------------------------ | ----------------------------------- |
| "user_id"        | ID unik akun                                                                   | _Unique identifier_                 |
| "caption_text"   | Gabungan teks unggahan dan balasan akun                                        | Bukti utama KU, IP1, IP2, dan IP4   |
| "follower_count" | Jumlah pengikut saat _scraping_                                                | Konteks tambahan                    |
| "threads_count"  | Jumlah unggahan orisinal dalam rentang observasi tanpa syarat relevansi topik  | Konteks tambahan                    |
| "replies_count"  | Jumlah balasan dalam rentang observasi                                         | Konteks tambahan                    |
| "reposts_count"  | Jumlah unggahan ulang dalam rentang observasi                                  | Konteks tambahan                    |
| "threads_topik"  | Unggahan orisinal yang memenuhi relevansi topik                                | Dasar IP3                           |
| "balasan_topik"  | Balasan yang memenuhi kriteria relevansi topik                                 | Dasar IP3                           |

**Tabel 2.** Ringkasan distribusi kolom numerik

| **Kolom**        | **Med** | **Q3** | **Maks** | **Akun bernilai 0** |
| ---------------- | ------- | ------ | -------- | ------------------- |
| "follower_count" | 51,5    | 148    | 89.000   | 42                  |
| "threads_count"  | 1       | 7      | 600      | 255                 |
| "replies_count"  | 59      | 142    | 817      | 40                  |
| "reposts_count"  | 1       | 7      | 798      | 304                 |
| "threads_topik"  | 0       | 0      | 15       | 538                 |
| "balasan_topik"  | 0       | 0      | 12       | 579                 |
| "items_scanned"  | 77      | 175,8  | 1.430    | 0                   |

# C. Kriteria dan Aturan Keputusan

## C.1. Kriteria Utama

Kriteria Utama (KU) dalam pelabelan adalah teks unggahan akun yang menyampaikan atau menguatkan narasi kampanye dengan sikap yang dapat dibaca jelas dari teks itu sendiri. KU dinilai:

1. _terpenuhi_, apabila pesan pro-kampanye terbaca jelas atau hanya berupa tagar kampanye;
2. _terpenuhi sebagian_, apabila teks berupa ajakan kampanye tanpa isi pesan (selain tagar kampanye), atau pesan pro-kampanye hanya muncul pada bagian kecil teks; dan
3. _tidak terpenuhi_, apabila teks bersifat kritis, sarkastik terhadap kampanye, netral, tidak relevan, atau maknanya tidak dapat dibaca dari teks.

## C.2. Indikator Pendukung

**Tabel 3.** Indikator pendukung (IP)

| **Kode** | **Indikator**                 | **Deskripsi dan sumber bukti**                                                                                    | **Rujukan**                  |
| -------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| IP1      | Keseragaman isi               | Kalimat, slogan, atau ajakan yang sama atau nyaris sama muncul berulang dalam teks akun (caption_text).          | Rizki dkk. (2024)            |
| IP2      | Minimnya opini personal       | Isi berupa slogan atau potongan narasi tanpa pengalaman, argumen, atau pandangan pribadi (caption_text).         | Rizki dkk. (2024)            |
| IP3      | Aktivitas bertopik berulang   | Akun memiliki lebih dari satu unggahan atau balasan bertopik, (threads_topik/balasan_topik) berjumlah ≥2         | Rizki dkk. (2024)            |
| IP4      | Serangan atau label stigmatis | Serangan personal atau pelabelan stigmatis terhadap pengkritik (caption_text).                                    | Amnesty International (2026) |

IP1, IP2, dan IP4 disebut indikator berbasis teks karena dinilai dari "caption_text". IP3 bersumber dari kolom numerik dan tidak dapat menjadi dasar label tanpa dukungan isi teks.

## C.3. Aturan Keputusan

Label ditetapkan berdasarkan Tabel 4. Aturan yang sama digunakan pada seluruh tahap anotasi. Setiap indikator yang dinyatakan terpenuhi harus dapat dilihat di "caption_text" atau nilai kolom yang relevan.

**Tabel 4.** Aturan penetapan label

| **Penilaian KU**                  | **Indikator pendukung**              | **Label**    |
| --------------------------------- | ------------------------------------ | ------------ |
| Terpenuhi                         | Minimal 1 indikator berbasis teks    | _Buzzer_     |
| Terpenuhi sebagian                | Minimal 2 indikator                  | _Buzzer_     |
| Terpenuhi atau terpenuhi sebagian | Selain kombinasi pada dua baris di atas | Non-_buzzer_ |
| Tidak terpenuhi                   | Apa pun                              | Non-_buzzer_ |

# D. Kasus Khusus

**Tabel 5.** Pedoman untuk kasus khusus

| **No.** | **Kasus**                                                          | **Label**         | **Catatan**                                                                                   |
| ------- | ------------------------------------------------------------------ | ----------------- | --------------------------------------------------------------------------------------------- |
| 1       | Pendukung organik: opini personal, bervariasi                      | Non-_buzzer_      | Dukungan bukan bukti _buzzer_. Umumnya tidak memenuhi IP1, IP2, atau IP4.                     |
| 2       | Pengkritik, termasuk yang berbahasa kasar atau bernada stigmatis   | Non-_buzzer_      | KU tidak terpenuhi karena akun tidak menguatkan narasi kampanye.                              |
| 3       | Sarkasme                                                           | Sesuai makna asli | Sarkasme terhadap kampanye: KU tidak terpenuhi. Jika sikap tidak terbaca, KU tidak terpenuhi. |
| 4       | Kontra-mobilisasi (ajakan blokir atau _report_ akun secara massal) | Non-_buzzer_      | KU tidak terpenuhi.                                                                           |
| 5       | Balasan singkat yang bergantung pada unggahan induk                | Non-_buzzer_      | Sikap tidak terbaca dari teks sehingga KU tidak terpenuhi.                                    |
| 6       | Bahasa campuran, slang, atau emoji                                 | Sesuai makna asli | Penilaian berdasarkan makna, bukan tingkat kekasaran bahasa.                                  |

# E. Format Keluaran Anotasi

Setiap akun dicatat dengan isian berikut: (a) penilaian KU; (b) status IP1 sampai IP4; dan (c) label akhir, sesuai aturan pada Tabel 4.

# F. Contoh Penerapan

Contoh pada Tabel 6 bersifat ilustratif dan disusun peneliti, bukan kutipan data penelitian.

**Tabel 6.** Contoh ilustratif penerapan pedoman

| **No.** | **Cuplikan**                                                                                                                                                                   | **Penilaian**               | **Label**    |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------- | ------------ |
| A       | Isi hampir serupa, misalnya "Dukung terus Pak Prabowo, jangan mau diadu domba asing! #StillPrabowo", tanpa opini tambahan. Salah satunya nyebut yang kritik itu "antek asing". | KU terpenuhi; IP1, IP2, IP4 | _Buzzer_     |
| B       | "Menurut aku sih respons pemerintah udah lumayan bagus, soalnya …" lengkap dengan alasan dan pengalaman sendiri.                                                               | KU terpenuhi; tanpa IP teks | Non-_buzzer_ |
| C       | "Emang paling oke dah #StillPrabowo, rakyat adem ayem, semuanya aman terkendali 🙃"                                                                                            | KU tidak terpenuhi          | Non-_buzzer_ |
| D       | "Langsung report sama blokir akun-akun buzzer #StillPrabowo."                                                                                                                  | KU tidak terpenuhi          | Non-_buzzer_ |
| E       | Teks hanya "#StillPrabowo"                                                                                                                                                     | KU terpenuhi; IP2           | _Buzzer_     |
| F       | "Setuju sama komen di atas."                                                                                                                                                   | KU tidak terpenuhi          | Non-_buzzer_ |
