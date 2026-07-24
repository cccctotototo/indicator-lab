from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
MARKET_DIR = DATA_DIR / "market"
SAMPLES_DIR = DATA_DIR / "samples"
MODELS_DIR = DATA_DIR / "models"
STRATEGY_VERSIONS_DIR = DATA_DIR / "strategy_versions"
EXPORTS_DIR = PROJECT_ROOT / "exports"
INDICATORS_DIR = PROJECT_ROOT / "indicators"
ADAPTERS_DIR = PROJECT_ROOT / "adapters"
DB_PATH = DATA_DIR / "app.db"

LABELS = ("win", "loss", "breakeven", "invalid")
LABEL_ZH = {"win": "贏", "loss": "輸", "breakeven": "打平", "invalid": "無效"}
DIRECTIONS = ("long", "short")


def ensure_directories() -> None:
    for path in (
        MARKET_DIR,
        MODELS_DIR,
        STRATEGY_VERSIONS_DIR,
        EXPORTS_DIR,
        INDICATORS_DIR,
        ADAPTERS_DIR,
        *(SAMPLES_DIR / label for label in LABELS),
    ):
        path.mkdir(parents=True, exist_ok=True)
