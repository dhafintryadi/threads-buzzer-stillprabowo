"""ablasi_ringkasan.md (tabel angka saja, TANPA interpretasi) dan manifest.json."""

from __future__ import annotations

import importlib.metadata as md
import platform

import numpy as np
import pandas as pd


def _fmt(v) -> str:
    if v is None or v is pd.NA or (isinstance(v, (float, np.floating)) and np.isnan(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "ya" if v else "-"
    if isinstance(v, (float, np.floating)):
        return f"{v:.4f}"
    return str(v)


def md_table(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def ringkasan_md(t9: pd.DataFrame, baseline: pd.DataFrame, agg: pd.DataFrame, dlt: pd.DataFrame, rank: pd.DataFrame,
                 perk: pd.DataFrame, pola_summary: pd.DataFrame, run_id: str) -> str:
    base_rows = baseline.assign(konfigurasi="baseline_mayoritas", tp=pd.NA, fp=pd.NA, fn=pd.NA, tn=pd.NA)[
        ["split", "konfigurasi", "n_test", "support_buzzer", "support_non_buzzer", "tp", "fp", "fn", "tn", "makro_f1",
         "akurasi", "tak_terdefinisi"]]
    nine = pd.concat([t9, base_rows], ignore_index=True)
    pola = pola_summary.pivot_table(index=["split", "pola"], columns="y_true", values="jumlah_akun", aggfunc="sum",
                                    sort=False).reset_index()
    pola.columns = ["split", "pola", *[f"y_true={c}" for c in pola.columns[2:]]]
    L = [f"# Ringkasan angka analisis ablasi -- run `{run_id}`", "",
         "Semua angka dari data uji. Kelas positif = buzzer. Simpangan baku = sampel (ddof=1). "
         "Dokumen ini hanya memuat angka; interpretasi dikerjakan peneliti.", "",
         "## Tabel 9 sel (+ baseline mayoritas per split)", "", md_table(nine), "",
         "## Agregat per konfigurasi (lintas 3 split)", "", md_table(agg), "",
         "## Delta makro-F1", "", md_table(dlt), "",
         "## Peringkat makro-F1 per split", "", md_table(rank), "",
         "## Per kelas", "", md_table(perk.drop(columns=[c for c in perk.columns if c.endswith("_tak_terdefinisi")])), "",
         "Kolom `*_tak_terdefinisi` (pembagi nol) ada di `ablasi_perkelas.csv`.", "",
         "## Baseline mayoritas", "", md_table(baseline), "",
         "## Pola benar/salah per akun (jumlah akun; A = akun, T = teks, G = gabungan; 1 = benar)", "",
         md_table(pola), ""]
    return "\n".join(L)


def versions() -> dict:
    out = {"python": platform.python_version()}
    for lib in ("pandas", "numpy", "matplotlib", "scikit-learn"):
        try:
            out[lib] = md.version(lib)
        except md.PackageNotFoundError:
            out[lib] = None
    return out
