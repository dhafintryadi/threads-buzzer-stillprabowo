"""A3 -- label SELURUH akun dengan prompt beku."""

from __future__ import annotations

from . import llm
from .common import AnnotationError, add_manifest, check_guideline, paths, read_clean_data, read_csv_str, read_json


def frozen_prompt(cfg: dict, clean) -> tuple[dict, object]:
    """(frozen_prompt.json, prompt) + cek I3: hash render prompt (termasuk few-shot) sama dengan saat dibekukan."""
    p = paths(cfg)
    check_guideline(cfg)
    if not p.frozen.exists():
        raise AnnotationError("Prompt belum dibekukan. Selesaikan loop optimasi: python -m annotation a2 --version vN")
    frozen = read_json(p.frozen)
    prompt = llm.load_prompt(cfg, frozen["prompt_version"], clean)
    sha = prompt.sha256
    if sha != frozen["prompt_sha256"]:
        raise AnnotationError(f"I3: berkas prompt {frozen['prompt_version']} berubah sejak dibekukan "
                              f"({sha[:12]} != {frozen['prompt_sha256'][:12]}). Kembalikan isinya; bila prompt itu tidak "
                              f"menulis render_format/layout sendiri, periksa juga prompt.render_format dan prompt.layout di config.")
    return frozen, prompt


def run(cfg: dict) -> dict:
    p = paths(cfg)
    clean, _ = read_clean_data(cfg)
    frozen, prompt = frozen_prompt(cfg, clean)
    llm.check_independence(prompt, read_csv_str(p.manual_subset), clean.set_index("user_id"))
    res = llm.annotate(cfg, clean, sorted(clean.user_id), frozen["prompt_version"], "full")
    done = llm.ok_labels(cfg, frozen["prompt_sha256"], "full")
    print(f"{len(done)}/{len(clean)} akun berlabel (dilewati karena sudah ada: {res['skipped']}, dipanggil: {res['called']}).")
    if len(done):
        print("Pemeriksaan aturan:", llm.rule_summary(done))
    if res["failed"]:
        print(f"{len(res['failed'])} akun gagal (tidak diberi label default). Jalankan ulang a3 untuk mencoba lagi: "
              f"{res['failed'][:10]}")
    else:
        print("Lanjut: python -m annotation a4")
    add_manifest(cfg, "a3_annotate_full", [p.clean_data, p.frozen], [p.llm_calls],
                 {"prompt_version": frozen["prompt_version"], "labeled": len(done), "failed": res["failed"],
                  "model_snapshot": sorted(set(done.model_snapshot))})
    return res
