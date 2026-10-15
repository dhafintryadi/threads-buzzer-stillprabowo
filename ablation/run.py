"""Analisis ablasi dari keluaran run model."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import analyses as A
from .config import Settings
from .figures import fig_makro_f1, fig_perkelas_buzzer
from .inputs import AblationError, discover, read_optional_csv, sha256_file, validate
from .report import ringkasan_md, versions

OUTPUTS = ["ablasi_tabel_9sel.csv", "ablasi_agregat.csv", "ablasi_delta.csv", "ablasi_perkelas.csv",
           "ablasi_peringkat.csv", "ablasi_baseline.csv", "ablasi_pola_error_per_akun.csv", "ablasi_mapping_anonim.csv",
           "fig_makrof1_per_konfigurasi.png", "fig_perkelas_buzzer.png", "ablasi_ringkasan.md"]


def _write_csv(df, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def run(s: Settings, features_path: Path | None = None, cross_split: bool = False, log=print) -> dict:
    out = s.out_dir.resolve()
    run_dir = s.run_dir.resolve()
    if out == run_dir or run_dir in out.parents:
        raise AblationError(f"Direktori keluaran {out} berada di dalam direktori run modeling (read-only)")

    found = discover(s)
    log(f"Masukan: {found['path']}")
    for (sl, cl), m in found["cells"].items():
        log(f"  sel {sl} x {cl:<8} -> {m['path']} {m['filter']} ({m['n_rows']} baris)")
    cells = validate(found["frame"], s)

    metrics_path, base_path = s.run_dir / s.model_metrics_file, s.run_dir / s.model_baselines_file
    model_metrics, model_baselines = read_optional_csv(metrics_path), read_optional_csv(base_path)

    table = A.cell_table(cells, s)
    check_metrics = A.crosscheck_model_metrics(table, model_metrics, s)
    baseline, check_base = A.baseline_table(cells, s, model_baselines)
    for sl in s.splits:
        sub = table[table["split"] == sl]
        if sub["n_test"].nunique() != 1 or ((sub["tp"] + sub["fp"] + sub["fn"] + sub["tn"]) != sub["n_test"]).any():
            raise AblationError(f"split {sl}: n_test tidak konsisten antar konfigurasi")

    t9, agg = A.tabel_9sel(table), A.agregat(table, baseline, s)
    dlt, rank, perk = A.delta(table, s), A.peringkat(table, s), A.perkelas(table, s)
    mapping = A.anon_mapping(cells)
    pola_summary, per = A.error_patterns(cells, mapping, s)

    out.mkdir(parents=True, exist_ok=True)
    _write_csv(t9, out / "ablasi_tabel_9sel.csv")
    _write_csv(agg, out / "ablasi_agregat.csv")
    _write_csv(dlt, out / "ablasi_delta.csv")
    _write_csv(perk, out / "ablasi_perkelas.csv")
    _write_csv(rank, out / "ablasi_peringkat.csv")
    _write_csv(baseline, out / "ablasi_baseline.csv")
    _write_csv(A.pola_output(pola_summary, per, s), out / "ablasi_pola_error_per_akun.csv")
    _write_csv(mapping, out / "ablasi_mapping_anonim.csv")
    fig_makro_f1(agg, table, s, out / "fig_makrof1_per_konfigurasi.png")
    fig_perkelas_buzzer(table, s, out / "fig_perkelas_buzzer.png")
    (out / "ablasi_ringkasan.md").write_text(ringkasan_md(t9, baseline, agg, dlt, rank, perk, pola_summary, s.run_id),
                                             encoding="utf-8", newline="\n")
    written = list(OUTPUTS)

    optional = {"cross_split": None, "fitur_mentah": None}
    if cross_split:
        _write_csv(A.cross_split(per, s), out / "ablasi_lintas_split.csv")
        written.append("ablasi_lintas_split.csv")
        optional["cross_split"] = {"status": "dipakai"}
    if features_path is not None:
        feats, status = A.raw_features(Path(features_path), per, s)
        optional["fitur_mentah"] = status
        if feats is not None:
            _write_csv(feats, out / "ablasi_fitur_mentah_pola_menarik.csv")
            written.append("ablasi_fitur_mentah_pola_menarik.csv")
        else:
            log(f"LAPORAN: fitur mentah tidak dipakai -- {status['alasan']}")

    inputs = {str(found["path"]): sha256_file(found["path"])}
    for p in (metrics_path, base_path):
        if p.exists():
            inputs[str(p)] = sha256_file(p)
    manifest = {
        "run_id": s.run_id,
        "dibuat_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "direktori_run_modeling": str(s.run_dir), "direktori_keluaran": str(out),
        "masukan_sha256": inputs,
        "pemetaan_sel": {f"{sl} x {cl}": m for (sl, cl), m in found["cells"].items()},
        "csv_kandidat_prediksi": found["candidates"],
        "validasi": "lulus",
        "cross_check": {"makro_f1_vs_sklearn": {"status": "cocok", "toleransi": s.crosscheck_tol},
                        "metrik_modeling": check_metrics, "baseline_modeling": check_base},
        "std_ddof": s.std_ddof, "toleransi_seri_peringkat": s.tie_tol, "konfigurasi_referensi": s.reference_config,
        "k_per_sel_metadata": A.k_metadata(model_metrics, s),
        "opsi": {"features_path": str(features_path) if features_path else None, "cross_split": cross_split,
                 **optional},
        "berkas_internal": {"ablasi_mapping_anonim.csv": "INTERNAL - berisi user_id; jangan masuk naskah"},
        "keluaran_sha256": {f: sha256_file(out / f) for f in written},
        "versi_pustaka": versions(),
        "settings": {k: (str(v) if isinstance(v, Path) else v) for k, v in dataclasses.asdict(s).items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    log(f"Selesai: {len(written) + 1} berkas -> {out}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", default=Settings.run_id)
    ap.add_argument("--features-path", default=None, help="opsional: CSV fitur MENTAH (split, user_id, 8 fitur)")
    ap.add_argument("--cross-split", action="store_true", help="opsional: ringkasan per akun lintas split")
    args = ap.parse_args(argv)
    s = Settings(run_id=args.run_id)
    try:
        run(s, Path(args.features_path) if args.features_path else None, args.cross_split)
    except AblationError as e:
        print(f"\nBERHENTI: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
