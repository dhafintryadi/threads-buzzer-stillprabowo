"""A5 -- label akhir (fungsi murni) + laporan anotasi."""

from __future__ import annotations

import json

import pandas as pd

from . import llm
from .a2_eval_prompt import read_rounds
from .a3_annotate_full import frozen_prompt
from .a4_export_review import llm_full_labels
from .common import LABELS, POSITIVE, AnnotationError, add_manifest, paths, read_clean_data, read_csv_str, write_csv, write_json
from .metrics import threshold_note

SOURCES = ("manual_subset", "llm_positive_reviewed", "llm_negative_unreviewed")


def finalize(clean: pd.DataFrame, llm_labels: pd.DataFrame, review: pd.DataFrame, manual: pd.DataFrame,
             frozen: dict) -> pd.DataFrame:
    """Fungsi murni: input yang sama -> output identik."""
    df = clean.merge(llm_labels[["user_id", "label"]].rename(columns={"label": "llm_label"}), on="user_id", how="left")
    if df.llm_label.isna().any():
        raise AnnotationError(f"I5: {int(df.llm_label.isna().sum())} akun tanpa label LLM.")
    gold = manual.set_index("user_id").manual_label
    rv = review.set_index("user_id")
    in_subset = df.user_id.isin(gold.index)
    if set(rv.index) & set(gold.index):
        raise AnnotationError(f"I9: review_labels.csv memuat akun subset: {sorted(set(rv.index) & set(gold.index))[:5]}")
    need_review = set(df.user_id[~in_subset & (df.llm_label == POSITIVE)])
    if set(rv.index) != need_review:
        raise AnnotationError(f"I4: tinjauan tidak cocok dengan akun buzzer-LLM non-subset "
                              f"(kurang {sorted(need_review - set(rv.index))[:5]}, lebih {sorted(set(rv.index) - need_review)[:5]}).")
    reviewed = df.user_id.isin(need_review)
    final = df.llm_label.where(~reviewed, df.user_id.map(rv.review_label))
    final = final.where(~in_subset, df.user_id.map(gold))
    source = pd.Series("llm_negative_unreviewed", index=df.index)
    source[reviewed], source[in_subset] = "llm_positive_reviewed", "manual_subset"
    changed = df.user_id.map(rv.review_changed_label.map({"True": True, "False": False, True: True, False: False}))

    out = clean.copy()
    out["label"] = (final == POSITIVE).astype(int)
    out["label_source"] = source
    out["final_prompt_version"] = frozen["prompt_version"]
    out["review_changed_label"] = changed.where(reviewed).astype("boolean")
    out = out.sort_values("user_id").reset_index(drop=True)
    assert len(out) == len(clean) and set(out.user_id) == set(clean.user_id) and out.user_id.is_unique
    assert out.label.isin([0, 1]).all() and out.label_source.isin(SOURCES).all()
    return out


def subset_confusion(manual: pd.DataFrame, llm_labels: pd.DataFrame) -> dict:
    """Label LLM (prompt beku, anotasi penuh) vs label manual pada subset, per set."""
    m = manual.merge(llm_labels[["user_id", "label"]], on="user_id")
    out = {}
    for s in ("tuning", "validation"):
        part = m[m.split == s]
        tab = pd.crosstab(part.manual_label, part.label).reindex(index=list(LABELS), columns=list(LABELS), fill_value=0)
        out[s] = {f"manual_{a}/llm_{b}": int(tab.loc[a, b]) for a in LABELS for b in LABELS}
    return out


def build_report(out: pd.DataFrame, manual: pd.DataFrame, rounds: pd.DataFrame, frozen: dict,
                 llm_labels: pd.DataFrame, flags: dict, threshold: float, usage: pd.DataFrame) -> dict:
    reviewed = out[out.label_source == "llm_positive_reviewed"]
    n_changed = int(reviewed.review_changed_label.sum())
    val_pos = int(((manual.split == "validation") & (manual.manual_label == POSITIVE)).sum())
    return {
        "n_accounts": len(out),
        "final_buzzer": int(out.label.sum()), "final_buzzer_proportion": round(float(out.label.mean()), 4),
        "label_source_counts": {s: int((out.label_source == s).sum()) for s in SOURCES},
        "llm_buzzer_non_subset_reviewed": len(reviewed),
        "review_corrections": n_changed,
        "review_correction_rate": round(n_changed / len(reviewed), 4) if len(reviewed) else None,
        "subset_confusion_llm_vs_manual": subset_confusion(manual, llm_labels),
        "validation_threshold_note": threshold_note(val_pos, threshold),
        "frozen_prompt": {k: frozen[k] for k in ("prompt_version", "prompt_sha256", "threshold_met", "recall_validation", "reason")},
        "eval_rounds": json.loads(rounds.to_json(orient="records")),
        "rule_inconsistent": int(llm_labels.rule_inconsistent.eq(True).sum()),
        "ip3_mismatch": int(llm_labels.ip3_mismatch.eq(True).sum()),
        "flags": flags,
        "usage_per_stage": json.loads(usage.round(2).to_json(orient="index")),
        "model_snapshots": sorted(set(llm_labels.model_snapshot)),
    }


