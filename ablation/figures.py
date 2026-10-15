"""Gambar ablasi: >= 300 dpi, label Indonesia, konfigurasi tidak dibedakan dengan warna saja."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .config import Settings  # noqa: E402

HATCHES = ["//", "..", "xx"]
MARKERS = ["o", "s", "^"]
LABEL_CONF = {"akun": "Akun", "teks": "Teks", "gabungan": "Gabungan"}


def _save(fig, path: Path, s: Settings) -> None:
    fig.savefig(path, dpi=s.fig_dpi, metadata={"Software": None}, bbox_inches="tight")
    plt.close(fig)


def fig_makro_f1(agregat: pd.DataFrame, table: pd.DataFrame, s: Settings, path: Path) -> None:
    confs = list(s.configs)
    sub = agregat[agregat["metrik"] == "makro_f1"].set_index("konfigurasi")
    means = [float(sub.loc[c, "mean"]) for c in confs]
    stds = [float(sub.loc[c, "std_ddof1"]) for c in confs]
    x = np.arange(len(confs))
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for i, c in enumerate(confs):
        ax.bar(x[i], means[i], width=0.5, facecolor="white", edgecolor="black", hatch=HATCHES[i % len(HATCHES)],
               yerr=stds[i], capsize=6, error_kw={"elinewidth": 1.2, "ecolor": "black"})
        ax.text(x[i], means[i] + stds[i] + 0.02, f"{means[i]:.3f}", ha="center", va="bottom", fontsize=9)
    offsets = 0.33 + 0.07 * np.arange(len(s.splits))
    for j, sl in enumerate(s.splits):
        vals = [float(table[(table["split"] == sl) & (table["konfigurasi"] == c)]["makro_f1"].iloc[0]) for c in confs]
        ax.scatter(x + offsets[j], vals, marker=MARKERS[j % len(MARKERS)], s=36, facecolor="black",
                   edgecolor="black", zorder=3, label=f"Split {sl}")
    base = agregat[(agregat["konfigurasi"] == "baseline_mayoritas") & (agregat["metrik"] == "makro_f1")]
    if len(base):
        ax.axhline(float(base["mean"].iloc[0]), color="black", linestyle="--", linewidth=1,
                   label="Baseline mayoritas (rerata)")
    ax.set_xticks(x + 0.1, [LABEL_CONF.get(c, c) for c in confs])
    ax.set_xlabel("Konfigurasi fitur")
    ax.set_ylabel("Makro-F1 (data uji)")
    ax.set_ylim(0, 1)
    ax.set_title("Makro-F1 per konfigurasi fitur\n(batang = rerata 3 split, garis galat = simpangan baku sampel, titik di samping batang = per split)",
                 fontsize=10)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    _save(fig, path, s)


def fig_perkelas_buzzer(table: pd.DataFrame, s: Settings, path: Path) -> None:
    metrics = [("presisi_buzzer", "Presisi"), ("recall_buzzer", "Recall"), ("f1_buzzer", "F1")]
    rows = [(sl, c) for sl in s.splits for c in s.configs]
    data = np.array([[float(table[(table["split"] == sl) & (table["konfigurasi"] == c)][m].iloc[0]) for m, _ in metrics]
                     for sl, c in rows])
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    im = ax.imshow(data, cmap="Greys", vmin=0, vmax=1, aspect="auto")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, f"{data[i, j]:.3f}", ha="center", va="center", fontsize=9,
                    color="white" if data[i, j] > 0.6 else "black")
    ax.set_xticks(range(len(metrics)), [lab for _, lab in metrics])
    ax.set_yticks(range(len(rows)), [f"{sl} - {LABEL_CONF.get(c, c)}" for sl, c in rows])
    for k in range(1, len(s.splits)):
        ax.axhline(k * len(s.configs) - 0.5, color="black", linewidth=1.5)
    ax.set_xlabel("Metrik kelas buzzer (data uji)")
    ax.set_ylabel("Split - konfigurasi fitur")
    ax.set_title("Presisi, recall, dan F1 kelas buzzer per sel", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Nilai")
    _save(fig, path, s)
