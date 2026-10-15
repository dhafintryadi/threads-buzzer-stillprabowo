"""Hal bersama: config, path, baca data, hash, manifest, Label Studio."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import yaml

from .labels import FIELDS, IP_FIELDS, IP_VALUES, KU_VALUES, LABELS, POSITIVE, problems  # noqa: F401 (diekspor ulang)

PKG_DIR = Path(__file__).resolve().parent
FORBIDDEN_PROMPT_COLUMNS = {"user_id"}


class AnnotationError(Exception):
    """Prasyarat belum terpenuhi atau invarian dilanggar."""


def load_config(base_dir: Path | str | None = None) -> dict:
    base = Path(base_dir) if base_dir else PKG_DIR
    with open(base / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_base"] = base
    cols = cfg["input"]["annotation_input_columns"]
    bad = FORBIDDEN_PROMPT_COLUMNS & set(cols)
    if bad:
        raise AnnotationError(f"annotation_input_columns tidak boleh memuat {sorted(bad)}.")
    if "caption_text" not in cols:
        raise AnnotationError("annotation_input_columns harus memuat caption_text.")
    if cfg["optimization"]["metric_class"] != POSITIVE or not cfg["llm"]["one_account_per_call"]:
        raise AnnotationError("Hanya metric_class=buzzer dan one_account_per_call=true yang didukung.")
    allowed = {"prompt.format": ["chen_two_message"], "prompt.eval_mode": ["simultaneous"],
               "output_schema.ip_when_ku_not_met": ["null", "filled"], "rules.label_policy": ["llm", "derived"],
               "rules.manual_rule_check": ["block", "derive"], "prompt.render_format": ["markdown", "json"],
               "prompt.layout": ["static_system", "chen"], "optimization.freeze_on_limit": ["best_validation", "last"],
               "final_label.manual_subset_overrides": [True]}
    for key, values in allowed.items():
        section, name = key.split(".")
        if cfg[section][name] not in values:
            raise AnnotationError(f"config `{key}` = {cfg[section][name]!r}; nilai yang didukung: {values}")
    if not (isinstance(cfg["optimization"]["eval_repeats"], int) and cfg["optimization"]["eval_repeats"] >= 1):
        raise AnnotationError("config `optimization.eval_repeats` harus bilangan bulat >= 1.")
    return cfg


def is_mock() -> bool:
    """Mode tiruan (ANNOTATION_MOCK=1): semua tulisan dialihkan ke state_mock/ dan out_mock/."""
    return os.getenv("ANNOTATION_MOCK") == "1"


def require(cfg: dict, dotted: str):
    node = cfg
    for key in dotted.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    if node is None:
        raise AnnotationError(f"config `{dotted}` belum diisi. Isi di config.yaml.")
    return node


def paths(cfg: dict) -> SimpleNamespace:
    base = cfg["_base"]
    suffix = "_mock" if is_mock() else ""
    state, out = base / f"state{suffix}", base / f"{cfg['output']['dir']}{suffix}"
    return SimpleNamespace(
        clean_data=(base / cfg["input"]["clean_data_path"]).resolve(),
        guideline=(base / cfg["guideline"]["path"]).resolve(),
        rules=(base / cfg["rules"]["path"]).resolve(),
        frozen_inputs=state / "frozen_inputs.json",
        prompts=base / "prompts", state=state, out=out,
        subset=state / "subset_for_manual_labeling.csv",
        manual_tasks=state / "manual_tasks.json",
        ls_config_manual=state / "label_studio_config_gate1.xml",
        ls_config_review=state / "label_studio_config_gate3.xml",
        manual_subset=state / "manual_subset.csv",
        split_moves=state / "split_moves.csv",
        llm_calls=state / "llm_calls.jsonl",
        llm_calls_check=state / "llm_calls.checkpoint.json",
        eval_rounds=state / "eval_rounds.csv",
        frozen=state / "frozen_prompt.json",
        review_tasks=state / "review_tasks.json",
        review_labels=state / "review_labels.csv",
        labeled=out / "clean_data_labeled.csv",
        report_json=out / "annotation_report.json",
        report_md=out / "annotation_report.md",
        manifest=out / "run_manifest.json",
    )


def read_clean_data(cfg: dict) -> tuple[pd.DataFrame, list[str]]:
    """Baca + validasi kontrak input."""
    p = paths(cfg).clean_data
    if not p.exists():
        raise AnnotationError(f"clean_data.csv tidak ditemukan: {p}")
    df = pd.read_csv(p, dtype={"user_id": str, "caption_text": str}, keep_default_na=False, encoding="utf-8")
    contract = cfg["input"]["contract_columns"]
    missing = [c for c in contract + cfg["input"]["annotation_input_columns"] if c not in df.columns]
    if missing:
        raise AnnotationError(f"Kolom hilang di clean_data.csv: {sorted(set(missing))}. Kolom yang ada: {list(df.columns)}")
    extra = [c for c in df.columns if c not in contract]
    if (df.user_id == "").any() or not df.user_id.is_unique:
        raise AnnotationError("user_id harus terisi dan unik.")
    if df.duplicated().any():
        raise AnnotationError(f"{int(df.duplicated().sum())} baris ganda di clean_data.csv.")
    warnings = [f"kolom di luar kontrak (diabaikan): {extra}"] if extra else []
    n_empty = int((df.caption_text.str.strip() == "").sum())
    if n_empty:
        warnings.append(f"{n_empty} akun dengan caption_text kosong.")
    return df, warnings


def read_csv_str(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def refuse_overwrite(path: Path, what: str) -> None:
    if path.exists():
        raise AnnotationError(f"{path.name} sudah ada ({what} dibekukan). Hapus manual jika memang ingin mengulang.")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def check_guideline(cfg: dict, freeze: bool = False) -> str:
    """Invarian I8: pedoman sudah dibekukan (hash diisi peneliti di config, tidak pernah otomatis) dan tidak berubah."""
    p = paths(cfg)
    actual = sha256_file(p.guideline)
    if actual is None:
        raise AnnotationError(f"Pedoman anotasi tidak ditemukan: {p.guideline}")
    frozen = cfg["guideline"]["sha256"]
    if frozen is None:
        raise AnnotationError(f"Pedoman belum dibekukan. Setelah versinya final, isi config guideline.sha256: {actual}")
    if actual != frozen:
        raise AnnotationError(f"I8: pedoman berubah sejak dibekukan ({actual[:12]} != {frozen[:12]}). "
                              f"Kembalikan isinya; pedoman tidak boleh diubah setelah GATE 1.")
    rules_sha = sha256_file(p.rules)
    if freeze:
        write_json(p.frozen_inputs, {"guideline_sha256": actual, "rules_sha256": rules_sha, "frozen_at": now_utc()})
    elif p.frozen_inputs.exists() and read_json(p.frozen_inputs)["rules_sha256"] != rules_sha:
        raise AnnotationError(f"I8: {p.rules.name} berubah sejak GATE 1 (dibekukan di {p.frozen_inputs.name}). "
                              f"Kembalikan isinya; Tabel 4 tidak boleh diubah setelah GATE 1.")
    return actual


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_manifest(cfg: dict, stage: str, inputs: list[Path], outputs: list[Path], extra: dict | None = None) -> None:
    """run_manifest.json: daftar append-only, satu entri per pemanggilan tahap."""
    p = paths(cfg).manifest
    data = read_json(p) if p.exists() else []
    libs = {"python": platform.python_version()}
    for lib in ("pandas", "PyYAML", "openai", "tiktoken"):
        try:
            libs[lib] = metadata.version(lib)
        except metadata.PackageNotFoundError:
            libs[lib] = None
    data.append({
        "stage": stage, "timestamp_utc": now_utc(),
        "inputs": {str(x): sha256_file(x) for x in inputs},
        "outputs": {str(x): sha256_file(x) for x in outputs},
        "config_sha256": sha256_file(cfg["_base"] / "config.yaml"),
        "guideline": {"path": str(paths(cfg).guideline), "sha256": sha256_file(paths(cfg).guideline)},
        "rules": {"path": str(paths(cfg).rules), "sha256": sha256_file(paths(cfg).rules)},
        "mock": is_mock(),
        "library_versions": libs, "extra": extra or {},
    })
    write_json(p, data)


IP_TITLES = {"ip1": "IP1 keseragaman isi", "ip2": "IP2 minimnya opini personal",
             "ip3": "IP3 aktivitas bertopik berulang", "ip4": "IP4 serangan/stigmatisasi terarah"}


def _choices(name: str, title: str, values, required: bool) -> str:
    opts = "".join(f'<Choice value="{v}"/>' for v in values)
    return (f'  <Header value="{title}"/>\n'
            f'  <Choices name="{name}" toName="caption" choice="single-radio" required="{str(required).lower()}" '
            f'showInline="true">{opts}</Choices>\n')


def label_studio_config(cfg: dict, with_ku_ip: bool) -> str:
    """Template GATE 1 dan GATE 3 (sama bila review.fill_ku_ip): KU, IP1-IP4, label."""
    ip_required = cfg["output_schema"]["ip_when_ku_not_met"] == "filled"
    parts = ['<View>\n  <Text name="meta" value="$meta_block"/>\n  <Text name="caption" value="$caption_text"/>\n']
    if with_ku_ip:
        parts.append(_choices("ku", "KU kriteria utama", KU_VALUES, True))
        parts += [_choices(f, IP_TITLES[f], IP_VALUES, ip_required) for f in IP_FIELDS]
    parts.append(_choices("label", "Label", LABELS, True))
    return "".join(parts) + "</View>\n"


def ls_task(row, cfg: dict, prediction: dict | None = None, model_version: str = "", hidden: dict | None = None) -> dict:
    """Tugas Label Studio."""
    meta_cols = [c for c in cfg["input"]["annotation_input_columns"] if c != "caption_text"]
    task = {"data": {"user_id": row["user_id"],
                     "meta_block": " | ".join(f"{c}={row[c]}" for c in meta_cols),
                     "caption_text": row["caption_text"], **(hidden or {})}}
    if prediction:
        task["predictions"] = [{"model_version": model_version, "result": [
            {"from_name": f, "to_name": "caption", "type": "choices", "value": {"choices": [v]}}
            for f, v in prediction.items()]}]
    return task


def read_export_json(path: Path) -> list:
    """Ekspor JSON Label Studio (daftar tugas), dengan pesan jelas bila berkas belum ada atau formatnya salah."""
    path = Path(path)
    if not path.exists():
        raise AnnotationError(f"Berkas ekspor belum ada: {path}. Ekspor dari Label Studio (Export -> JSON) ke lokasi ini.")
    try:
        data = read_json(path)
    except json.JSONDecodeError as e:
        raise AnnotationError(f"{path.name} bukan JSON yang valid ({e}). Ekspor ulang dengan format JSON.") from e
    if not isinstance(data, list):
        raise AnnotationError(f"{path.name} bukan ekspor JSON Label Studio (harus daftar tugas; JSON-MIN/CSV tidak didukung).")
    return data


def read_ls_export(path: Path, expected_ids: set[str], cfg: dict, with_ku_ip: bool = True) -> pd.DataFrame:
    """Baca ekspor JSON Label Studio secara ketat: tepat satu anotasi per tugas, nilai dalam enum."""
    rows, errs = [], []
    for t in read_export_json(path):
        uid = str(t.get("data", {}).get("user_id", ""))
        anns = t.get("annotations", [])
        if not anns:
            errs.append(f"{uid}: belum dianotasi"); continue
        if len(anns) > 1:
            errs.append(f"{uid}: {len(anns)} anotasi (harus tepat satu)"); continue
        a = anns[0]
        if a.get("was_cancelled"):
            errs.append(f"{uid}: anotasi dibatalkan"); continue
        rec = {f: "" for f in FIELDS}
        for r in a.get("result", []):
            ch = r.get("value", {}).get("choices") or []
            if r.get("from_name") in FIELDS:
                rec[r["from_name"]] = ch[0] if len(ch) == 1 else "<lebih dari satu pilihan>"
        bad = problems(rec, cfg["output_schema"]["ip_when_ku_not_met"], with_ku_ip)
        if bad:
            errs.append(f"{uid}: " + "; ".join(bad)); continue
        cb = a.get("completed_by")
        rows.append({"user_id": uid, **rec,
                     "annotator_id": str(cb.get("email") or cb.get("id")) if isinstance(cb, dict) else str(cb),
                     "labeled_at": a.get("updated_at") or a.get("created_at") or ""})
    df = pd.DataFrame(rows, columns=["user_id", *FIELDS, "annotator_id", "labeled_at"])
    errs += [f"{u}: muncul di lebih dari satu tugas" for u in sorted(set(df.user_id[df.user_id.duplicated()]))]
    rejected = {e.split(":")[0] for e in errs}
    errs += [f"{u}: tidak ada di ekspor" for u in sorted(expected_ids - set(df.user_id) - rejected)]
    errs += [f"{u}: bukan akun yang diharapkan" for u in sorted(set(df.user_id) - expected_ids)]
    if errs:
        raise AnnotationError(f"Ekspor Label Studio ditolak ({len(errs)} masalah):\n  " + "\n  ".join(errs[:20]))
    return df.sort_values("user_id").reset_index(drop=True)
