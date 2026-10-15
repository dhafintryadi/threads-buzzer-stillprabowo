# Menjalankan Label Studio 1.23.0 untuk pipeline anotasi.
#  - venv terpisah : ..\..\.venv-label-studio  (di folder code\; tidak menyentuh dependensi preprocess/)
#  - data          : .\label_studio_data     (database SQLite + upload, ikut proyek)
#  - hanya localhost (127.0.0.1) -- tidak terlihat dari jaringan
# Buka http://localhost:8080 ; hentikan dengan Ctrl+C.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # folder code\
& "$root\.venv-label-studio\Scripts\label-studio.exe" start `
    --data-dir "$PSScriptRoot\label_studio_data" `
    --internal-host localhost `
    -p 8080
