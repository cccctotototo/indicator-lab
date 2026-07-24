from __future__ import annotations

import gzip
import json

import pandas as pd

from quant_labeler import labeling


def test_delete_label_snapshot_removes_database_label_and_file(tmp_path, monkeypatch):
    samples = tmp_path / "data" / "samples"
    snapshot = samples / "win" / "signal_1.json.gz"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(b"snapshot")
    calls: list[int] = []

    monkeypatch.setattr(labeling, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(labeling, "SAMPLES_DIR", samples)
    monkeypatch.setattr(
        labeling,
        "get_signal",
        lambda signal_id: {
            "id": signal_id,
            "existing_sample_path": str(snapshot.relative_to(tmp_path)),
        },
    )
    monkeypatch.setattr(labeling, "delete_label", calls.append)

    removed = labeling.delete_label_snapshot(1)

    assert removed is True
    assert calls == [1]
    assert not snapshot.exists()


def test_delete_label_snapshot_rejects_paths_outside_sample_directory(
    tmp_path, monkeypatch
):
    samples = tmp_path / "data" / "samples"
    samples.mkdir(parents=True)
    outside = tmp_path / "outside.json.gz"
    outside.write_bytes(b"snapshot")

    monkeypatch.setattr(labeling, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(labeling, "SAMPLES_DIR", samples)
    monkeypatch.setattr(
        labeling,
        "get_signal",
        lambda _signal_id: {"existing_sample_path": str(outside)},
    )

    try:
        labeling.delete_label_snapshot(1)
    except ValueError as exc:
        assert "安全目錄" in str(exc)
    else:
        raise AssertionError("unsafe snapshot path was accepted")

    assert outside.exists()


def test_save_label_snapshot_rolls_back_file_when_database_write_fails(
    tmp_path, monkeypatch
):
    samples = tmp_path / "data" / "samples"
    samples.mkdir(parents=True)
    timestamp = pd.Timestamp("2025-01-01T00:00:00Z")
    frame = pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 10.0,
            },
            {
                "timestamp": pd.Timestamp("2025-01-01T00:15:00Z"),
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 11.0,
            },
        ]
    )

    monkeypatch.setattr(labeling, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(labeling, "SAMPLES_DIR", samples)
    monkeypatch.setattr(
        labeling,
        "get_signal",
        lambda signal_id: {
            "id": signal_id,
            "dataset_id": 1,
            "indicator_name": "test",
            "symbol": "BTCUSDT",
            "interval": "15m",
            "market_type": "futures",
            "timestamp": timestamp,
            "direction": "long",
            "source": "test",
            "existing_sample_path": None,
        },
    )

    def fail_write(_signal_id, _payload):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(labeling, "upsert_label", fail_write)

    try:
        labeling.save_label_snapshot(1, "win", frame=frame)
    except RuntimeError as exc:
        assert "database unavailable" in str(exc)
    else:
        raise AssertionError("database write failure was swallowed")

    assert list(samples.rglob("*.json.gz")) == []
    assert list(samples.rglob("*.tmp")) == []


def test_save_label_snapshot_creates_valid_gzip_json(tmp_path, monkeypatch):
    samples = tmp_path / "data" / "samples"
    samples.mkdir(parents=True)
    timestamp = pd.Timestamp("2025-01-01T00:00:00Z")
    frame = pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 10.0,
            }
        ]
    )
    saved: dict = {}

    monkeypatch.setattr(labeling, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(labeling, "SAMPLES_DIR", samples)
    monkeypatch.setattr(
        labeling,
        "get_signal",
        lambda signal_id: {
            "id": signal_id,
            "dataset_id": 1,
            "indicator_name": "test",
            "symbol": "BTCUSDT",
            "interval": "15m",
            "market_type": "futures",
            "timestamp": timestamp,
            "direction": "long",
            "source": "test",
            "existing_sample_path": None,
        },
    )
    monkeypatch.setattr(
        labeling,
        "upsert_label",
        lambda signal_id, payload: saved.update(signal_id=signal_id, **payload),
    )

    payload = labeling.save_label_snapshot(1, "win", frame=frame)
    target = tmp_path / saved["sample_path"]

    with gzip.open(target, "rt", encoding="utf-8") as handle:
        stored = json.load(handle)
    assert stored == payload
    assert list(samples.rglob("*.tmp")) == []