def report_markdown(r: dict) -> str:
    rows = "\n".join(f"| {x['round']} | {x.get('repeat', 1)} | {x['prompt_version']} | {x['set']} | {x['positives']} | "
                     f"{x['tp']} | {'-' if x['recall'] is None else format(float(x['recall']), '.3f')} |"
                     for x in r["eval_rounds"])
    conf = "\n".join(f"| {s} | " + " | ".join(str(v) for v in c.values()) + " |"
                     for s, c in r["subset_confusion_llm_vs_manual"].items())
    rate = "-" if r["review_correction_rate"] is None else f"{r['review_correction_rate']:.1%}"
    fmt = lambda v, d=0: "-" if v is None else f"{v:,.{d}f}"  # noqa: E731
    usage_rows = [f"| {st} | {fmt(u['panggilan'])} | {fmt(u['prompt_tokens'])} | {fmt(u['cached_tokens'])} | "
                  f"{fmt(u['cached_pct'], 1)} | {fmt(u['completion_tokens'])} | {fmt(u['reasoning_rata2'], 1)} |"
                  for st, u in r["usage_per_stage"].items()]
    usage_md = "\n".join(["| Tahap | Panggilan | Prompt | Cached | Cached % | Completion | Reasoning rata-rata |",
                          "|---|---|---|---|---|---|---|", *usage_rows])
    return f"""# Laporan anotasi

- Akun: {r['n_accounts']}; label akhir buzzer: {r['final_buzzer']} ({r['final_buzzer_proportion']:.1%})
- Sumber label: {r['label_source_counts']}
- Akun buzzer-LLM non-subset (semua ditinjau): {r['llm_buzzer_non_subset_reviewed']}; dikoreksi: {r['review_corrections']} (laju koreksi {rate})
- Prompt beku: {r['frozen_prompt']['prompt_version']} (ambang tercapai: {r['frozen_prompt']['threshold_met']}) -- {r['frozen_prompt']['reason']}
- Ambang pada validation: {r['validation_threshold_note']}
- Label LLM tidak sesuai Tabel 4 (anotasi penuh): {r['rule_inconsistent']}; IP3 LLM != IP3 kolom: {r['ip3_mismatch']}
- Flag: {r['flags']}
- Model: {', '.join(r['model_snapshots'])}

## Subset: label LLM (prompt beku) vs label manual

Tuning set bersifat in-sample (dipakai menyusun prompt); validation set tidak.

| Set | manual buzzer / LLM buzzer | manual buzzer / LLM non_buzzer | manual non_buzzer / LLM buzzer | manual non_buzzer / LLM non_buzzer |
|---|---|---|---|---|
{conf}

## Penggunaan token per tahap (dari respons API)

{usage_md}

## Semua ronde evaluasi

| Ronde | Pengulangan | Versi | Set | Buzzer | TP | Recall |
|---|---|---|---|---|---|---|
{rows}

Laporan ini bukan pengganti cek distribusi kelas (langkah 5).
"""


def run(cfg: dict) -> pd.DataFrame:
    p = paths(cfg)
    clean, _ = read_clean_data(cfg)
    frozen, _ = frozen_prompt(cfg, clean)
    llm.assert_no_mock(cfg)
    labels = llm_full_labels(cfg, frozen, clean)
    if not p.review_labels.exists():
        raise AnnotationError("review_labels.csv belum ada. Selesaikan GATE 3 lalu: python -m annotation a4b --export ...")
    review, manual = read_csv_str(p.review_labels), read_csv_str(p.manual_subset)
    out = finalize(clean, labels, review, manual, frozen)
    write_csv(out, p.labeled)
    flags = {k: cfg[s][k] for s, k in [("prompt", "layout"), ("prompt", "render_format"), ("rules", "label_policy"), ("rules", "ip3_from_columns"), ("rules", "manual_rule_check"),
                                       ("output_schema", "ip_when_ku_not_met"), ("review", "fill_ku_ip"),
                                       ("optimization", "freeze_on_limit"), ("optimization", "eval_repeats"),
                                       ("final_label", "manual_subset_overrides")]}
    report = build_report(out, manual, read_rounds(cfg), frozen, labels, flags, cfg["optimization"]["recall_threshold"],
                          llm.usage_summary(llm.read_calls(cfg)))
    write_json(p.report_json, report)
    p.report_md.write_text(report_markdown(report), encoding="utf-8")
    add_manifest(cfg, "a5_finalize", [p.clean_data, p.llm_calls, p.review_labels, p.manual_subset, p.frozen],
                 [p.labeled, p.report_json, p.report_md], {"label_source_counts": report["label_source_counts"]})
    print(report_markdown(report))
    print("Ditulis:", p.labeled)
    return out
