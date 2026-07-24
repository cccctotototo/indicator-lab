from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import quant_labeler.config as config
import quant_labeler.labeling as labeling
import quant_labeler.market as market
import quant_labeler.ml as ml
import quant_labeler.storage as storage
from quant_labeler.features import add_features


def test_end_to_end_label_snapshot_and_semisupervised_model(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    market_dir = data_dir / "market"
    samples_dir = data_dir / "samples"
    models_dir = data_dir / "models"
    exports_dir = tmp_path / "exports"
    indicators_dir = tmp_path / "indicators"
    adapters_dir = tmp_path / "adapters"
    patches = {
        "PROJECT_ROOT": tmp_path,
        "DATA_DIR": data_dir,
        "MARKET_DIR": market_dir,
        "SAMPLES_DIR": samples_dir,
        "MODELS_DIR": models_dir,
        "EXPORTS_DIR": exports_dir,
        "INDICATORS_DIR": indicators_dir,
        "ADAPTERS_DIR": adapters_dir,
        "DB_PATH": data_dir / "app.db",
    }
    for name, value in patches.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(storage, "DB_PATH", patches["DB_PATH"])
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(market, "MARKET_DIR", market_dir)
    monkeypatch.setattr(labeling, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(labeling, "SAMPLES_DIR", samples_dir)
    monkeypatch.setattr(ml, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ml, "MODELS_DIR", models_dir)
    config.ensure_directories()
    storage.initialize_database()

    rows = 900
    t = np.arange(rows)
    close = 100 + 0.02 * t + 4 * np.sin(t / 19) + 2 * np.sin(t / 61)
    frame = add_features(
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
                "open": close - 0.15,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 1000 + 100 * np.sin(t / 11),
            }
        )
    )
    market_path = market_dir / "TEST_custom_1h.csv"
    frame.to_csv(market_path, index=False)
    dataset_id = storage.add_dataset(
        "TESTUSDT", "1h", "custom", "UTC", frame, market_path, "pytest"
    )
    replacement_path = market_dir / "history" / "TEST_custom_1h.csv"
    replacement_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(replacement_path, index=False)
    storage.update_dataset_market_file(
        dataset_id,
        "TESTUSDT",
        "1h",
        "custom",
        "Asia/Taipei",
        frame,
        replacement_path,
        "pytest:full-history",
    )
    updated_dataset = storage.get_dataset(dataset_id)
    assert updated_dataset["id"] == dataset_id
    assert updated_dataset["timezone"] == "Asia/Taipei"
    assert updated_dataset["source"] == "pytest:full-history"
    assert Path(updated_dataset["resolved_path"]) == replacement_path
    records = [
        {
            "timestamp": frame.iloc[index].timestamp.isoformat(),
            "direction": "long" if number % 2 == 0 else "short",
        }
        for number, index in enumerate(range(100, 860, 38))
    ]
    assert storage.register_signals(dataset_id, "test_indicator", "pytest", records) == len(records)
    signals = storage.list_signals(dataset_id)
    monkeypatch.setattr(
        labeling,
        "load_saved_frame",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("rapid labeling must reuse the in-memory market frame")
        ),
    )
    for number, signal in enumerate(signals.head(12).itertuples(index=False)):
        payload = labeling.save_label_snapshot(
            int(signal.id),
            "win" if number % 2 == 0 else "loss",
            "pytest",
            12,
            40,
            20,
            frame=frame,
        )
        assert payload["context"]["candles"]
    labels = storage.analysis_frame()
    assert len(labels) == 12
    assert (tmp_path / labels.iloc[0].sample_path).exists()

    metadata = ml.train_semisupervised(0.70, min_labeled=10)
    assert metadata["labeled_count"] == 12
    assert metadata["unlabeled_count"] == len(records) - 12
    assert (models_dir / f"{metadata['name']}.joblib").exists()
    assert not storage.latest_predictions().empty
