"""`probe` -- uji langsung ke API parameter mana yang diterima model."""

from __future__ import annotations

from .common import AnnotationError, add_manifest, is_mock, now_utc, paths, write_json
from .labels import json_schema

VARIANTS = {
    "bawaan": {},
    "temperature=0": {"temperature": 0},
    "temperature=1": {"temperature": 1},
    "top_p=1": {"top_p": 1},
    "top_p=0.5": {"top_p": 0.5},
    "reasoning_effort=minimal": {"reasoning_effort": "minimal"},
    "reasoning_effort=low": {"reasoning_effort": "low"},
    "reasoning_effort=medium": {"reasoning_effort": "medium"},
    "reasoning_effort=high": {"reasoning_effort": "high"},
    "structured_output": {"response_format": {"type": "json_schema", "json_schema": json_schema("null")}},
}


def run(cfg: dict) -> dict:
    if is_mock():
        raise AnnotationError("probe memanggil API sungguhan; jalankan tanpa ANNOTATION_MOCK=1.")
    from openai import OpenAI
    client = OpenAI(max_retries=1, timeout=120)
    messages = [{"role": "user", "content": 'Jawab dengan JSON: {"alasan": {"ku": "tidak", "ip1": null, "ip2": null, '
                                            '"ip3": null, "ip4": null}, "label": "non_buzzer"}'}]
    results = {}
    for name, extra in VARIANTS.items():
        try:
            r = client.chat.completions.create(model=cfg["llm"]["model"], messages=messages, **extra)
            details = getattr(r.usage, "completion_tokens_details", None)
            results[name] = {"accepted": True, "model_snapshot": r.model, "params": extra,
                             "reasoning_tokens": getattr(details, "reasoning_tokens", None)}
        except Exception as e:  # noqa: BLE001 -- tujuan probe adalah mencatat penolakan
            results[name] = {"accepted": False, "params": extra, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        print(f"{name:<26} {'DITERIMA' if results[name]['accepted'] else 'DITOLAK '} "
              f"{results[name].get('model_snapshot') or results[name].get('error', '')[:110]}")
    out = {"model": cfg["llm"]["model"], "probed_at": now_utc(), "results": results}
    write_json(paths(cfg).state / "api_probe.json", out)
    add_manifest(cfg, "probe", [], [paths(cfg).state / "api_probe.json"], {"accepted": [k for k, v in results.items() if v["accepted"]]})
    print("Isi llm.temperature / llm.top_p / llm.reasoning_effort di config hanya dengan nilai yang DITERIMA.")
    return out
