"""CLI: python run_features.py [--config config/feature_config.yaml]."""

from __future__ import annotations

import argparse
import sys

from fe.lexicon import LexiconMissingError
from fe.pipeline import run
from fe.settings import FeatureEngineeringError, load_config, resolve


def main() -> int:
    parser = argparse.ArgumentParser(description="Rekayasa fitur: 8 fitur, 3 split stratified, terskala.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    try:
        result = run(cfg)
    except LexiconMissingError as exc:
        print(f"BERHENTI (tahap leksikon): {exc}", file=sys.stderr)
        return 2
    except FeatureEngineeringError as exc:
        print(f"BERHENTI: {exc}", file=sys.stderr)
        return 1
    print(f"== penyebut kepadatan: {result['report']['penyebut_kepadatan']} -> {resolve(cfg, 'output_dir')}")
    for name, sp in result["splits"].items():
        s = sp["summary"]
        print(f"  {name}: train {s['n_train']} ({s['buzzer_train']} buzzer), test {s['n_test']} ({s['buzzer_test']} buzzer), "
              f"penskalaan {sp['scaling']['method']} ({sp['scaling']['rule_note']})")
    for w in result["report"]["warnings"]:
        print(f"  PERINGATAN: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
