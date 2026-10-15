"""CLI: `python -m annotation <perintah>` dari folder code/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (a0_validate_input, a1_sample_subset, a1b_import_and_split, a2_eval_prompt, a2b_fewshot_candidates,
               a3_annotate_full, a4_export_review, a4b_import_review, a5_finalize, demo, probe, status)
from .common import AnnotationError, load_config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m annotation", description="Pipeline anotasi Human-LLM")
    ap.add_argument("--base", type=Path, default=None, help="folder berisi config.yaml (default: folder paket)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="tahap saat ini dan perintah berikutnya")
    sub.add_parser("a0", help="validasi input + estimasi token")
    sub.add_parser("a1", help="ambil subset manual ±10%%")
    s = sub.add_parser("a1b", help="impor label manual + bagi tuning/validation")
    s.add_argument("--labels", type=Path, required=True, help="ekspor Label Studio (.json) atau subset CSV")
    s.add_argument("--annotator", default=None, help="annotator_id bila CSV tidak mengisinya")
    s = sub.add_parser("a2", help="evaluasi satu versi prompt")
    s.add_argument("--version", required=True, help="mis. v1 -> prompts/prompt_v1.yaml")
    s = sub.add_parser("move-to-tuning", help="[keputusan peneliti] pindahkan akun validation ke tuning (dicatat)")
    s.add_argument("--user-id", nargs="+", required=True)
    s.add_argument("--reason", required=True)
    sub.add_parser("a2b", help="kandidat few-shot dari ronde terakhir")
    sub.add_parser("a3", help="label seluruh akun dengan prompt beku")
    sub.add_parser("a4", help="ekspor akun buzzer-LLM untuk ditinjau")
    s = sub.add_parser("a4b", help="impor hasil tinjauan")
    s.add_argument("--export", type=Path, required=True)
    sub.add_parser("a5", help="label akhir + laporan")
    s = sub.add_parser("demo", help="buat tugas demo pelabelan (di luar subset resmi; tanpa membekukan apa pun)")
    s.add_argument("--n", type=int, default=12)
    s = sub.add_parser("demo-check", help="periksa ekspor demo (Tabel 4, tidak memblokir)")
    s.add_argument("--export", type=Path, default=Path("annotation/exports/demo.json"))
    sub.add_parser("probe", help="uji parameter API yang diterima model (temperature, top_p, reasoning_effort)")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.base)
        {"status": lambda: status.run(cfg),
         "a0": lambda: a0_validate_input.run(cfg),
         "a1": lambda: a1_sample_subset.run(cfg),
         "a1b": lambda: a1b_import_and_split.run(cfg, args.labels, args.annotator),
         "a2": lambda: a2_eval_prompt.run(cfg, args.version),
         "move-to-tuning": lambda: a1b_import_and_split.move_to_tuning(cfg, args.user_id, args.reason),
         "a2b": lambda: a2b_fewshot_candidates.run(cfg),
         "a3": lambda: a3_annotate_full.run(cfg),
         "a4": lambda: a4_export_review.run(cfg),
         "a4b": lambda: a4b_import_review.run(cfg, args.export),
         "a5": lambda: a5_finalize.run(cfg),
         "demo": lambda: demo.build(cfg, args.n),
         "demo-check": lambda: print(demo.check(cfg, args.export).to_string(index=False)),
         "probe": lambda: probe.run(cfg)}[args.cmd]()
    except AnnotationError as e:
        print(f"BERHENTI: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
