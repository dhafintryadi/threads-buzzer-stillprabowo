"""A0 -- validasi kontrak input dan estimasi token."""

from __future__ import annotations

from .common import add_manifest, paths, read_clean_data
from .llm import count_tokens


def run(cfg: dict) -> dict:
    df, warnings = read_clean_data(cfg)
    tokens = df.caption_text.map(count_tokens)
    chars = df.caption_text.str.len()
    limit = cfg["llm"]["max_input_tokens"]
    stats = {
        "n_accounts": len(df),
        "caption_chars": {"min": int(chars.min()), "median": float(chars.median()),
                          "p95": float(chars.quantile(0.95)), "max": int(chars.max())},
        "caption_tokens_est": {"median": float(tokens.median()), "p95": float(tokens.quantile(0.95)),
                               "max": int(tokens.max()), "total": int(tokens.sum())},
        "over_max_input_tokens": int((tokens > limit).sum()) if limit else None,
        "warnings": warnings,
    }
    print(f"{len(df)} akun valid. Panjang caption (karakter) min/median/p95/max: "
          f"{stats['caption_chars']['min']}/{stats['caption_chars']['median']:.0f}/"
          f"{stats['caption_chars']['p95']:.0f}/{stats['caption_chars']['max']}")
    print(f"Estimasi token caption: total {stats['caption_tokens_est']['total']:,}, "
          f"maks per akun {stats['caption_tokens_est']['max']} (perkiraan, bukan hitungan API).")
    print(f"Akun > max_input_tokens: {stats['over_max_input_tokens']}" if limit
          else "max_input_tokens belum diisi -- jumlah akun yang perlu dipotong belum bisa dihitung.")
    for w in warnings:
        print("PERINGATAN:", w)
    add_manifest(cfg, "a0_validate_input", [paths(cfg).clean_data], [], stats)
    return stats
