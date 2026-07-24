from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_labeler import deletion, improvement, storage


def _prepare_workspace(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    data = tmp_path / "data"
    paths = {
        "market": data / "market",
        "samples": data / "samples",
        "versions": data / "strategy_versions",
        "indicators": tmp_path / "indicators",
        "adapters": tmp_path / "adapters",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    (paths["samples"] / "win").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage, "DB_PATH", data / "app.db")
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(deletion, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(deletion, "MARKET_DIR", paths["market"])
    monkeypatch.setattr(deletion, "SAMPLES_DIR", paths["samples"])
    monkeypatch.setattr(deletion, "STRATEGY_VERSIONS_DIR", paths["versions"])
    monkeypatch.setattr(deletion, "INDICATORS_DIR", paths["indicators"])
    monkeypatch.setattr(deletion, "ADAPTERS_DIR", paths["adapters"])
    monkeypatch.setattr(improvement, "STRATEGY_VERSIONS_DIR", paths["versions"])
    storage.initialize_database()
    return paths


def _add_dataset(paths: dict[str, Path]) -> int:
    market_file = paths["market"] / "BTCUSDT_15m.csv"
    market_file.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"]
            ),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10.0, 11.0],
        }
    )
    return storage.add_dataset(
        "BTCUSDT",
        "15m",
        "futures",
        "UTC",
        frame,
        market_file,
        "test",
    )


def _add_strategy(paths: dict[str, Path], dataset_id: int) -> None:
    versions = [
        ("strategy", None, 1),
        ("strategy_v2", "strategy", 2),
        ("strategy_v3", "strategy_v2", 3),
        ("strategy_v4", "strategy_v3", 4),
    ]
    for index, (name, parent, version) in enumerate(versions):
        (paths["indicators"] / f"{name}.pine").write_text(name, encoding="utf-8")
        (paths["adapters"] / f"{name}.py").write_text(name, encoding="utf-8")
        storage.register_signals(
            dataset_id,
            name,
            "test",
            [
                {
                    "timestamp": f"2026-01-01T0{index}:00:00+00:00",
                    "direction": "long",
                }
            ],
        )
        if version > 1:
            metadata = {
                "root": "strategy",
                "parent": parent,
                "child": name,
                "version": version,
                "dataset_id": dataset_id,
                "created_at": f"2026-01-0{version}T00:00:00+00:00",
            }
            (paths["versions"] / f"{name}.json").write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )

    v3_signal = storage.list_signals(dataset_id, "strategy_v3").iloc[0]
    sample = paths["samples"] / "win" / "strategy_v3.json.gz"
    sample.write_text("sample", encoding="utf-8")
    storage.upsert_label(
        int(v3_signal["id"]),
        {
            "label": "win",
            "sample_path": str(sample.relative_to(paths["market"].parents[1])),
        },
    )


def test_delete_version_removes_selected_branch_only(tmp_path, monkeypatch):
    paths = _prepare_workspace(tmp_path, monkeypatch)
    dataset_id = _add_dataset(paths)
    _add_strategy(paths, dataset_id)

    result = deletion.delete_version_branch(dataset_id, "strategy_v3")

    assert result["deleted"] == ["strategy_v3", "strategy_v4"]
    assert set(storage.list_signals(dataset_id)["indicator_name"]) == {
        "strategy",
        "strategy_v2",
    }
    assert (paths["indicators"] / "strategy_v2.pine").exists()
    assert not (paths["indicators"] / "strategy_v3.pine").exists()
    assert not (paths["versions"] / "strategy_v4.json").exists()
    assert not (paths["samples"] / "win" / "strategy_v3.json.gz").exists()


def test_delete_strategy_keeps_market_file(tmp_path, monkeypatch):
    paths = _prepare_workspace(tmp_path, monkeypatch)
    dataset_id = _add_dataset(paths)
    _add_strategy(paths, dataset_id)
    market_file = paths["market"] / "BTCUSDT_15m.csv"

    result = deletion.delete_strategy(dataset_id, "strategy")

    assert result["signals"] == 4
    assert storage.list_signals(dataset_id).empty
    assert market_file.exists()
    assert not list(paths["indicators"].glob("strategy*.pine"))
    assert not list(paths["versions"].glob("strategy*.json"))


def test_delete_market_removes_owned_market_and_all_artifacts(tmp_path, monkeypatch):
    paths = _prepare_workspace(tmp_path, monkeypatch)
    dataset_id = _add_dataset(paths)
    _add_strategy(paths, dataset_id)

    result = deletion.delete_market(dataset_id)

    assert result["market_file_deleted"] is True
    assert storage.list_datasets().empty
    assert storage.list_signals().empty
    assert not (paths["market"] / "BTCUSDT_15m.csv").exists()
    assert not list(paths["indicators"].glob("strategy*.pine"))
    assert not list(paths["versions"].glob("strategy*.json"))
