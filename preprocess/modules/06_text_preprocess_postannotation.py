"""Tahap 6: ALIRAN T (TF-IDF) pasca-anotasi."""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
for _p in (_THIS_DIR, _ROOT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config as cfgmod
import schema
import storage
from manifest import RunManifest
from text_streams.stemmer_ext import build_stemmers
from text_streams.stream_t import stream_t

STEMMER_DICTIONARIES = ("default", "extended")
STOPWORD_SOURCES = ("sastrawi_default",)


class TextPreprocessConfigError(Exception):
    pass


def read_stream_t_config(cfg: dict) -> dict:
    tf = cfg.get("text_features") or {}
    st = tf.get("stream_t") or {}
    dictionary = st.get("stemmer_dictionary")
    stopwords = st.get("stopwords")
    if dictionary not in STEMMER_DICTIONARIES:
        raise TextPreprocessConfigError(
            f"text_features.stream_t.stemmer_dictionary={dictionary!r} tidak dikenal (pilihan: {list(STEMMER_DICTIONARIES)})."
        )
    if stopwords not in STOPWORD_SOURCES:
        raise TextPreprocessConfigError(
            f"text_features.stream_t.stopwords={stopwords!r} tidak dikenal (pilihan: {list(STOPWORD_SOURCES)})."
        )
    return {"stemmer_dictionary": dictionary, "stopwords": stopwords}


def load_labeled_inputs(cfg: dict):
    """Baca + validasi serah terima dari annotation/."""
    labeled_path = cfgmod.resolve_path(cfg, "paths.clean_data_labeled_csv")
    clean_data_path = cfgmod.resolve_path(cfg, "paths.clean_data_csv")
    report_path = cfgmod.resolve_path(cfg, "paths.annotation_report_json")

    labeled = schema.read_and_validate_csv(
        labeled_path, schema.CLEAN_DATA_LABELED_COLUMNS, schema.LABELED_STRING_COLUMNS,
        "clean_data_labeled.csv", int_columns=schema.LABELED_INT_COLUMNS,
    )
    clean_data = schema.read_and_validate_csv(
        clean_data_path, schema.CLEAN_DATA_COLUMNS, ["user_id", "caption_text"], "clean_data.csv",
        int_columns=schema.COUNT_COLUMNS,
    )
    schema.validate_labeled_contract(labeled, clean_data)

    if not report_path.exists():
        raise schema.SchemaValidationError(f"annotation_report.json tidak ditemukan: {report_path}")
    report = storage.read_json(report_path)
    frozen = report.get("frozen_prompt") or {}
    if not frozen.get("prompt_version") or not frozen.get("prompt_sha256"):
        raise schema.SchemaValidationError(
            f"{report_path.name}: frozen_prompt.prompt_version / prompt_sha256 tidak ada (prompt belum dibekukan?)."
        )
    labeled_version = labeled["final_prompt_version"].iloc[0]
    if frozen["prompt_version"] != labeled_version:
        raise schema.SchemaValidationError(
            f"final_prompt_version di clean_data_labeled.csv ({labeled_version!r}) berbeda dari prompt beku di "
            f"{report_path.name} ({frozen['prompt_version']!r}): keluaran anotasi dan laporan bukan dari run yang sama."
        )
    return labeled, report, {"labeled": labeled_path, "clean_data": clean_data_path, "report": report_path}


def run(cfg: dict, write_manifest: bool = True) -> dict:
    t_cfg = read_stream_t_config(cfg)
    tf = cfg["text_features"]
    df, report, paths = load_labeled_inputs(cfg)

    bundle = build_stemmers(tf["extra_roots"], tf.get("expected_dict_hash"))
    extended = t_cfg["stemmer_dictionary"] == "extended"

    df = df.copy()
    df["caption_text_clean"] = df["caption_text"].fillna("").apply(lambda t: stream_t(t, bundle, extended))

    io_cfg = cfg["csv_io"]
    out_path = cfgmod.resolve_path(cfg, "paths.clean_data_text_csv")
    storage.write_csv_deterministic(
        df[schema.CLEAN_DATA_TEXT_COLUMNS], out_path, io_cfg["sort_column"], io_cfg["encoding"], io_cfg["quoting"]
    )

    empty_after_clean = int((df["caption_text_clean"].str.len() == 0).sum())
    label_counts = {int(k): int(v) for k, v in df["label"].value_counts().sort_index().items()}
    label_source_counts = {str(k): int(v) for k, v in df["label_source"].value_counts().items()}

    if write_manifest:
        manifest_path = cfgmod.resolve_path(cfg, "paths.run_manifest_json")
        manifest = RunManifest(manifest_path, config_path=cfgmod.config_path(cfg))
        manifest.add_stage(
            stage_name="06_text_preprocess_postannotation",
            inputs=[paths["labeled"], paths["clean_data"], paths["report"]],
            outputs=[out_path],
            rows_in=len(df),
            rows_out=len(df),
            rows_dropped=[],
            extra={
                "labeled_sha256": storage.sha256_file(paths["labeled"]),
                "clean_data_sha256": storage.sha256_file(paths["clean_data"]),
                "annotation_report_sha256": storage.sha256_file(paths["report"]),
                "frozen_prompt_version": report["frozen_prompt"]["prompt_version"],
                "frozen_prompt_sha256": report["frozen_prompt"]["prompt_sha256"],
                "label_counts": label_counts,
                "label_source_counts": label_source_counts,
                "stream": "T",
                "stream_t": t_cfg,
                "pysastrawi": bundle.version,
                "dict_hash": bundle.dict_hash,
                "stopword_count": len(bundle.stopwords_t),
                "stopword_list_sha256": storage.sha256_text("\n".join(sorted(bundle.stopwords_t))),
                "rows_with_empty_caption_text_clean": empty_after_clean,
            },
        )

    return {"df": df, "empty_after_clean": empty_after_clean, "label_counts": label_counts}


def main() -> None:
    cfg = cfgmod.load_config()
    result = run(cfg)
    print(f"caption_text_clean (aliran T) dihitung untuk {len(result['df'])} baris; label: {result['label_counts']}.")
    if result["empty_after_clean"]:
        print(f"  ({result['empty_after_clean']} baris caption_text_clean kosong setelah cleaning -- dihitung di manifest, tidak dibuang.)")


if __name__ == "__main__":
    main()
