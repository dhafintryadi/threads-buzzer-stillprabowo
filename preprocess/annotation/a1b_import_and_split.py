"""A1b -- impor label manual, bagi subset menjadi tuning dan validation."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import llm
from .common import (FIELDS, LABELS, POSITIVE, AnnotationError, add_manifest, check_guideline, paths, problems,
                     read_clean_data, read_csv_str, read_ls_export, refuse_overwrite, write_csv)
from .metrics import threshold_note


def read_manual_labels(path: Path, expected: set[str], annotator: str | None, cfg: dict) -> pd.DataFrame:
    """Dari ekspor Label Studio (.json) atau subset CSV berisi manual_ku, manual_ip1..ip4, manual_label."""
    manual_cols = {f: f"manual_{f}" for f in FIELDS}
    if path.suffix.lower() == ".json":
        return read_ls_export(path, expected, cfg).rename(columns=manual_cols)
    if not path.exists():
        raise AnnotationError(f"Berkas label manual belum ada: {path}. Ekspor dari Label Studio (Export -> JSON) ke lokasi ini.")
    df = read_csv_str(path)
    for col in manual_cols.values():
        df[col] = df.get(col, pd.Series("", index=df.index)).str.strip()
    df["annotator_id"] = df.get("annotator_id", pd.Series("", index=df.index)).replace("", annotator or "")
    df["labeled_at"] = ""
    ip_mode = cfg["output_schema"]["ip_when_ku_not_met"]
    errs = [f"{u}: " + "; ".join(bad) for u, rec in zip(df.user_id, df[list(manual_cols.values())].to_dict("records"))
            if (bad := problems({f: rec[c] for f, c in manual_cols.items()}, ip_mode))]
    errs += [f"{u}: muncul lebih dari sekali" for u in sorted(set(df.user_id[df.user_id.duplicated()]))]
    errs += [f"{u}: tidak ada" for u in sorted(expected - set(df.user_id))]
    errs += [f"{u}: bukan akun subset" for u in sorted(set(df.user_id) - expected)]
    if (df.annotator_id == "").any():
        errs.append("annotator_id kosong -- isi kolomnya atau pakai --annotator")
    if errs:
        raise AnnotationError(f"Label manual ditolak ({len(errs)} masalah):\n  " + "\n  ".join(errs[:20]))
    return df[["user_id", *manual_cols.values(), "annotator_id", "labeled_at"]]


def split(labels: pd.DataFrame, tuning_fraction: float, seed: int, stratify: bool) -> pd.Series:
    """'tuning'/'validation' per baris; deterministik."""
    rng = np.random.default_rng(seed)
    out = pd.Series("validation", index=labels.index)
    groups = [labels.index[labels.manual_label == lab] for lab in LABELS] if stratify else [labels.index]
    for idx in groups:
        idx = labels.loc[idx].sort_values("user_id").index.to_numpy()
        chosen = idx[rng.permutation(len(idx))[: math.floor(tuning_fraction * len(idx))]]
        out[chosen] = "tuning"
    return out


def run(cfg: dict, labels_path: Path, annotator: str | None = None) -> pd.DataFrame:
    p = paths(cfg)
    check_guideline(cfg)
    refuse_overwrite(p.manual_subset, "manual_subset")
    if not p.subset.exists():
        raise AnnotationError("Subset belum ada. Jalankan: python -m annotation a1")
    frac, min_pos = cfg["subset"]["split_tuning_fraction"], cfg["subset"]["min_validation_positives"]
    threshold = cfg["optimization"]["recall_threshold"]
    expected = set(read_csv_str(p.subset).user_id)

    df = read_manual_labels(Path(labels_path), expected, annotator, cfg).sort_values("user_id").reset_index(drop=True)
    df, rule_issues = llm.apply_manual_rules(df, "manual_", read_clean_data(cfg)[0], cfg)
    df["split"] = split(df, frac, cfg["subset"]["seed"], cfg["subset"]["stratify_split_by_manual_label"])
    tun, val = set(df.user_id[df.split == "tuning"]), set(df.user_id[df.split == "validation"])
    assert not tun & val and tun | val == expected, "I1 dilanggar"

    counts = pd.crosstab(df.split, df.manual_label).reindex(index=["tuning", "validation"], columns=list(LABELS), fill_value=0)
    val_pos = int(counts.loc["validation", POSITIVE])
    print(counts.to_string(), "\n")
    if val_pos == 0:
        raise AnnotationError("Validation set tidak memuat akun buzzer: recall tidak terdefinisi dan kriteria berhenti "
                              "tidak dapat dievaluasi. manual_subset.csv tidak ditulis; periksa label manual subset.")
    print("Ambang recall pada validation:", threshold_note(val_pos, threshold))
    if val_pos < min_pos:
        print(f"PERINGATAN: validation set hanya memuat {val_pos} buzzer (< min_validation_positives {min_pos}).")

    write_csv(df[["user_id", *[f"manual_{f}" for f in FIELDS], "split", "annotator_id", "labeled_at"]], p.manual_subset)
    add_manifest(cfg, "a1b_import_and_split", [Path(labels_path), p.subset], [p.manual_subset],
                 {"counts": {f"{s}/{l}": int(v) for (s, l), v in counts.stack().items()}, "tuning_fraction": frac,
                  "validation_positives": val_pos, "threshold_note": threshold_note(val_pos, threshold),
                  "rule_check": rule_issues})
    print("GATE 2 -- isi prompts/prompt_v1.yaml, lalu: python -m annotation a2 --version v1")
    return df


def move_to_tuning(cfg: dict, user_ids: list[str], reason: str) -> pd.DataFrame:
    """[keputusan peneliti] Pindahkan akun validation ke tuning setelah evaluasi."""
    from .a2_eval_prompt import ROUND_COLUMNS, read_rounds, score
    from .common import now_utc, read_json
    from .metrics import decide

    p = paths(cfg)
    if p.frozen.exists():
        raise AnnotationError(f"Prompt sudah dibekukan ({read_json(p.frozen)['prompt_version']}); split tidak boleh diubah lagi.")
    if not reason.strip():
        raise AnnotationError("Isi alasan pemindahan (--reason).")
    manual = read_csv_str(p.manual_subset)
    val = set(manual.user_id[manual.split == "validation"])
    bad = [u for u in user_ids if u not in val]
    if bad:
        raise AnnotationError(f"Bukan akun validation: {bad}")
    after = manual.assign(split=manual.split.where(~manual.user_id.isin(user_ids), "tuning"))
    if not ((after.split == "validation") & (after.manual_label == POSITIVE)).any():
        raise AnnotationError("Validation set tidak lagi memuat akun buzzer; pemindahan dibatalkan.")

    rounds = read_rounds(cfg)
    n_move = (len(read_csv_str(p.split_moves).move_id.unique()) if p.split_moves.exists() else 0) + 1
    log = pd.DataFrame([{"move_id": n_move, "user_id": u, "from_split": "validation", "to_split": "tuning",
                         "manual_label": manual.set_index("user_id").loc[u, "manual_label"],
                         "after_round": int(rounds["round"].max()) if len(rounds) else 0,
                         "reason": reason.strip(), "moved_at": now_utc()} for u in user_ids])
    write_csv(log if not p.split_moves.exists() else pd.concat([read_csv_str(p.split_moves), log]), p.split_moves)
    write_csv(after, p.manual_subset)

    outputs = [p.manual_subset, p.split_moves]
    if len(rounds):
        archive = p.state / f"eval_rounds_before_move{n_move}.csv"
        write_csv(rounds, archive)
        rows = [r for x in rounds.drop_duplicates(["round", "repeat"]).itertuples()
                for r in score(cfg, after, int(x.round), int(x.repeat), x.prompt_version, x.prompt_sha256,
                               x.render_format, x.layout)]
        write_csv(pd.DataFrame(rows)[ROUND_COLUMNS], p.eval_rounds)
        outputs += [archive, p.eval_rounds]
    add_manifest(cfg, "move_to_tuning", [p.manual_subset], outputs, {"move_id": n_move, "user_ids": user_ids, "reason": reason})

    counts = pd.crosstab(after.split, after.manual_label).reindex(index=["tuning", "validation"], columns=list(LABELS), fill_value=0)
    print(f"{len(user_ids)} akun dipindah validation -> tuning (dicatat di {p.split_moves.name}).\n{counts.to_string()}\n")
    if len(rounds):
        new = read_rounds(cfg)
        print("Ronde dihitung ulang pada split baru (arsip lama:", f"{archive.name}):")
        for r in new[new["repeat"] == 1].to_dict(orient="records"):
            print(f"  {r['prompt_version']:<4} {r['set']:<10} n={r['n']:<3} buzzer={r['positives']:<3} recall={float(r['recall']):.3f} "
                  f"| TP {r['tp']} FN {r['fn']} FP {r['fp']} TN {r['tn']}")
        d = decide(new, cfg["optimization"]["recall_threshold"], cfg["optimization"]["max_optimizations"],
                   cfg["optimization"]["freeze_on_limit"])
        print("Status ronde terakhir pada split baru:", d["reason"], "(belum dibekukan; pembekuan hanya lewat a2)")
    print("PERINGATAN: recall validation sesudah pemindahan bias optimistis; pemindahan dicatat di state/split_moves.csv.")
    return after
