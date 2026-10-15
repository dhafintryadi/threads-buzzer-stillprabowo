"""CLI pipeline preprocessing: satu entry point, satu subcommand per tahap."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
MODULES_DIR = ROOT_DIR / "modules"

STAGE_FILES = {
    "validate-load": "01_validate_load.py",
    "clean-account": "02_clean_account.py",
    "aggregate-text": "03_aggregate_text.py",
    "integrate": "04_integrate.py",
    "text-preprocess": "06_text_preprocess_postannotation.py",
}

ALL_ORDER = ["validate-load", "clean-account", "aggregate-text", "integrate"]


def _load_stage_module(filename: str):
    path = MODULES_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    all_commands = sorted(set(STAGE_FILES) | {"all"})
    parser = argparse.ArgumentParser(description="Pipeline preprocessing clean_data.csv")
    parser.add_argument("command", choices=all_commands)
    args, remaining_argv = parser.parse_known_args()

    if args.command == "all":
        for stage in ALL_ORDER:
            print(f"=== {stage} ===")
            module = _load_stage_module(STAGE_FILES[stage])
            sys.argv = ["main.py"]
            module.main()
        return

    filename = STAGE_FILES[args.command]
    module = _load_stage_module(filename)
    sys.argv = [filename] + remaining_argv
    module.main()


if __name__ == "__main__":
    main()
