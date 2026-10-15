"""Format anotasi dan aturan label (Tabel 4, dibaca dari rules.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

LABELS = ("buzzer", "non_buzzer")
POSITIVE = "buzzer"
KU_VALUES = ("terpenuhi", "sebagian", "tidak")
IP_FIELDS = ("ip1", "ip2", "ip3", "ip4")
IP_VALUES = ("ya", "tidak")
FIELDS = ("ku",) + IP_FIELDS + ("label",)


def load_rules(path: Path) -> dict:
    rules = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for r in rules["rules"]:
        assert r["ku"] in KU_VALUES and r["label"] in LABELS, f"aturan tidak valid di {path}: {r}"
        min_yes = r.get("min_yes") or {"count": 1, "of": []}
        assert isinstance(min_yes["count"], int) and min_yes["count"] >= 1, f"min_yes.count tidak valid: {r}"
        used = r.get("requires_any", []) + r.get("requires_all", []) + min_yes["of"]
        assert set(used) <= set(IP_FIELDS), f"indikator tidak dikenal: {r}"
    assert rules["default_label"] in LABELS
    return rules


def derive_label(ku: str, ip: dict, rules: dict) -> str:
    """Tabel 4: aturan pertama yang cocok dengan KU dan indikator menentukan label."""
    for r in rules["rules"]:
        if ku != r["ku"]:
            continue
        if r.get("requires_any") and not any(ip.get(f) == "ya" for f in r["requires_any"]):
            continue
        if r.get("requires_all") and not all(ip.get(f) == "ya" for f in r["requires_all"]):
            continue
        if r.get("min_yes") and sum(ip.get(f) == "ya" for f in r["min_yes"]["of"]) < r["min_yes"]["count"]:
            continue
        return r["label"]
    return rules["default_label"]


def rules_text(rules: dict) -> str:
    """Teks aturan keputusan yang dihasilkan dari rules.yaml (dipakai bila decision_rule memuat {{rules}})."""
    lines = []
    for r in rules["rules"]:
        cond = [f"ku = {r['ku']}"]
        if r.get("requires_any"):
            cond.append("minimal satu dari " + ", ".join(r["requires_any"]) + " = ya")
        if r.get("requires_all"):
            cond.append(" dan ".join(f"{f} = ya" for f in r["requires_all"]))
        if r.get("min_yes"):
            cond.append(f"minimal {r['min_yes']['count']} dari " + ", ".join(r["min_yes"]["of"]) + " = ya")
        lines.append(f"- Jika {' dan '.join(cond)}: label = {r['label']}.")
    lines.append(f"- Selain itu: label = {rules['default_label']}.")
    return "\n".join(lines)


def ip3_from_columns(row, rules: dict) -> str:
    """IP3 dihitung dari kolom numerik: threads_topik + balasan_topik >= ambang."""
    return "ya" if int(row["threads_topik"]) + int(row["balasan_topik"]) >= rules["ip3_min_topic_posts"] else "tidak"


def problems(record: dict, ip_mode: str, with_ku_ip: bool = True) -> list[str]:
    """Masalah enum pada isian datar."""
    out = []
    if record.get("label") not in LABELS:
        out.append(f"label {record.get('label')!r} di luar {LABELS}")
    if not with_ku_ip:
        return out
    ku = record.get("ku")
    if ku not in KU_VALUES:
        out.append(f"ku {ku!r} di luar {KU_VALUES}")
    for f in IP_FIELDS:
        v = record.get(f)
        if v in (None, "") and ip_mode == "null" and ku == "tidak":
            continue
        if v not in IP_VALUES:
            out.append(f"{f} {v!r} di luar {IP_VALUES}" + (" (kosong hanya boleh bila ku=tidak)" if ip_mode == "null" else ""))
    return out


def json_schema(ip_mode: str) -> dict:
    """Skema structured output: {"alasan": {ku, ip1..ip4}, "label"} -- alasan dulu, label terakhir [CHEN]."""
    ip = ({"type": ["string", "null"], "enum": [*IP_VALUES, None]} if ip_mode == "null"
          else {"type": "string", "enum": list(IP_VALUES)})
    alasan = {"type": "object", "additionalProperties": False, "required": ["ku", *IP_FIELDS],
              "properties": {"ku": {"type": "string", "enum": list(KU_VALUES)}, **{f: dict(ip) for f in IP_FIELDS}}}
    return {"name": "annotation", "strict": True,
            "schema": {"type": "object", "additionalProperties": False, "required": ["alasan", "label"],
                       "properties": {"alasan": alasan, "label": {"type": "string", "enum": list(LABELS)}}}}


def nested(record: dict) -> dict:
    """Isian datar -> bentuk jawaban LLM (dipakai untuk contoh few-shot)."""
    return {"alasan": {f: (record[f] or None) for f in ("ku", *IP_FIELDS)}, "label": record["label"]}
