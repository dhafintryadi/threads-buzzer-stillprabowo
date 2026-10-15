"""Orkestrasi rekayasa fitur: fitur row-wise, split, lalu fitur yang di-fit per split pada data latih."""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .account_features import ACCOUNT_FEATURES, compute_account_features
from .lexicon import DENOMINATORS, distribution, lexicon_density, load_lexicon
from .report import write_report_md
from .scaling import choose_method, fit_transform, outlier_summary
from .settings import FeatureEngineeringError, all_features, load_clean_shared, resolve
from .similarity import similarity_for_split
from .split import make_splits, split_summary
from .validate import load_input, validate

TEXT_FEATURES = ["similarity", "kepadatan_leksikon_a", "kepadatan_leksikon_b"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _versions() -> dict:
    out = {"python": platform.python_version()}
    for lib in ("pandas", "numpy", "scikit-learn", "PyYAML"):
        try:
            out[lib] = md.version(lib)
        except md.PackageNotFoundError:
            out[lib] = None
    return out


class Checks:
    """Pemeriksaan wajib: gagal -> berhenti; setiap hasil dicatat di laporan."""

    def __init__(self):
        self.items: list[dict] = []

    def require(self, name: str, ok: bool, detail: str = "", split: str | None = None) -> None:
        self.items.append({"check": name, "split": split, "passed": bool(ok), "detail": detail})
        if not ok:
            raise FeatureEngineeringError(f"Pemeriksaan gagal [{split or 'global'}] {name}: {detail}")


def _check_config(cfg: dict) -> None:
    feats = cfg["features"]
    if feats["akun"] != ACCOUNT_FEATURES or feats["teks"] != TEXT_FEATURES:
        raise FeatureEngineeringError(
            f"config.features harus akun={ACCOUNT_FEATURES}, teks={TEXT_FEATURES}."
        )
    if cfg["lexicon"]["occurrence"] != "total" or cfg["lexicon"]["stemming"] is not False:
        raise FeatureEngineeringError("Hanya lexicon.occurrence='total' dan lexicon.stemming=false yang diimplementasikan.")
    if cfg["lexicon"].get("denominator") not in DENOMINATORS:
        raise FeatureEngineeringError(f"lexicon.denominator harus salah satu {DENOMINATORS}.")


def _lexicon_freeze_status(cfg: dict) -> dict:
    """Bila leksikon ditandai beku, isinya harus sama persis dengan SHA-256 yang dibekukan."""
    lx = cfg["lexicon"]
    frozen_sha = dict(lx.get("frozen_sha256") or {})
    current = {k: _sha256(resolve(cfg, f"lexicon_{k}_txt")) for k in ("a", "b") if resolve(cfg, f"lexicon_{k}_txt").exists()}
    if lx.get("frozen"):
        missing = [k for k in ("version",) if not lx.get(k)] + [f"frozen_sha256.{k}" for k in ("a", "b") if not frozen_sha.get(k)]
        if missing:
            raise FeatureEngineeringError(f"lexicon.frozen = true tetapi {missing} belum diisi di config.")
        changed = [k for k in ("a", "b") if current.get(k) != frozen_sha.get(k)]
        if changed:
            raise FeatureEngineeringError(
                f"Leksikon beku {lx['version']!r} berubah: SHA-256 lexicon_{changed} tidak sama dengan frozen_sha256. "
                f"Kembalikan isi leksikon atau naikkan versi dan bekukan ulang."
            )
    return {"version": lx.get("version"), "frozen": bool(lx.get("frozen")), "frozen_sha256": frozen_sha,
            "sha256_at_generation": current}


def build(cfg: dict) -> dict:
    """Hitung semua fitur dan pemeriksaan di memori (tidak menulis berkas)."""
    _check_config(cfg)
    denominator = cfg["lexicon"]["denominator"]
    checks = Checks()
    features = all_features(cfg)

    input_path = resolve(cfg, "input_csv")
    df = load_input(input_path, cfg)
    input_info = validate(df, cfg.get("expected_rows"))
    clean = load_clean_shared(cfg)

    base = compute_account_features(df)
    for f in ("rasio_balasan", "rasio_unggahan_ulang"):
        checks.require(f"{f} dalam [0, 1]", bool(base[f].between(0, 1).all()), f"min {base[f].min()}, max {base[f].max()}")

    freeze = _lexicon_freeze_status(cfg)
    lexicons = {
        "a": load_lexicon(resolve(cfg, "lexicon_a_txt"), "A", clean),
        "b": load_lexicon(resolve(cfg, "lexicon_b_txt"), "B", clean),
    }
    dens, term_totals = lexicon_density(df["caption_text"], lexicons, clean, denominator)
    base = pd.concat([base, dens.reset_index(drop=True)], axis=1)
    lexicon_report, warnings = {}, []
    for key, lx in lexicons.items():
        col = f"kepadatan_leksikon_{key}"
        dist = distribution(base[col])
        lexicon_report[col] = {
            "berkas": lx.path, "sha256": lx.sha256, "baris_istilah": lx.n_lines, "entri_setelah_dedup": lx.n_entries,
            "duplikat_dibuang": lx.duplicates, "total_kemunculan": int(base[f"n_match_{key}"].sum()),
            "kemunculan_per_istilah": dict(sorted(term_totals[key].items(), key=lambda kv: (-kv[1], kv[0]))),
            "distribusi": dist,
        }
        if dist["pct_zero"] > 100 * cfg["lexicon"]["sparse_warning_zero_prop"]:
            warnings.append(
                f"{col}: {dist['pct_zero']}% akun bernilai 0 (> {100 * cfg['lexicon']['sparse_warning_zero_prop']:.0f}%) "
                f"-- indikasi leksikon terlalu jarang; dilaporkan, tidak diperbaiki."
            )

    labels = df["label"].astype(int).to_numpy()
    p_all = float(labels.mean())
    tol = float(cfg["split"]["stratify_tolerance"])
    splits_out = {}
    for sp in make_splits(df, cfg):
        name = sp["name"]
        tr_pos, te_pos = sp["train_pos"], sp["test_pos"]
        summary = split_summary(df, sp)
        checks.require("train + test = N", len(tr_pos) + len(te_pos) == len(df), f"{len(tr_pos)} + {len(te_pos)}", name)
        overlap = set(df["user_id"].iloc[tr_pos]) & set(df["user_id"].iloc[te_pos])
        checks.require("tidak ada user_id di train dan test sekaligus", not overlap, f"{len(overlap)} tumpang tindih", name)
        for part in ("train", "test"):
            p = summary[f"prop_buzzer_{part}"]
            checks.require(f"proporsi buzzer {part} ~ {p_all:.4f}", abs(p - p_all) <= tol, f"{p:.4f} (toleransi {tol})", name)

        train = base.iloc[tr_pos].reset_index(drop=True)
        test = base.iloc[te_pos].reset_index(drop=True)
        sim = similarity_for_split(df["caption_text_stream_t"], tr_pos, te_pos, cfg)
        checks.require("TfidfVectorizer di-fit hanya pada data latih", sim["n_fit_docs"] == len(tr_pos), f"{sim['n_fit_docs']} dokumen", name)
        train["similarity"], test["similarity"] = sim["train"], sim["test"]
        checks.require("similarity dalam [0, 1]",
                       bool((train["similarity"].between(0, 1)).all() and (test["similarity"].between(0, 1)).all()),
                       f"train {train['similarity'].min():.4f}-{train['similarity'].max():.4f}, "
                       f"test {test['similarity'].min():.4f}-{test['similarity'].max():.4f}", name)

        outliers = outlier_summary(train, features, cfg)
        choice = choose_method(outliers, cfg)
        tr_s, te_s, params, scaler = fit_transform(train, test, features, choice["method"])
        checks.require("scaler di-fit hanya pada data latih", int(scaler.n_samples_seen_) == len(tr_pos), f"{int(scaler.n_samples_seen_)} sampel", name)
        checks.require("tidak ada NaN/inf di fitur akhir",
                       bool(np.isfinite(tr_s.to_numpy()).all() and np.isfinite(te_s.to_numpy()).all()), "", name)

        splits_out[name] = {
            "summary": {**summary, "tfidf_vocabulary_size": sim["vocabulary_size"],
                        "caption_text_clean_kosong": {"train": sim["empty_docs_train"], "test": sim["empty_docs_test"]}},
            "outliers": outliers, "scaling": {**choice, "params": params},
            "train": pd.concat([train[["user_id"]], tr_s, pd.Series(labels[tr_pos], name="label")], axis=1),
            "test": pd.concat([test[["user_id"]], te_s, pd.Series(labels[te_pos], name="label")], axis=1),
        }

    report = {
        "status": "selesai",
        "varian": "utama",
        "lexicon_denominator": denominator,
        "penyebut_kepadatan": ("jumlah entri leksikon (setelah dedup)" if denominator == "entries"
                               else "jumlah token aliran leksikon per akun"),
        "akun_tanpa_token_leksikon": int((base["n_tokens"] == 0).sum()),
        "dibuat_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "input": str(input_path), "input_sha256": _sha256(input_path),
            "config": cfg["_config_path"], "config_sha256": _sha256(Path(cfg["_config_path"])),
            "shared_clean_py_sha256": _sha256(resolve(cfg, "shared_clean_py")),
            "versions": _versions(),
            "teks_tfidf": "caption_text_clean (aliran T, preprocess tahap 06)",
            "teks_leksikon": "caption_text -> clean_shared + segmentasi/tokenisasi dual-stream, tanpa stopword removal, tanpa stemming",
        },
        "input": input_info,
        "parameter_menunggu_konfirmasi": {
            "outlier": cfg["outlier"], "scaler": cfg["scaler"],
            "lexicon_occurrence": cfg["lexicon"]["occurrence"], "lexicon_stemming": cfg["lexicon"]["stemming"],
        },
        "leksikon": lexicon_report,
        "lexicon_freeze": freeze,
        "scaling_status": {
            "confirmed": bool(cfg["scaler"].get("confirmed")),
            "outlier": cfg["outlier"], "scaler_rule": cfg["scaler"]["rule"],
            "method_per_split": {k: v["scaling"]["method"] for k, v in splits_out.items()},
        },
        "splits": {k: {kk: vv for kk, vv in v.items() if kk not in ("train", "test")} for k, v in splits_out.items()},
        "checks": checks.items,
        "warnings": warnings,
    }
    return {"report": report, "splits": splits_out, "features": features}


