"""report.md yang mudah dibaca dari report.json."""

from __future__ import annotations

from pathlib import Path


def _fmt(x) -> str:
    return f"{x:.4g}" if isinstance(x, float) else str(x)


def write_report_md(report: dict, path: Path) -> None:
    L = [f"# Laporan rekayasa fitur ({report['dibuat_utc']})", "",
         f"Varian: **{report['varian']}** -- penyebut kepadatan leksikon = {report['penyebut_kepadatan']} "
         f"(akun tanpa token aliran leksikon: {report['akun_tanpa_token_leksikon']}).", ""]
    inp = report["input"]
    L += [f"Input: {inp['rows']} akun ({inp['buzzer']} buzzer, {inp['non_buzzer']} non-buzzer). "
          f"`caption_text_clean` kosong: {inp['empty_caption_text_stream_t']} akun (similarity = 0).", ""]

    L += ["## Split", "", "| Split | Seed | Train (buzzer) | Test (buzzer) | Proporsi buzzer train / test | Penskalaan |", "|---|---|---|---|---|---|"]
    for name, sp in report["splits"].items():
        s = sp["summary"]
        L.append(f"| {name} | {s['seed']} | {s['n_train']} ({s['buzzer_train']}) | {s['n_test']} ({s['buzzer_test']}) | "
                 f"{s['prop_buzzer_train']} / {s['prop_buzzer_test']} | {sp['scaling']['method']} |")
    L.append("")

    L += ["## Fitur leksikon (seluruh akun, sebelum split)", "", "| Fitur | Entri (dedup) | Total kemunculan | Nilai 0 | Min | Median | Maks |", "|---|---|---|---|---|---|---|"]
    for col, lx in report["leksikon"].items():
        d = lx["distribusi"]
        L.append(f"| {col} | {lx['entri_setelah_dedup']} | {lx['total_kemunculan']} | {d['n_zero']} ({d['pct_zero']}%) | "
                 f"{_fmt(d['min'])} | {_fmt(d['median'])} | {_fmt(d['max'])} |")
    L.append("")

    for name, sp in report["splits"].items():
        sc = sp["scaling"]
        L += [f"## {name}: outlier (Tukey, data latih) dan penskalaan", "",
              f"Metode: **{sc['method']}** -- {sc['rule_note']}. Dikeluarkan dari aturan (IQR = 0): "
              f"{', '.join(sc['excluded_iqr_zero']) or '-'}.", "",
              "| Fitur | Q1 | Q3 | IQR | Proporsi outlier | Ikut aturan | Parameter scaler |", "|---|---|---|---|---|---|---|"]
        for f, o in sp["outliers"].items():
            p = sc["params"][f]
            ps = ", ".join(f"{k}={_fmt(v)}" for k, v in p.items())
            L.append(f"| {f} | {_fmt(o['q1'])} | {_fmt(o['q3'])} | {_fmt(o['iqr'])} | {o['outlier_prop']} | "
                     f"{'ya' if o['eligible'] else 'tidak (IQR=0)'} | {ps} |")
        L.append("")

    L += ["## Pemeriksaan", ""]
    for c in report["checks"]:
        L.append(f"- [{'x' if c['passed'] else ' '}] {c['split'] or 'global'}: {c['check']} {('-- ' + c['detail']) if c['detail'] else ''}")
    L += ["", "## Peringatan", ""] + ([f"- {w}" for w in report["warnings"]] or ["- (tidak ada)"])
    L += ["", "## Parameter yang menunggu konfirmasi peneliti", "",
          "outlier (Tukey, 1,5 IQR, ambang 0,05), aturan pemilihan scaler, kemunculan leksikon = total, "
          "aliran leksikon tanpa stemming. Harus ditetapkan sebelum melihat hasil model."]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
