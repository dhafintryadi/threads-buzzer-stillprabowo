"""`annotation status` -- tahap saat ini, prasyarat yang belum terpenuhi, dan perintah berikutnya."""

from __future__ import annotations

from . import llm
from .a2_eval_prompt import read_rounds
from .common import AnnotationError, is_mock, paths, read_clean_data, read_json
from .metrics import decide

TBD_KEYS = ["guideline.sha256"]


def _tbd(cfg: dict) -> list[str]:
    out = []
    for key in TBD_KEYS:
        node = cfg
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            out.append(key)
    return out


def current(cfg: dict) -> tuple[str, str]:
    """> (tahap, perintah/aksi berikutnya)."""
    p = paths(cfg)
    if not p.subset.exists():
        return "A0/A1", "python -m annotation a0   lalu   python -m annotation a1"
    if not p.manual_subset.exists():
        return "GATE 1", "labeli subset (Label Studio atau CSV), lalu: python -m annotation a1b --labels <berkas>"
    if not p.frozen.exists():
        rounds = read_rounds(cfg)
        if not len(rounds):
            return "GATE 2", "isi prompts/prompt_v1.yaml, lalu: python -m annotation a2 --version v1"
        d = decide(rounds, cfg["optimization"]["recall_threshold"], cfg["optimization"]["max_optimizations"],
                   cfg["optimization"]["freeze_on_limit"])
        if d["action"] == "freeze":
            return "GATE 2 (split berubah)", (f"{d['reason']} pada split baru, belum dibekukan. "
                                              "Evaluasi versi berikutnya: python -m annotation a2 --version vN")
        return "GATE 2 (optimasi)", f"{d['reason']}. python -m annotation a2b, tulis versi berikutnya, lalu a2 --version vN"
    frozen = read_json(p.frozen)
    clean, _ = read_clean_data(cfg)
    done = llm.ok_labels(cfg, frozen["prompt_sha256"], "full")
    if len(set(done.user_id) & set(clean.user_id)) < len(clean):
        return "A3", f"{len(done)}/{len(clean)} akun berlabel. python -m annotation a3"
    if not p.review_tasks.exists():
        return "A4", "python -m annotation a4"
    if not p.review_labels.exists():
        return "GATE 3", "tinjau review_tasks.json di Label Studio, lalu: python -m annotation a4b --export <ekspor.json>"
    if not p.labeled.exists():
        return "A5", "python -m annotation a5"
    return "SELESAI", f"{p.labeled} sudah ditulis"


def run(cfg: dict) -> None:
    try:
        stage, nxt = current(cfg)
    except AnnotationError as e:
        stage, nxt = "TERHAMBAT", str(e)
    if is_mock():
        print("MODE TIRUAN (ANNOTATION_MOCK=1): membaca/menulis state_mock/ dan out_mock/, bukan state/.")
    print(f"Tahap   : {stage}\nBerikut : {nxt}")
    tbd = _tbd(cfg)
    if tbd:
        print("Config yang masih TBD: " + ", ".join(tbd))
    if paths(cfg).frozen.exists():
        f = read_json(paths(cfg).frozen)
        print(f"Prompt beku: {f['prompt_version']} (ambang tercapai: {f['threshold_met']})")
