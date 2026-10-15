"""A2b -- kandidat few-shot dari ronde terakhir, hanya dari TUNING set."""

from __future__ import annotations

import pandas as pd

from . import llm
from .a2_eval_prompt import read_rounds
from .common import FIELDS, AnnotationError, add_manifest, check_guideline, paths, read_clean_data, read_csv_str, write_csv


def candidates(tuning: pd.DataFrame, pred: pd.DataFrame) -> pd.DataFrame:
    df = tuning.merge(pred[["user_id", *FIELDS]].rename(columns={f: f"llm_{f}" for f in FIELDS}), on="user_id")

    def value(x):
        return None if x is None or (isinstance(x, float) and pd.isna(x)) or x == "" else x

    def diffs(r) -> str:
        ku_tidak = r["manual_ku"] == r["llm_ku"] == "tidak"
        return ",".join(f for f in FIELDS
                        if not (ku_tidak and f.startswith("ip") and value(r[f"llm_{f}"]) is None)
                        and value(r[f"manual_{f}"]) != value(r[f"llm_{f}"]))

    df["diff_fields"] = [diffs(r) for _, r in df.iterrows()]
    df["error_type"] = [("FN" if m == "buzzer" else "FP") if m != l else "label_benar"
                        for m, l in zip(df.manual_label, df.llm_label)]
    df = df[df.diff_fields != ""].assign(_wrong=lambda d: d.error_type != "label_benar",
                                         _n=lambda d: d.diff_fields.str.count(",") + 1)
    cols = ["user_id", "error_type", "diff_fields"] + [c for f in FIELDS for c in (f"manual_{f}", f"llm_{f}")]
    return df.sort_values(["_wrong", "_n", "user_id"], ascending=[False, False, True])[cols]


def run(cfg: dict) -> str:
    p = paths(cfg)
    check_guideline(cfg)
    rounds = read_rounds(cfg)
    if not len(rounds):
        raise AnnotationError("Belum ada ronde evaluasi. Jalankan dulu: python -m annotation a2 --version v1")
    last = rounds[rounds["round"] == rounds["round"].max()].iloc[0]
    manual = read_csv_str(p.manual_subset)
    tuning = manual[manual.split == "tuning"]
    cand = candidates(tuning, llm.ok_labels(cfg, last.prompt_sha256, "eval"))
    clean, _ = read_clean_data(cfg)
    cand = cand.merge(clean[["user_id", "caption_text"]], on="user_id")
    out = p.state / f"fewshot_candidates_round{int(last['round'])}.csv"
    write_csv(cand, out)
    add_manifest(cfg, "a2b_fewshot_candidates", [p.eval_rounds, p.manual_subset], [out], {"n_candidates": len(cand)})

    nxt = f"v{int(str(last.prompt_version).lstrip('v')) + 1}" if str(last.prompt_version).lstrip("v").isdigit() else "<versi baru>"
    print(f"{len(cand)} kandidat dari tuning set -> {out.name}")
    print(cand.error_type.value_counts().to_string())
    print("Bidang yang paling sering berbeda:",
          pd.Series([f for d in cand.diff_fields for f in d.split(",")]).value_counts().to_dict())
    print(f"GATE 2 -- tulis prompts/prompt_{nxt}.yaml (revisi kriteria) dan (opsional) prompts/fewshot_{nxt}.json\n"
          f'  few-shot: [{{"user_id": "..."}}, ...] hanya akun tuning; jawabannya diambil dari label manual;\n'
          f"  rujuk dari prompt_{nxt}.yaml dengan  fewshot_ref: fewshot_{nxt}.json\n"
          f"Lalu: python -m annotation a2 --version {nxt}")
    return str(out)