def _write(result: dict, out_dir: Path, cfg: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, sp in result["splits"].items():
        d = out_dir / name
        d.mkdir(parents=True, exist_ok=True)
        sp["train"].to_csv(d / "train.csv", index=False, encoding="utf-8")
        sp["test"].to_csv(d / "test.csv", index=False, encoding="utf-8")
    akun, teks = list(cfg["features"]["akun"]), list(cfg["features"]["teks"])
    (out_dir / "feature_config.json").write_text(json.dumps(
        {"akun": akun, "teks": teks, "gabungan": akun + teks,
         "catatan": "Penskalaan di-fit sekali per split pada seluruh 8 fitur; konfigurasi hanya memilih subset kolom."},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(result["report"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_report_md(result["report"], out_dir / "report.md")
    rep = result["report"]
    split_manifest = {
        "generated_by": "feature_engineering",
        "created_utc": rep["dibuat_utc"],
        "variant": rep["varian"],
        "input_sha256": rep["provenance"]["input_sha256"],
        "lexicon_freeze": rep["lexicon_freeze"],
        "scaling_status": rep["scaling_status"],
        "splits": {
            name: {
                "seed": sp["summary"]["seed"], "test_size": sp["summary"]["test_size"],
                "train_user_ids": sp["train"]["user_id"].astype(str).tolist(),
                "test_user_ids": sp["test"]["user_id"].astype(str).tolist(),
                "train_csv_sha256": _sha256(out_dir / name / "train.csv"),
                "test_csv_sha256": _sha256(out_dir / name / "test.csv"),
            }
            for name, sp in result["splits"].items()
        },
    }
    (out_dir / "split_manifest.json").write_text(json.dumps(split_manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cfg: dict) -> dict:
    """Satu set fitur (penyebut kepadatan = lexicon.denominator)."""
    result = build(cfg)
    _write(result, resolve(cfg, "output_dir"), cfg)
    return result
