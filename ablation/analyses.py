"""Analisis A (agregat), B (per kelas), C (error per akun)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import FEATURES, Settings
from .inputs import AblationError
from .metrics import PER_CLASS, UNDEF_METRICS, majority_baseline, metrics_from_counts, confusion, sklearn_macro_f1, std_sample

AGG_METRICS = ["makro_f1", "akurasi", "presisi_buzzer", "recall_buzzer", "f1_buzzer"]
BUZZER_METRICS = ["presisi_buzzer", "recall_buzzer", "f1_buzzer"]
PATTERNS = [f"A{a}T{t}G{g}" for a, t, g in itertools.product((1, 0), repeat=3)]
FLAG_COLS = [f"{m}_tak_terdefinisi" for m in UNDEF_METRICS]


def cell_table(cells: dict, s: Settings) -> pd.DataFrame:
    rows = []
    for (sl, cl), df in cells.items():
        m = metrics_from_counts(**confusion(df["y_true"], df["y_pred"], s.positive_label))
        sk = sklearn_macro_f1(df["y_true"], df["y_pred"])
        if abs(sk - m["makro_f1"]) > s.crosscheck_tol:
            raise AblationError(f"{sl} x {cl}: makro-F1 sendiri {m['makro_f1']} != sklearn {sk}")
        rows.append({"split": sl, "konfigurasi": cl, **m, "makro_f1_sklearn": sk})
    return pd.DataFrame(rows)


def crosscheck_model_metrics(table: pd.DataFrame, model_metrics: pd.DataFrame | None, s: Settings) -> dict:
    """Bandingkan dengan metrik keluaran modeling bila tersedia (toleransi 1e-9)."""
    if model_metrics is None:
        return {"status": "tidak_tersedia"}
    max_diff, checked = 0.0, 0
    for _, r in table.iterrows():
        mm = model_metrics[(model_metrics[s.col_split] == s.splits[r["split"]])
                           & (model_metrics[s.col_config] == s.configs[r["konfigurasi"]])]
        if len(mm) != 1:
            raise AblationError(f"{r['split']} x {r['konfigurasi']}: metrik modeling tidak tunggal ({len(mm)} baris)")
        mm = mm.iloc[0]
        for ours, theirs in s.model_metric_columns.items():
            if theirs not in mm.index:
                continue
            d = abs(float(r[ours]) - float(mm[theirs]))
            max_diff, checked = max(max_diff, d), checked + 1
            if d > s.crosscheck_tol:
                raise AblationError(f"{r['split']} x {r['konfigurasi']}: {ours} = {r[ours]} != modeling {theirs} = {mm[theirs]}")
    return {"status": "cocok", "n_nilai_dibandingkan": checked, "selisih_maks": max_diff}


def k_metadata(model_metrics: pd.DataFrame | None, s: Settings) -> dict:
    if model_metrics is None or s.model_k_column not in model_metrics:
        return {}
    out = {}
    for sl, sv in s.splits.items():
        for cl, cv in s.configs.items():
            mm = model_metrics[(model_metrics[s.col_split] == sv) & (model_metrics[s.col_config] == cv)]
            if len(mm) == 1:
                out[f"{sl} x {cl}"] = int(mm[s.model_k_column].iloc[0])
    return out


def tabel_9sel(table: pd.DataFrame) -> pd.DataFrame:
    cols = ["split", "konfigurasi", "n_test", "support_buzzer", "support_non_buzzer", "tp", "fp", "fn", "tn",
            "makro_f1", "akurasi", "tak_terdefinisi"]
    return table[cols].copy()


def baseline_table(cells: dict, s: Settings, model_baselines: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    rows, checked, max_diff = [], 0, 0.0
    ref_conf = next(iter(s.configs))
    for sl, sv in s.splits.items():
        y = cells[(sl, ref_conf)]["y_true"]
        b = majority_baseline(int((y == 1).sum()), int((y == 0).sum()))
        for k in ("akurasi", "makro_f1"):
            if abs(b[k] - b[f"{k}_rumus"]) > s.crosscheck_tol:
                raise AblationError(f"baseline {sl}: {k} hitungan {b[k]} != rumus {b[f'{k}_rumus']}")
        if model_baselines is not None:
            mb = model_baselines[model_baselines[s.col_split] == sv]
            if len(mb) != 1:
                raise AblationError(f"baseline {sl}: baris baseline modeling tidak tunggal ({len(mb)})")
            for ours, theirs in (("akurasi", "accuracy"), ("makro_f1", "f1_macro"), ("f1_buzzer", "f1")):
                if theirs in mb:
                    d = abs(b[ours] - float(mb[theirs].iloc[0]))
                    max_diff, checked = max(max_diff, d), checked + 1
                    if d > s.crosscheck_tol:
                        raise AblationError(f"baseline {sl}: {ours} {b[ours]} != modeling {theirs} {mb[theirs].iloc[0]}")
        rows.append({"split": sl, "n_test": b["n_test"], "support_buzzer": b["support_buzzer"],
                     "support_non_buzzer": b["support_non_buzzer"], "kelas_mayoritas": b["kelas_mayoritas"],
                     "p_mayoritas": b["p"], "akurasi": b["akurasi"], "makro_f1": b["makro_f1"],
                     "f1_buzzer": b["f1_buzzer"], "tak_terdefinisi": b["tak_terdefinisi"]})
    check = {"status": "cocok", "n_nilai_dibandingkan": checked, "selisih_maks": max_diff} if model_baselines is not None \
        else {"status": "tidak_tersedia"}
    return pd.DataFrame(rows), check


def _values(table: pd.DataFrame, conf: str, metric: str, s: Settings) -> list[float]:
    sub = table[table["konfigurasi"] == conf].set_index("split")
    return [float(sub.loc[sl, metric]) for sl in s.splits]


def _summary(name_cols: dict, vals: list[float], s: Settings) -> dict:
    row = dict(name_cols)
    row.update({"mean": float(np.mean(vals)), "std_ddof1": std_sample(vals, s.std_ddof),
                "min": float(np.min(vals)), "maks": float(np.max(vals))})
    row.update({f"nilai_{s.split_key(sl)}": v for sl, v in zip(s.splits, vals)})
    return row


def agregat(table: pd.DataFrame, baseline: pd.DataFrame, s: Settings) -> pd.DataFrame:
    rows = [_summary({"konfigurasi": c, "metrik": m}, _values(table, c, m, s), s) for c in s.configs for m in AGG_METRICS]
    b = baseline.set_index("split")
    for m in ("makro_f1", "akurasi"):
        rows.append(_summary({"konfigurasi": "baseline_mayoritas", "metrik": m},
                             [float(b.loc[sl, m]) for sl in s.splits], s))
    return pd.DataFrame(rows)


def delta(table: pd.DataFrame, s: Settings) -> pd.DataFrame:
    if set(s.configs) != {"akun", "teks", "gabungan"} or s.reference_config != "gabungan":
        raise AblationError("Delta didefinisikan untuk konfigurasi akun/teks/gabungan dengan referensi gabungan")
    f = {c: np.array(_values(table, c, "makro_f1", s)) for c in s.configs}
    defs = [("kontribusi_teks", "makro_f1(gabungan) - makro_f1(akun)", f["gabungan"] - f["akun"]),
            ("kontribusi_akun", "makro_f1(gabungan) - makro_f1(teks)", f["gabungan"] - f["teks"]),
            ("akun_vs_teks", "makro_f1(akun) - makro_f1(teks)", f["akun"] - f["teks"])]
    rows = []
    for name, definition, v in defs:
        r = {"delta": name, "definisi": definition}
        r.update({f"nilai_{s.split_key(sl)}": float(x) for sl, x in zip(s.splits, v)})
        r.update({"mean": float(np.mean(v)), "std_ddof1": std_sample(v, s.std_ddof)})
        rows.append(r)
    return pd.DataFrame(rows)


def peringkat(table: pd.DataFrame, s: Settings) -> pd.DataFrame:
    rows = []
    for sl in s.splits:
        sub = table[table["split"] == sl]
        scores = dict(zip(sub["konfigurasi"], sub["makro_f1"].astype(float)))
        for c in s.configs:
            better = sum(1 for o, v in scores.items() if o != c and v - scores[c] >= s.tie_tol)
            tied = sorted(o for o, v in scores.items() if o != c and abs(v - scores[c]) < s.tie_tol)
            rows.append({"split": sl, "konfigurasi": c, "makro_f1": scores[c], "peringkat": better + 1,
                         "seri": bool(tied), "seri_dengan": ";".join(tied)})
    out = pd.DataFrame(rows)
    champs = out[out["peringkat"] == 1].groupby("konfigurasi").size()
    out["jumlah_juara_konfigurasi"] = out["konfigurasi"].map(lambda c: int(champs.get(c, 0)))
    order = {**{sl: i for i, sl in enumerate(s.splits)}, **{c: i for i, c in enumerate(s.configs)}}
    return out.sort_values(["split", "peringkat", "konfigurasi"],
                           key=lambda col: col if col.name == "peringkat" else col.map(order), kind="stable"
                           ).reset_index(drop=True)


def perkelas(table: pd.DataFrame, s: Settings) -> pd.DataFrame:
    cols = ["split", "konfigurasi", "tp", "fp", "fn", "tn", *PER_CLASS, "spesifisitas",
            *[f"{m}_tak_terdefinisi" for m in PER_CLASS + ["spesifisitas"]]]
    cells = table[cols].copy()
    cells.insert(0, "baris", "sel")
    agg = []
    for c in s.configs:
        for stat in ("agregat_mean", "agregat_std_ddof1"):
            r = {"baris": stat, "split": "", "konfigurasi": c}
            for m in BUZZER_METRICS:
                v = _values(table, c, m, s)
                r[m] = float(np.mean(v)) if stat == "agregat_mean" else std_sample(v, s.std_ddof)
            agg.append(r)
    return pd.concat([cells, pd.DataFrame(agg)], ignore_index=True)


def anon_mapping(cells: dict) -> pd.DataFrame:
    """kode_anonim stabil lintas split: urut user_id (numerik bila semua digit), A001, A002,..."""
    ids = sorted({u for df in cells.values() for u in df["user_id"]},
                 key=lambda u: (0, int(u), u) if u.isdigit() else (1, 0, u))
    width = max(3, len(str(len(ids))))
    return pd.DataFrame({"user_id": ids, "kode_anonim": [f"A{i:0{width}d}" for i in range(1, len(ids) + 1)],
                         "status": "INTERNAL - jangan masuk naskah"})


def error_patterns(cells: dict, mapping: pd.DataFrame, s: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    code = dict(zip(mapping["user_id"], mapping["kode_anonim"]))
    initials = {"akun": "A", "teks": "T", "gabungan": "G"}
    per_akun, summary = [], []
    for sl in s.splits:
        merged = None
        for c in s.configs:
            f = cells[(sl, c)].rename(columns={"y_pred": f"y_pred_{c}"})
            merged = f if merged is None else merged.merge(f.drop(columns="y_true"), on="user_id", how="inner",
                                                           validate="one_to_one")
        for c in s.configs:
            merged[f"benar_{c}"] = (merged[f"y_pred_{c}"] == merged["y_true"]).astype(int)
        merged["pola"] = [ "".join(f"{initials[c]}{r[f'benar_{c}']}" for c in ("akun", "teks", "gabungan"))
                          for _, r in merged.iterrows()]
        merged["jumlah_konfigurasi_benar"] = merged[[f"benar_{c}" for c in s.configs]].sum(axis=1)
        merged.insert(0, "split", sl)
        merged.insert(1, "kode_anonim", merged["user_id"].map(code))
        per_akun.append(merged)
        for yt in (1, 0):
            for p in PATTERNS:
                summary.append({"split": sl, "y_true": yt, "pola": p,
                                "jumlah_akun": int(((merged["y_true"] == yt) & (merged["pola"] == p)).sum())})
    per = pd.concat(per_akun, ignore_index=True)
    order = {sl: i for i, sl in enumerate(s.splits)}
    per = per.sort_values(["split", "kode_anonim"], key=lambda col: col.map(order) if col.name == "split" else col,
                          kind="stable").reset_index(drop=True)
    return pd.DataFrame(summary), per


def pola_output(summary: pd.DataFrame, per: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Satu berkas: bagian 'ringkasan_pola' lalu 'per_akun'."""
    a = summary.assign(bagian="ringkasan_pola")
    cols_per = ["split", "kode_anonim", "y_true", *[f"y_pred_{c}" for c in s.configs], *[f"benar_{c}" for c in s.configs],
                "jumlah_konfigurasi_benar", "pola"]
    b = per[cols_per].assign(bagian="per_akun")
    cols = ["bagian", "split", "y_true", "pola", "jumlah_akun", "kode_anonim", *[f"y_pred_{c}" for c in s.configs],
            *[f"benar_{c}" for c in s.configs], "jumlah_konfigurasi_benar"]
    out = pd.concat([a, b], ignore_index=True)[cols]
    for c in ["jumlah_akun", *[f"y_pred_{c}" for c in s.configs], *[f"benar_{c}" for c in s.configs],
              "jumlah_konfigurasi_benar"]:
        out[c] = out[c].astype("Int64")
    return out


