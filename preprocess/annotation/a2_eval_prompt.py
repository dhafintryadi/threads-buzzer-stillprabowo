"""A2 -- evaluasi satu versi prompt pada tuning + validation, lalu putuskan lanjut/bekukan."""

from __future__ import annotations

import pandas as pd

from . import llm
from .common import POSITIVE, AnnotationError, add_manifest, check_guideline, now_utc, paths, read_clean_data, read_csv_str, read_json, write_csv, write_json
from .metrics import decide, set_metrics, threshold_note

ROUND_COLUMNS = ["round", "repeat", "prompt_version", "prompt_sha256", "render_format", "layout", "set", "n", "positives", "tp", "fp", "fn", "tn",
                 "recall", "recall_ci_low", "recall_ci_high", "precision", "f1", "rule_inconsistent", "ip3_mismatch",
                 "label_policy", "model_snapshot", "evaluated_at"]


def read_rounds(cfg: dict) -> pd.DataFrame:
    p = paths(cfg).eval_rounds
    return pd.read_csv(p, dtype={"prompt_version": str, "prompt_sha256": str}) if p.exists() else pd.DataFrame(columns=ROUND_COLUMNS)


def score(cfg: dict, manual: pd.DataFrame, rnd: int, rep: int, version: str, sha: str, render_format: str,
          layout: str) -> list[dict]:
    """Baris eval_rounds (tuning + validation) untuk satu versi, dari label LLM di llm_calls dan split di `manual`."""
    ev = manual.merge(llm.ok_labels(cfg, sha, "eval", rep), on="user_id", how="left")
    rows = []
    for s in ("tuning", "validation"):
        part = ev[ev.split == s]
        rows.append({"round": rnd, "repeat": rep, "prompt_version": version, "prompt_sha256": sha,
                     "render_format": render_format, "layout": layout, "set": s,
                     **set_metrics(part.manual_label, part.label),
                     "rule_inconsistent": int(part.rule_inconsistent.eq(True).sum()),
                     "ip3_mismatch": int(part.ip3_mismatch.eq(True).sum()),
                     "label_policy": cfg["rules"]["label_policy"],
                     "model_snapshot": ";".join(sorted(set(part.model_snapshot.dropna()))), "evaluated_at": now_utc()})
    return rows


def run(cfg: dict, version: str) -> dict:
    p = paths(cfg)
    check_guideline(cfg)
    if p.frozen.exists():
        raise AnnotationError(f"Prompt sudah dibekukan ({read_json(p.frozen)['prompt_version']}). Lanjut: python -m annotation a3")
    if not p.manual_subset.exists():
        raise AnnotationError("manual_subset.csv belum ada. Selesaikan GATE 1 lalu: python -m annotation a1b --labels ...")
    clean, _ = read_clean_data(cfg)
    manual = read_csv_str(p.manual_subset)
    threshold = cfg["optimization"]["recall_threshold"]
    val_pos = int(((manual.split == "validation") & (manual.manual_label == POSITIVE)).sum())
    if val_pos == 0:
        raise AnnotationError("Validation set tidak memuat akun buzzer: recall tidak terdefinisi; kriteria berhenti "
                              "tidak dapat dievaluasi.")
    prompt = llm.load_prompt(cfg, version, clean)
    sha = prompt.sha256
    rounds = read_rounds(cfg)
    if version in set(rounds.prompt_version):
        old = rounds[rounds.prompt_version == version].prompt_sha256.iloc[0]
        raise AnnotationError(f"{version} sudah dievaluasi." if old == sha else
                              f"Berkas {version} berubah sejak dievaluasi. Simpan revisi sebagai versi baru.")
    llm.check_independence(prompt, manual, clean.set_index("user_id"))
    if prompt.rule_warning:
        print("PERINGATAN:", prompt.rule_warning)

    repeats = cfg["optimization"]["eval_repeats"]
    for rep in range(1, repeats + 1):
        res = llm.annotate(cfg, clean, sorted(manual.user_id), version, "eval", repeat=rep)
        if res["failed"]:
            raise AnnotationError(f"{len(res['failed'])} akun gagal dilabeli (pengulangan {rep}; lihat llm_calls.jsonl). "
                                  f"Jalankan ulang `a2 --version {version}` untuk mencoba lagi.")

    rnd = int(rounds["round"].max()) + 1 if len(rounds) else 1
    new = []
    for rep in range(1, repeats + 1):
        new += score(cfg, manual, rnd, rep, version, sha, prompt.render_format, prompt.layout)
        if rep == 1:
            print("Pemeriksaan aturan:", llm.rule_summary(llm.ok_labels(cfg, sha, "eval", rep)))
    new = pd.DataFrame(new)
    rounds = (new if rounds.empty else pd.concat([rounds, new], ignore_index=True))[ROUND_COLUMNS]
    write_csv(rounds, p.eval_rounds)

    for r in new.to_dict(orient="records"):
        print(f"pengulangan {r['repeat']} {r['set']:<10} n={r['n']:<3} buzzer={r['positives']:<3} recall={r['recall']:.3f} "
              f"(95% CI {r['recall_ci_low']:.2f}-{r['recall_ci_high']:.2f}) precision={r['precision']:.3f} "
              f"| TP {r['tp']} FN {r['fn']} FP {r['fp']} TN {r['tn']}")
    print("Ambang:", threshold_note(val_pos, threshold), "| keputusan memakai pengulangan 1.")
    d = decide(rounds, threshold, cfg["optimization"]["max_optimizations"], cfg["optimization"]["freeze_on_limit"])
    print("Keputusan:", d["reason"])
    if d["action"] == "freeze":
        llm.assert_no_mock(cfg)
        write_json(p.frozen, {k: d[k] for k in ("prompt_version", "prompt_sha256", "threshold_met", "recall_validation", "reason")}
                   | {"split_moves": len(read_csv_str(p.split_moves)) if p.split_moves.exists() else 0,
                      "frozen_at": now_utc()})
        print(f"Prompt {d['prompt_version']} DIBEKUKAN. Berkasnya tidak boleh diubah lagi. Lanjut: python -m annotation a3")
    else:
        print("Lanjut optimasi: python -m annotation a2b, lalu tulis prompt versi berikutnya (GATE 2).")
    add_manifest(cfg, "a2_eval_prompt", [p.manual_subset, llm.prompt_path(cfg, version)],
                 [p.eval_rounds, p.llm_calls] + ([p.frozen] if d["action"] == "freeze" else []),
                 {"round": rnd, "prompt_version": version, "prompt_sha256": sha, "render_format": prompt.render_format,
                  "layout": prompt.layout, "usage": llm.usage_summary(llm.read_calls(cfg)).to_dict(orient="index"),
                  "eval_repeats": repeats, "decision": d})
    return d
