"""m00 -- gerbang prasyarat + split_manifest cadangan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import common as C

PASS, FAIL, PENDING = "lulus", "gagal", "tertunda"
GATE_NAMES = {
    1: "leksikon_beku",
    2: "penskalaan_terkonfirmasi",
    3: "kontrak_baris_dan_split",
    4: "daftar_putih_kolom_dan_nilai",
    5: "stratifikasi",
    6: "konsistensi_skala",
    7: "config_sha256_di_manifest",
}
SCALE_METHODS = ("zscore", "minmax")


def _result(gate: int, problems: list[str], notes: list[str] | None = None, status: str | None = None) -> dict:
    return {"gate": gate, "name": GATE_NAMES[gate], "status": status or (FAIL if problems else PASS),
            "problems": problems, "notes": notes or []}


def gate_lexicon(report: dict) -> dict:
    fr = report.get("lexicon_freeze")
    if not fr:
        return _result(1, ["laporan FE tidak memuat lexicon_freeze; hasilkan ulang fitur dengan FE terbaru"])
    problems, notes = [], []
    if fr.get("frozen") is not True:
        problems.append("lexicon.frozen belum true di config FE")
    if not fr.get("version"):
        problems.append("lexicon.version belum diisi")
    frozen = fr.get("frozen_sha256") or {}
    at_gen = fr.get("sha256_at_generation") or {}
    for k in ("a", "b"):
        if not frozen.get(k):
            problems.append(f"frozen_sha256.{k} belum diisi")
        elif at_gen.get(k) != frozen.get(k):
            problems.append(f"SHA-256 lexicon_{k} saat fitur dihasilkan != SHA-256 beku: fitur usang, hasilkan ulang")
    for k, feat in (("a", "kepadatan_leksikon_a"), ("b", "kepadatan_leksikon_b")):
        path = (report.get("leksikon", {}).get(feat) or {}).get("berkas")
        if path and Path(path).exists():
            if at_gen.get(k) and C.sha256_file(Path(path)) != at_gen[k]:
                problems.append(f"lexicon_{k}.txt berubah setelah fitur dihasilkan: hasilkan ulang fitur")
        else:
            notes.append(f"berkas lexicon_{k} tidak ditemukan untuk pemeriksaan ulang ({path})")
    return _result(1, problems, notes)


def gate_scaling(report: dict, cfg: dict) -> dict:
    st = report.get("scaling_status")
    if not st:
        return _result(2, ["laporan FE tidak memuat scaling_status; hasilkan ulang fitur dengan FE terbaru"])
    problems = []
    if st.get("confirmed") is not True:
        problems.append("scaler.confirmed belum true di config FE (aturan penskalaan belum dikonfirmasi)")
    methods = st.get("method_per_split") or {}
    for s in cfg["splits"]:
        name = C.split_name(cfg, s)
        m = methods.get(name)
        if m not in SCALE_METHODS:
            problems.append(f"{name}: metode penskalaan FE tidak dikenal/ tidak ada ({m!r})")
        elif (report.get("splits", {}).get(name, {}).get("scaling") or {}).get("method") not in (None, m):
            problems.append(f"{name}: method_per_split tidak sama dengan splits.{name}.scaling.method")
    notes = [f"aturan: {st.get('scaler_rule')}; outlier: {st.get('outlier')}"]
    return _result(2, problems, notes)


def _read_raw(cfg: dict) -> tuple[dict, list[str]]:
    frames, problems = {}, []
    for s in cfg["splits"]:
        paths = C.split_paths(cfg, s)
        try:
            frames[s] = {k: C.read_frame(p, cfg["run"]["label_col"]) for k, p in paths.items()}
        except C.ModelError as e:
            problems.append(str(e))
    return frames, problems


def gate_rows(cfg: dict, report: dict, frames: dict, read_problems: list[str], split_manifest: dict) -> dict:
    exp, label = cfg["expected"], cfg["run"]["label_col"]
    problems, notes = list(read_problems), []
    want = C.VARIANTS[cfg["run"]["input_variant"]]
    if report.get("lexicon_denominator") != want:
        problems.append(f"laporan FE lexicon_denominator {report.get('lexicon_denominator')!r} != {want!r} "
                        f"(input_variant {cfg['run']['input_variant']!r})")
    universes = []
    for s, fr in frames.items():
        name, tr, te = C.split_name(cfg, s), fr["train"], fr["test"]
        if "user_id" not in tr or "user_id" not in te or label not in tr or label not in te:
            problems.append(f"{name}: kolom user_id/{label} tidak ada")
            continue
        n = len(tr) + len(te)
        if n != exp["n_total"]:
            problems.append(f"{name}: latih + uji = {n} != {exp['n_total']}")
        ids_tr, ids_te = tr["user_id"].astype(str), te["user_id"].astype(str)
        if ids_tr.duplicated().any() or ids_te.duplicated().any():
            problems.append(f"{name}: user_id tidak unik di dalam latih/uji")
        both = sorted(set(ids_tr) & set(ids_te))
        if both:
            problems.append(f"{name}: {len(both)} user_id ada di latih DAN uji")
        n_pos = int(pd.to_numeric(tr[label], errors="coerce").eq(1).sum() + pd.to_numeric(te[label], errors="coerce").eq(1).sum())
        if n_pos != exp["n_buzzer"]:
            problems.append(f"{name}: total buzzer {n_pos} != {exp['n_buzzer']}")
        universes.append(frozenset(ids_tr) | frozenset(ids_te))
        sm = split_manifest.get("splits", {}).get(name)
        if sm is None:
            problems.append(f"{name}: tidak ada di split_manifest")
        else:
            if set(sm["train_user_ids"]) != set(ids_tr) or set(sm["test_user_ids"]) != set(ids_te):
                problems.append(f"{name}: user_id latih/uji tidak sama dengan split_manifest")
            paths = C.split_paths(cfg, s)
            for part in ("train", "test"):
                if sm.get(f"{part}_csv_sha256") != C.sha256_file(paths[part]):
                    problems.append(f"{name}: SHA-256 {part}.csv berbeda dari split_manifest (berkas berubah)")
    if len(set(universes)) > 1:
        problems.append("himpunan akun (latih + uji) berbeda antar split")
    notes.append(f"split_manifest generated_by = {split_manifest.get('generated_by')}")
    return _result(3, problems, notes)


def gate_columns(cfg: dict, frames: dict) -> dict:
    label, problems = cfg["run"]["label_col"], []
    for s, fr in frames.items():
        name = C.split_name(cfg, s)
        p = C.contract_problems(fr["train"], cfg, f"{name}/train") + C.contract_problems(fr["test"], cfg, f"{name}/test")
        if not p and set(pd.unique(pd.concat([fr["train"][label], fr["test"][label]]))) != {0, 1}:
            p.append(f"{name}: label harus memuat tepat {{0, 1}}")
        problems += p
    return _result(4, problems)


def stratification_deviation(n_pos_part: int, n_part: int, n_pos_total: int, n_total: int) -> float:
    """Selisih (dalam akun) jumlah buzzer bagian dari jumlah yang diharapkan bila proporsinya sama persis."""
    return n_pos_part - n_pos_total * n_part / n_total


def gate_stratification(cfg: dict, frames: dict) -> dict:
    label, problems, notes = cfg["run"]["label_col"], [], []
    for s, fr in frames.items():
        name = C.split_name(cfg, s)
        try:
            ytr, yte = fr["train"][label].astype(int), fr["test"][label].astype(int)
        except (KeyError, ValueError, TypeError):
            problems.append(f"{name}: label tidak terbaca")
            continue
        n, pos = len(ytr) + len(yte), int(ytr.sum() + yte.sum())
        dev = stratification_deviation(int(yte.sum()), len(yte), pos, n)
        line = (f"{name}: buzzer latih {int(ytr.sum())}/{len(ytr)} ({ytr.mean():.4f}), "
                f"uji {int(yte.sum())}/{len(yte)} ({yte.mean():.4f}); deviasi uji {dev:+.3f} akun")
        notes.append(line)
        if abs(dev) > 1 + 1e-9:
            problems.append(line + " > 1 akun")
    return _result(5, problems, notes)


def _standardized(x: np.ndarray, method: str, tol: float) -> tuple[bool, str]:
    if method == "zscore":
        mean, std = float(x.mean()), float(x.std(ddof=0))
        return abs(mean) <= tol and abs(std - 1) <= tol, f"mean {mean:.3g}, std {std:.9f}"
    lo, hi = float(x.min()), float(x.max())
    return abs(lo) <= tol and abs(hi - 1) <= tol, f"min {lo:.3g}, max {hi:.9f}"


def scale_consistency_problems(train: pd.DataFrame, test: pd.DataFrame, method: str, name: str,
                               tol: float = C.SCALE_TOL) -> tuple[list[str], list[str]]:
    problems, notes, test_fit = [], [], []
    for c in C.FEATURES:
        xtr, xte = train[c].to_numpy(dtype=float), test[c].to_numpy(dtype=float)
        if np.ptp(xtr) == 0:
            notes.append(f"{name}.{c}: konstan pada latih (tidak diperiksa)")
            continue
        ok, desc = _standardized(xtr, method, tol)
        if not ok:
            problems.append(f"{name}.{c}: latih tidak sesuai {method} yang di-fit pada latih ({desc})")
        if np.ptp(xte) > 0:
            test_fit.append(_standardized(xte, method, tol)[0])
    if test_fit and all(test_fit):
        problems.append(f"{name}: SEMUA fitur uji tepat terstandar {method} -> data uji tampak di-fit sendiri")
    return problems, notes


def gate_scale(cfg: dict, report: dict, frames: dict, columns_gate: dict) -> dict:
    methods = (report.get("scaling_status") or {}).get("method_per_split") or {}
    problems, notes = [], []
    for s, fr in frames.items():
        name = C.split_name(cfg, s)
        if methods.get(name) not in SCALE_METHODS:
            problems.append(f"{name}: metode penskalaan FE tidak diketahui; tidak dapat diperiksa")
            continue
        if any(p.startswith(f"{name}/") or p.startswith(f"{name}:") for p in columns_gate["problems"]):
            problems.append(f"{name}: kontrak kolom gagal (gerbang 4); tidak dapat diperiksa")
            continue
        p, n = scale_consistency_problems(fr["train"], fr["test"], methods[name], name)
        problems += p
        notes += n
    return _result(6, problems, notes)


def gate_config_hash(cfg: dict) -> dict:
    stored = C.read_manifest(cfg).get("config_sha256")
    current = C.config_sha256(cfg)
    if stored is None:
        return _result(7, [], [f"config belum dibekukan (jalankan `run_all.py freeze`); hash sekarang {current}"], PENDING)
    if stored != current:
        return _result(7, [f"config_sha256 di manifest {stored} != config sekarang {current}"])
    return _result(7, [], [f"config_sha256 {current}"])


def build_split_manifest(cfg: dict, report: dict, frames: dict) -> dict:
    """Cadangan bila FE belum menulis split_manifest.json; provenans seed dari laporan FE."""
    splits = {}
    for s, fr in frames.items():
        name, paths = C.split_name(cfg, s), C.split_paths(cfg, s)
        summary = (report.get("splits", {}).get(name) or {}).get("summary") or {}
        splits[name] = {
            "seed": summary.get("seed"), "test_size": summary.get("test_size"),
            "train_user_ids": fr["train"]["user_id"].astype(str).tolist(),
            "test_user_ids": fr["test"]["user_id"].astype(str).tolist(),
            "train_csv_sha256": C.sha256_file(paths["train"]), "test_csv_sha256": C.sha256_file(paths["test"]),
        }
    return {"generated_by": "model_m00", "created_utc": C.utc_now(), "variant": report.get("varian"),
            "input_sha256": (report.get("provenance") or {}).get("input_sha256"), "splits": splits}


def load_or_build_split_manifest(cfg: dict, report: dict, frames: dict) -> tuple[dict, Path]:
    fe_path = C.resolve(cfg, cfg["input"]["split_manifest"]) if cfg["input"].get("split_manifest") else None
    if fe_path and fe_path.exists():
        return json.loads(fe_path.read_text(encoding="utf-8")), fe_path
    sm = build_split_manifest(cfg, report, frames)
    out = C.run_dir(cfg) / "split_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    return sm, out


def run_checks(cfg: dict, write: bool = True) -> dict:
    report = C.read_fe_report(cfg)
    frames, read_problems = _read_raw(cfg)
    sm, sm_path = load_or_build_split_manifest(cfg, report, frames) if not read_problems else ({}, None)
    g4 = gate_columns(cfg, frames)
    gates = [
        gate_lexicon(report),
        gate_scaling(report, cfg),
        gate_rows(cfg, report, frames, read_problems, sm),
        g4,
        gate_stratification(cfg, frames),
        gate_scale(cfg, report, frames, g4),
        gate_config_hash(cfg),
    ]
    inputs = {}
    for s in cfg["splits"]:
        for part, p in C.split_paths(cfg, s).items():
            inputs[f"{C.split_name(cfg, s)}/{part}"] = {"path": str(p), "sha256": C.sha256_file(p) if p.exists() else None}
    fe_path = C.resolve(cfg, cfg["input"]["fe_manifest"])
    result = {
        "checked_utc": C.utc_now(),
        "gates": gates,
        "gates_1_6_passed": all(g["status"] == PASS for g in gates[:6]),
        "inputs": {
            "files": inputs,
            "fe_report": {"path": str(fe_path), "sha256": C.sha256_file(fe_path), "varian": report.get("varian"),
                          "lexicon_denominator": report.get("lexicon_denominator"), "created_utc": report.get("dibuat_utc")},
            "split_manifest": {"path": str(sm_path) if sm_path else None, "generated_by": sm.get("generated_by"),
                               "sha256": C.sha256_file(sm_path) if sm_path else None},
        },
        "fe": {
            "lexicon_freeze": report.get("lexicon_freeze"),
            "scaling_status": report.get("scaling_status"),
            "seeds": {n: (sp.get("summary") or {}).get("seed") for n, sp in (report.get("splits") or {}).items()},
            "provenance": report.get("provenance"),
        },
    }
    if write:
        C.update_manifest(cfg, checks=result)
    for g in gates:
        C.log.info("[m00] gerbang %d %-28s %s%s", g["gate"], g["name"], g["status"],
                   "" if not g["problems"] else f" ({len(g['problems'])} masalah)")
    return result


def require(cfg: dict, need_config_hash: bool = False) -> dict:
    res = run_checks(cfg)
    failed = [g for g in res["gates"][:6] if g["status"] != PASS]
    g7 = res["gates"][6]
    if need_config_hash and g7["status"] != PASS:
        failed.append(g7 if g7["problems"] else {**g7, "problems": g7["notes"]})
    if failed:
        lines = [f"gerbang {g['gate']} ({g['name']}): " + "; ".join(g["problems"]) for g in failed]
        raise C.GateError("Gerbang prasyarat gagal:\n  - " + "\n  - ".join(lines))
    return res


def format_gates(res: dict) -> str:
    out = []
    for g in res["gates"]:
        out.append(f"  [{g['status']:^8}] {g['gate']}. {g['name']}")
        out += [f"             - {p}" for p in g["problems"]]
        out += [f"             . {n}" for n in g["notes"]]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="m00: gerbang prasyarat")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    C.setup_logging()
    cfg = C.load_config(args.config)
    res = run_checks(cfg)
    print(format_gates(res))
    return 0 if res["gates_1_6_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