def cross_split(per: pd.DataFrame, s: Settings) -> pd.DataFrame:
    rows = []
    for code, g in per.groupby("kode_anonim", sort=True):
        r = {"kode_anonim": code, "jumlah_split_uji": len(g),
             "split_uji": ";".join(sl for sl in s.splits if sl in set(g["split"])), "y_true": int(g["y_true"].iloc[0])}
        if g["y_true"].nunique() != 1:
            raise AblationError(f"{code}: y_true berbeda antar split")
        r.update({f"salah_{c}": int((g[f"benar_{c}"] == 0).sum()) for c in s.configs})
        rows.append(r)
    return pd.DataFrame(rows)


def raw_features(features_path: Path, per: pd.DataFrame, s: Settings) -> tuple[pd.DataFrame | None, dict]:
    """Fitur mentah (sebelum scaling) untuk akun pola menarik."""
    p = Path(features_path)
    fe_report = None
    for cand in ([p / "report.json"] if p.is_dir() else [p.parent / "report.json", p.parent.parent / "report.json"]):
        if cand.exists():
            fe_report = cand
            break
    if fe_report is not None and "scaling_status" in json.loads(fe_report.read_text(encoding="utf-8")):
        return None, {"status": "tidak_tersedia",
                      "alasan": f"{p} adalah keluaran FE yang sudah ter-scaling ({fe_report.name} memuat scaling_status); "
                                "fitur mentah tidak tersedia dan inverse transform tidak dilakukan."}
    if p.is_dir() or p.suffix.lower() != ".csv":
        return None, {"status": "tidak_tersedia", "alasan": f"{p} bukan berkas CSV fitur mentah"}
    raw = pd.read_csv(p, dtype={s.col_user_id: str})
    need = [s.col_user_id, s.col_split, *FEATURES]
    missing = [c for c in need if c not in raw.columns]
    if missing:
        raise AblationError(f"{p.name}: kolom fitur mentah tidak ada {missing}")
    raw = raw.assign(**{s.col_split: raw[s.col_split].map({v: k for k, v in s.splits.items()})})
    interesting = per[per["jumlah_konfigurasi_benar"].isin([0, 1])]
    merged = interesting.merge(raw[need].rename(columns={s.col_user_id: "user_id", s.col_split: "split"}),
                               on=["user_id", "split"], how="left", validate="one_to_one", indicator=True)
    lacking = merged[merged["_merge"] != "both"]
    if len(lacking):
        raise AblationError(f"{len(lacking)} akun pola menarik tidak punya baris fitur mentah di {p.name}")
    cols = ["split", "kode_anonim", "y_true", "pola", "jumlah_konfigurasi_benar", *FEATURES]
    return merged[cols].reset_index(drop=True), {"status": "dipakai", "path": str(p), "n_akun": len(merged)}
