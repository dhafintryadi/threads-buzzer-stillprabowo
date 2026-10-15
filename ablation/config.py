"""Satu-satunya tempat konfigurasi analisis ablasi."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FEATURES = ["pengikut", "rasio_balasan", "rasio_unggahan_ulang", "threads_topik", "balasan_topik",
            "similarity", "kepadatan_leksikon_a", "kepadatan_leksikon_b"]


@dataclass(frozen=True)
class Settings:
    run_id: str = "model_v1"
    modeling_root: Path = ROOT.parent / "model" / "outputs"
    output_root: Path = ROOT / "output"

    predictions_file: str = "test_predictions.csv"
    model_metrics_file: str = "test_metrics.csv"
    model_baselines_file: str = "baselines.csv"

    col_user_id: str = "user_id"
    col_split: str = "split"
    col_config: str = "config"
    col_y_true: str = "y_true"
    col_y_pred: str = "y_pred"

    splits: dict = field(default_factory=lambda: {"70:30": 70, "80:20": 80, "90:10": 90})
    configs: dict = field(default_factory=lambda: {"akun": "akun", "teks": "teks", "gabungan": "gabungan"})
    reference_config: str = "gabungan"

    model_metric_columns: dict = field(default_factory=lambda: {
        "tp": "tp", "fp": "fp", "fn": "fn", "tn": "tn", "akurasi": "accuracy", "makro_f1": "f1_macro",
        "presisi_buzzer": "precision", "recall_buzzer": "recall", "f1_buzzer": "f1"})
    model_k_column: str = "k"

    positive_label: int = 1
    crosscheck_tol: float = 1e-9
    tie_tol: float = 1e-12
    std_ddof: int = 1
    fig_dpi: int = 300

    @property
    def run_dir(self) -> Path:
        return Path(self.modeling_root) / self.run_id

    @property
    def out_dir(self) -> Path:
        return Path(self.output_root) / self.run_id

    def split_key(self, label: str) -> str:
        """'70:30' -> '70_30' (akhiran nama kolom)."""
        return label.replace(":", "_")
