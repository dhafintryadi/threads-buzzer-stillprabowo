"""Prompt dua pesan, klien GPT-5 Mini, parser, dan log `llm_calls.jsonl` (append-only)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

import pandas as pd
import yaml

from .common import AnnotationError, now_utc, paths, read_csv_str, read_json, require, sha256_file, sha256_text, write_json
from .common import is_mock
from .labels import FIELDS, IP_FIELDS, derive_label, ip3_from_columns, json_schema, load_rules, nested, problems, rules_text

CRITERIA = ("ku", *IP_FIELDS)
PROMPT_KEYS = ("system", "instruction", "criteria", "decision_rule", "response_format", "options", "fewshot_ref")


def prompt_path(cfg: dict, version: str):
    return paths(cfg).prompts / f"prompt_{version}.yaml"


RENDER_FORMATS = ("markdown", "json")
LAYOUTS = ("static_system", "chen")


def account_data(row, cfg: dict) -> dict:
    """Data akun sesuai annotation_input_columns (tanpa user_id dan items_scanned); angka tetap angka."""
    return {c: (row[c].item() if hasattr(row[c], "item") else row[c]) for c in cfg["input"]["annotation_input_columns"]}


def _lines(data: dict) -> str:
    return "\n".join(f"{c}: {v}" for c, v in data.items())


def account_lines(row, cfg: dict) -> str:
    """Baris 'kolom: nilai' (format markdown)."""
    return _lines(account_data(row, cfg))


def _md_frozen_sections(prompt: SimpleNamespace) -> list[str]:
    """Bagian beku setelah instruksi: kriteria, aturan, contoh (bila ada), respons, opsi."""
    s = prompt.spec
    sections = ["# Kriteria\n" + "\n".join(f"- {k}: {str(s['criteria'][k]).strip()}" for k in CRITERIA),
                "# Aturan keputusan\n" + prompt.decision_rule]
    if prompt.fewshot_examples:
        sections.append("# Contoh\n" + "\n\n".join(
            f"Contoh {i}:\n{_lines(ex['data_akun'])}\nJawaban: {json.dumps(ex['jawaban'], ensure_ascii=False)}"
            for i, ex in enumerate(prompt.fewshot_examples, 1)))
    return sections + ["# Respons\n" + s["response_format"].strip(), "# Opsi\n" + s["options"].strip()]


def _json_frozen(prompt: SimpleNamespace) -> dict:
    s = prompt.spec
    out = {"instruksi": s["instruction"].strip(),
           "kriteria": {k: str(s["criteria"][k]).strip() for k in CRITERIA},
           "aturan_keputusan": prompt.decision_rule}
    if prompt.fewshot_examples:
        out["contoh"] = prompt.fewshot_examples
    return out | {"format_respons": s["response_format"].strip(), "opsi": s["options"].strip()}


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _render(row, prompt: SimpleNamespace, cfg: dict) -> tuple[str, str]:
    s, suffix = prompt.spec, cfg["prompt"]["answer_suffix"]
    if prompt.layout == "static_system":
        if prompt.render_format == "json":
            return (_dump({"peran": s["system"].strip(), **_json_frozen(prompt)}),
                    f"{_dump({'data_akun': account_data(row, cfg)})}\n\n{suffix}")
        system = "\n\n".join([s["system"].strip(), "# Instruksi\n" + s["instruction"].strip(), *_md_frozen_sections(prompt)])
        return system, f"# Data akun\n{account_lines(row, cfg)}\n\n{suffix}"
    if prompt.render_format == "json":
        return (_dump({"peran": s["system"].strip(), "data_akun": account_data(row, cfg)}),
                f"{_dump(_json_frozen(prompt))}\n\n{suffix}")
    system = f"{s['system'].strip()}\n\n# Data akun\n{account_lines(row, cfg)}"
    return system, "\n\n".join([s["instruction"].strip(), *_md_frozen_sections(prompt), suffix])


def render_messages(row, prompt: SimpleNamespace, cfg: dict) -> list[dict]:
    """Fungsi murni: akun + prompt -> [system, user]; pesan user selalu diakhiri ANSWER:."""
    system, user = _render(row, prompt, cfg)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def load_prompt(cfg: dict, version: str, clean: pd.DataFrame) -> SimpleNamespace:
    """prompt_vN.yaml + few-shot -> namespace."""
    path = prompt_path(cfg, version)
    if not path.exists():
        raise AnnotationError(f"Prompt {version} belum ada: {path} (GATE 2: peneliti menulis prompt).")
    raw = path.read_text(encoding="utf-8")
    spec = yaml.safe_load(raw) or {}
    missing = [k for k in PROMPT_KEYS if k not in spec] + [f"criteria.{c}" for c in CRITERIA if c not in (spec.get("criteria") or {})]
    if missing:
        raise AnnotationError(f"{path.name} kurang kunci: {missing}")
    fmt = spec.get("render_format") or cfg["prompt"]["render_format"]
    if fmt not in RENDER_FORMATS:
        raise AnnotationError(f"render_format {fmt!r} di {path.name}/config tidak didukung; pilih {RENDER_FORMATS}.")
    layout = spec.get("layout") or cfg["prompt"]["layout"]
    if layout not in LAYOUTS:
        raise AnnotationError(f"layout {layout!r} di {path.name}/config tidak didukung; pilih {LAYOUTS}.")
    fewshot = []
    if spec["fewshot_ref"]:
        fs_path = paths(cfg).prompts / spec["fewshot_ref"]
        if not fs_path.exists():
            raise AnnotationError(f"Berkas few-shot {fs_path} (fewshot_ref di {path.name}) tidak ada.")
        fewshot = [str(e["user_id"]) for e in read_json(fs_path)]
    by_id = clean.set_index("user_id", drop=False)
    examples = fewshot_examples(fewshot, by_id, read_csv_str(paths(cfg).manual_subset), cfg) if fewshot else []
    dr = str(spec["decision_rule"]).strip()
    rule_text = rules_text(load_rules(paths(cfg).rules))
    warning = None
    if "{{rules}}" in dr:
        dr = dr.replace("{{rules}}", rule_text)
    else:
        warning = (f"decision_rule di {path.name} ditulis manual dan tidak diperiksa terhadap rules.yaml. "
                   f"Pakai {{{{rules}}}} agar teks aturan dihasilkan dari rules.yaml, atau pastikan setara dengan:\n{rule_text}")
    prompt = SimpleNamespace(version=version, spec=spec, raw=raw, render_format=fmt, layout=layout, fewshot=fewshot,
                             fewshot_examples=examples, decision_rule=dr, rule_warning=warning, sha256=None)
    template_row = {c: "{" + c + "}" for c in cfg["input"]["annotation_input_columns"]}
    prompt.sha256 = sha256_text(json.dumps(render_messages(template_row, prompt, cfg), ensure_ascii=False))
    return prompt


def fewshot_examples(user_ids: list[str], clean_by_id: pd.DataFrame, manual: pd.DataFrame, cfg: dict) -> list[dict]:
    """Setiap contoh = {data_akun, jawaban}."""
    gold = manual.set_index("user_id")
    unknown = [u for u in user_ids if u not in gold.index]
    if unknown:
        raise AnnotationError(f"I2: contoh few-shot {unknown[:5]} harus akun tuning set (tidak ada di manual_subset).")
    null_ip = (cfg["output_schema"]["ip_when_ku_not_met"] == "null"
               and cfg["prompt"].get("fewshot_ip_when_ku_not_met", "null") == "null")
    out = []
    for uid in user_ids:
        rec = {f: gold.loc[uid, f"manual_{f}"] for f in (*CRITERIA, "label")}
        if null_ip and rec["ku"] == "tidak":
            rec |= dict.fromkeys(IP_FIELDS)
        out.append({"data_akun": account_data(clean_by_id.loc[uid], cfg), "jawaban": nested(rec)})
    return out


def check_independence(prompt: SimpleNamespace, manual: pd.DataFrame, clean_by_id: pd.DataFrame) -> None:
    """Invarian I2: tidak ada akun validation (ID atau teks) di prompt/few-shot; few-shot hanya dari tuning set."""
    tuning = set(manual.user_id[manual.split == "tuning"])
    val_ids = set(manual.user_id[manual.split == "validation"])
    for uid in prompt.fewshot:
        if uid in val_ids:
            raise AnnotationError(f"I2: contoh few-shot {uid} ada di validation set.")
        if uid not in tuning:
            raise AnnotationError(f"I2: contoh few-shot {uid} harus akun tuning set.")
    for uid in val_ids:
        caption = clean_by_id.loc[uid, "caption_text"].strip()
        if uid in prompt.raw or (len(caption) >= 30 and caption in prompt.raw):
            raise AnnotationError(f"I2: prompt memuat akun validation {uid} (ID atau teksnya).")
    norm = lambda t: " ".join(str(t).split()).lower()  # noqa: E731
    val_text = {norm(clean_by_id.loc[u, "caption_text"]): u for u in val_ids}
    for uid in prompt.fewshot:
        twin = val_text.get(norm(clean_by_id.loc[uid, "caption_text"]))
        if twin:
            raise AnnotationError(f"I2: teks contoh few-shot {uid} identik dengan akun validation {twin}; "
                                  f"ganti contoh ini agar validation set tetap independen.")


def _encoder():
    try:
        import tiktoken
        return tiktoken.get_encoding("o200k_base")
    except Exception:  # noqa: BLE001 -- tanpa tiktoken/offline: perkiraan 4 karakter per token
        return None


_ENC = _encoder()


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text)) if _ENC else math.ceil(len(text) / 4)


def check_length(row, cfg: dict) -> None:
    """truncation_policy: fail -- akun yang melewati batas menghentikan run, tidak dipotong."""
    limit = require(cfg, "llm.max_input_tokens")
    if require(cfg, "llm.truncation_policy") != "fail":
        raise AnnotationError("Hanya truncation_policy: fail yang didukung.")
    if count_tokens(row["caption_text"]) > limit:
        raise AnnotationError(f"caption_text akun {row['user_id']} > {limit} token (truncation_policy=fail).")


_client = None


def request_params(cfg: dict) -> dict:
    """Parameter yang benar-benar dikirim (temperature/top_p hanya bila tidak null)."""
    params = {"model": cfg["llm"]["model"],
              "response_format": {"type": "json_schema", "json_schema": json_schema(cfg["output_schema"]["ip_when_ku_not_met"])}}
    optional = ("temperature", "top_p", "reasoning_effort", "max_completion_tokens")
    params.update({k: cfg["llm"][k] for k in optional if cfg["llm"].get(k) is not None})
    return params


def call_model(messages: list[dict], cfg: dict) -> dict:
    params = request_params(cfg)
    if os.getenv("ANNOTATION_MOCK") == "1":
        hit = int(hashlib.sha256(messages[0]["content"].encode()).hexdigest()[:8], 16) % 4 == 0
        ans = {"alasan": {"ku": "terpenuhi" if hit else "tidak", "ip1": "tidak", "ip2": "ya" if hit else "tidak",
                          "ip3": "tidak", "ip4": "tidak"}, "label": "buzzer" if hit else "non_buzzer"}
        raw = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ans), "refusal": None}}],
               "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
        return {"raw_response": raw, "model_snapshot": "mock", "request_params": params}
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(max_retries=cfg["llm"]["max_api_retries"], timeout=180)
    r = _client.chat.completions.create(messages=messages, **params)
    return {"raw_response": r.model_dump(), "model_snapshot": r.model, "request_params": params}


_REAL_CALL_MODEL = call_model


def preflight() -> None:
    """Sebelum memanggil API sungguhan: paket openai dan OPENAI_API_KEY harus tersedia."""
    try:
        import openai  # noqa: F401
    except ImportError as e:
        raise AnnotationError("Paket openai belum terpasang di Python kernel ini. Jalankan: python -m pip install openai "
                              "(di lingkungan yang sama dengan kernel notebook), lalu ulangi tahap ini.") from e
    key = os.getenv("OPENAI_API_KEY") or ""
    if not key:
        raise AnnotationError("OPENAI_API_KEY belum diset. Jalankan sel API key di notebook (atau set variabel "
                              "lingkungan OPENAI_API_KEY), lalu ulangi tahap ini.")
    if not key.startswith("sk-") or any(c.isspace() for c in key):
        raise AnnotationError("OPENAI_API_KEY tidak berbentuk API key OpenAI (harus diawali 'sk-', tanpa spasi atau baris "
                              "baru) -- kemungkinan teks lain ikut tertempel. Jalankan ulang sel API key dan tempel key-nya saja.")


def parse_answer(content: str, cfg: dict) -> tuple[dict, bool]:
    """(1) ekstrak JSON, (2) perbaiki bila rusak [CHEN], (3) validasi enum."""
    text = (content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    candidate = text[start:end + 1] if start != -1 and end > start else text
    repaired = False
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        if not cfg["llm"]["repair_json"]:
            raise ValueError("JSON tidak valid (repair_json: false)")
        from json_repair import repair_json
        obj, repaired = repair_json(text, return_objects=True), True
    if not isinstance(obj, dict) or not isinstance(obj.get("alasan"), dict):
        raise ValueError(f"bukan objek {{alasan, label}}: {str(obj)[:80]}")
    rec = {**{f: obj["alasan"].get(f) for f in CRITERIA}, "label": obj.get("label")}
    for f in IP_FIELDS:
        if isinstance(rec[f], str) and rec[f].strip().lower() == "null":
            rec[f], repaired = None, True
    bad = problems(rec, cfg["output_schema"]["ip_when_ku_not_met"])
    if bad:
        raise ValueError("; ".join(bad))
    return rec, repaired


def parse_response(raw: dict, cfg: dict) -> tuple[dict, bool]:
    choice = raw["choices"][0]
    msg = choice["message"]
    if choice.get("finish_reason") != "stop" or msg.get("refusal"):
        raise ValueError(f"finish_reason={choice.get('finish_reason')}, refusal={msg.get('refusal')}")
    return parse_answer(msg["content"], cfg)


def rule_check(rec: dict, row, cfg: dict, rules: dict) -> dict:
    """Pemeriksaan Tabel 4 (dan IP3 dari kolom bila diaktifkan)."""
    ip = {f: rec[f] for f in IP_FIELDS}
    out = {"ip3_code": None, "ip3_mismatch": None}
    if cfg["rules"]["ip3_from_columns"]:
        out["ip3_code"] = ip3_from_columns(row, rules)
        out["ip3_mismatch"] = rec["ip3"] is not None and rec["ip3"] != out["ip3_code"]
        ip["ip3"] = out["ip3_code"]
    out["derived_label"] = derive_label(rec["ku"], ip, rules)
    out["rule_inconsistent"] = out["derived_label"] != rec["label"]
    return out


USAGE_FIELDS = ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens", "finish_reason")


def usage_from_raw(raw: dict) -> dict:
    """Penggunaan token dari respons API (kalibrasi biaya)."""
    raw = raw or {}
    usage = raw.get("usage") or {}
    choices = raw.get("choices") or [{}]
    return {"prompt_tokens": usage.get("prompt_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "finish_reason": choices[0].get("finish_reason")}


def usage_summary(calls: pd.DataFrame) -> pd.DataFrame:
    """Per tahap: jumlah panggilan, total token, persentase cached_tokens, rata-rata reasoning_tokens."""
    cols = ["panggilan", "prompt_tokens", "cached_tokens", "completion_tokens", "cached_pct", "reasoning_rata2"]
    if not len(calls):
        return pd.DataFrame(columns=cols)
    c = calls.reindex(columns=["stage", *USAGE_FIELDS])
    num = c[["prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens"]].apply(pd.to_numeric, errors="coerce")
    g = num.assign(stage=c.stage).groupby("stage")
    out = pd.DataFrame({"panggilan": c.groupby("stage").size(),
                        "prompt_tokens": g.prompt_tokens.sum(min_count=1), "cached_tokens": g.cached_tokens.sum(min_count=1),
                        "completion_tokens": g.completion_tokens.sum(min_count=1),
                        "reasoning_rata2": g.reasoning_tokens.mean()})
    out["cached_pct"] = 100 * out.cached_tokens / out.prompt_tokens
    return out[cols]


def read_calls(cfg: dict) -> pd.DataFrame:
    p = paths(cfg).llm_calls
    if not p.exists():
        return pd.DataFrame(columns=["user_id", "stage", "prompt_sha256", "status", "parsed_label"])
    return pd.DataFrame([json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])


def ok_labels(cfg: dict, prompt_sha: str, stage: str, repeat: int = 1) -> pd.DataFrame:
    """Isian `ok` per akun untuk (prompt, stage, pengulangan)."""
    c = read_calls(cfg)
    rep = c["repeat"].fillna(1).astype(int) if "repeat" in c else pd.Series(1, index=c.index)
    c = c[(c.status == "ok") & (c.prompt_sha256 == prompt_sha) & (c.stage == stage) & (rep == repeat)]
    dup = sorted(set(c.user_id[c.user_id.duplicated()]))
    if dup:
        raise AnnotationError(f"I5: akun dengan lebih dari satu label ok: {dup[:5]}")
    cols = ["user_id", *CRITERIA, "llm_label", "derived_label", "label", "rule_inconsistent", "ip3_mismatch",
            "model_snapshot"]
    if not len(c):
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({"user_id": c.user_id.values, "ku": c.parsed_ku.values})
    for f in IP_FIELDS:
        out[f] = [ip[f] for ip in c.parsed_ip]
    out["llm_label"], out["derived_label"] = c.parsed_label.values, c.derived_label.values
    out["label"] = out.llm_label if cfg["rules"]["label_policy"] == "llm" else out.derived_label
    out["rule_inconsistent"], out["ip3_mismatch"] = c.rule_inconsistent.values, c.ip3_mismatch.values
    out["model_snapshot"] = c.model_snapshot.values
    return out[cols]


def _check_append_only(cfg: dict) -> None:
    """Invarian I7: prefiks log yang tercatat setelah run terakhir harus tetap sama."""
    p, chk = paths(cfg).llm_calls, paths(cfg).llm_calls_check
    if not chk.exists():
        if p.exists() and p.stat().st_size:
            raise AnnotationError(f"I7: {p.name} ada tanpa {chk.name} -- log tidak bisa diverifikasi.")
        return
    c = read_json(chk)
    data = p.read_bytes() if p.exists() else b""
    if len(data) < c["size"] or hashlib.sha256(data[: c["size"]]).hexdigest() != c["sha256"]:
        raise AnnotationError(f"I7: {p.name} diubah/dipotong sejak run terakhir. Log ini tidak boleh diedit.")


def _save_checkpoint(cfg: dict) -> None:
    p = paths(cfg).llm_calls
    write_json(paths(cfg).llm_calls_check, {"size": p.stat().st_size, "sha256": sha256_file(p)})


def assert_no_mock(cfg: dict) -> None:
    """Mode produksi menolak lanjut bila ada baris tiruan di llm_calls.jsonl (tidak bisa dihapus: append-only)."""
    if is_mock():
        return
    c = read_calls(cfg)
    n = int((c["model_snapshot"] == "mock").sum()) if "model_snapshot" in c else 0
    if n:
        raise AnnotationError(f"{n} baris tiruan (model_snapshot=mock) ada di {paths(cfg).llm_calls}. Log produksi "
                              f"tercemar; mulai ulang state/ dari awal. Mode tiruan kini menulis ke state_mock/.")


def annotate(cfg: dict, clean: pd.DataFrame, user_ids: list[str], version: str, stage: str, repeat: int = 1) -> dict:
    """Label akun yang belum punya isian ok untuk (prompt, stage, pengulangan)."""
    assert_no_mock(cfg)
    if not is_mock() and call_model is _REAL_CALL_MODEL:
        preflight()
    prompt = load_prompt(cfg, version, clean)
    rules = load_rules(paths(cfg).rules)
    by_id = clean.set_index("user_id", drop=False)
    for uid in user_ids:
        check_length(by_id.loc[uid], cfg)
    _check_append_only(cfg)
    done = set(ok_labels(cfg, prompt.sha256, stage, repeat).user_id)
    todo = [u for u in user_ids if u not in done]
    run_id = uuid.uuid4().hex[:12]

    def one(uid: str) -> list[dict]:
        row = by_id.loc[uid]
        messages = render_messages(row, prompt, cfg)
        records = []
        for attempt in range(1, cfg["llm"]["max_parse_retries"] + 2):
            rec = {"call_id": uuid.uuid4().hex, "run_id": run_id, "stage": stage, "repeat": repeat, "prompt_version": version,
                   "render_format": prompt.render_format, "layout": prompt.layout,
                   "prompt_sha256": prompt.sha256, "user_id": uid, "model_requested": cfg["llm"]["model"],
                   "model_snapshot": None, "request_params": None, "messages": messages, "raw_response": None,
                   "parsed_ku": None, "parsed_ip": None, "parsed_label": None, "derived_label": None,
                   "rule_inconsistent": None, "ip3_code": None, "ip3_mismatch": None, "repair_applied": False,
                   **dict.fromkeys(USAGE_FIELDS), "truncated": False, "status": None, "error": None,
                   "attempt": attempt, "timestamp_utc": now_utc()}
            try:
                res = call_model(messages, cfg)
            except Exception as e:  # noqa: BLE001 -- SDK sudah mencoba ulang; catat dan berhenti untuk akun ini
                records.append({**rec, "status": "api_error", "error": repr(e)})
                return records
            rec.update({k: res[k] for k in ("model_snapshot", "request_params", "raw_response")} | usage_from_raw(res["raw_response"]))
            try:
                ans, repaired = parse_response(res["raw_response"], cfg)
            except (ValueError, KeyError, TypeError, IndexError) as e:
                records.append({**rec, "status": "parse_error", "error": str(e)})
                continue
            records.append({**rec, "status": "ok", "repair_applied": repaired, "parsed_ku": ans["ku"],
                            "parsed_ip": {f: ans[f] for f in IP_FIELDS}, "parsed_label": ans["label"],
                            **rule_check(ans, row, cfg, rules)})
            return records
        return records

    failed, log = [], paths(cfg).llm_calls
    log.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(cfg["llm"]["workers"]) as ex, open(log, "a", encoding="utf-8") as f:
        futures = [ex.submit(one, u) for u in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            recs = fut.result()
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            f.flush()
            if recs[-1]["status"] != "ok":
                failed.append(recs[-1]["user_id"])
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} akun")
    if log.exists():
        _save_checkpoint(cfg)
    return {"prompt_sha256": prompt.sha256, "skipped": len(done & set(user_ids)), "called": len(todo), "failed": sorted(failed)}


def apply_manual_rules(df: pd.DataFrame, prefix: str, clean: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Label manusia (GATE 1/3) harus sesuai Tabel 4 (rules.manual_rule_check)"""
    rules = load_rules(paths(cfg).rules)
    by_id = clean.set_index("user_id", drop=False)
    df = df.copy()
    issues = {"rule_inconsistent": [], "ip3_mismatch": [], "derived_changes": []}
    for i, r in df.iterrows():
        rec = {f: (r[f"{prefix}{f}"] or None) for f in FIELDS}
        if rec["ku"] is None:
            continue
        chk = rule_check(rec, by_id.loc[r.user_id], cfg, rules)
        if chk["ip3_mismatch"]:
            issues["ip3_mismatch"].append(r.user_id)
        if chk["rule_inconsistent"]:
            issues["rule_inconsistent"].append(f"{r.user_id} (label {rec['label']}, Tabel 4: {chk['derived_label']})")
            if cfg["rules"]["manual_rule_check"] == "derive":
                df.loc[i, f"{prefix}label"] = chk["derived_label"]
                issues["derived_changes"].append(r.user_id)
    if issues["rule_inconsistent"] and cfg["rules"]["manual_rule_check"] == "block":
        raise AnnotationError(f"{len(issues['rule_inconsistent'])} label manusia tidak sesuai Tabel 4 "
                              f"(manual_rule_check: block). Perbaiki KU/IP atau label lalu impor ulang:\n  "
                              + "\n  ".join(issues["rule_inconsistent"][:20]))
    if issues["derived_changes"]:
        print(f"{len(issues['derived_changes'])} label manusia diganti label Tabel 4 (manual_rule_check: derive): "
              f"{issues['derived_changes'][:10]}")
    if issues["ip3_mismatch"]:
        print(f"PERINGATAN: {len(issues['ip3_mismatch'])} isian IP3 manusia berbeda dari kolom: {issues['ip3_mismatch'][:10]}")
    return df, issues


def rule_summary(labels: pd.DataFrame) -> str:
    """Ringkasan pemeriksaan aturan untuk dicetak/dilaporkan."""
    n_inc = int(labels.rule_inconsistent.eq(True).sum())
    n_ip3 = int(labels.ip3_mismatch.eq(True).sum())
    return f"label LLM != Tabel 4: {n_inc}/{len(labels)} | IP3 LLM != IP3 kolom: {n_ip3}/{len(labels)}"
