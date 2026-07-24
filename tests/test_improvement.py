import json

import numpy as np
import pandas as pd
import pytest

import quant_labeler.improvement as improvement
from quant_labeler.improvement import (
    feature_comparison,
    find_directional_filters,
    find_stable_filter,
)


def _training_rows() -> pd.DataFrame:
    rows = 120
    low_volatility = np.arange(rows) % 2 == 0
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC"),
            "label_text": np.where(low_volatility, "win", "loss"),
            "direction": np.where(np.arange(rows) % 4 < 2, "long", "short"),
            "rsi_14": np.linspace(35, 65, rows),
            "volume_ratio_20": np.linspace(0.7, 1.3, rows),
            "trend_9_21": np.linspace(-0.01, 0.01, rows),
            "volatility_20": np.where(low_volatility, 0.001, 0.01)
            + np.arange(rows) * 0.0000001,
            "close_position_20": np.linspace(0.1, 0.9, rows),
        }
    )


def test_comparison_and_filter_explain_winners_and_reduce_losses():
    data = _training_rows()

    comparison = feature_comparison(data)
    volatility = comparison.loc[comparison["feature"] == "volatility_20"].iloc[0]
    result = find_stable_filter(data)

    assert volatility["winner_tendency"] == "較低"
    assert volatility["loser_tendency"] == "較高"
    assert result["filtered"]["validation"]["win_rate"] > result["baseline"]["validation"]["win_rate"]
    assert result["removed_losses"] > result["removed_wins"]


def test_directional_filters_train_long_and_short_without_disabling_either():
    result = find_directional_filters(_training_rows())

    assert result["long"]["rules"]
    assert result["short"]["rules"]
    assert result["long"]["filtered"]["validation"]["win_rate"] > result["long"]["baseline"]["validation"]["win_rate"]
    assert result["short"]["filtered"]["validation"]["win_rate"] > result["short"]["baseline"]["validation"]["win_rate"]


def test_generated_versions_preserve_both_original_signal_conditions(tmp_path, monkeypatch):
    monkeypatch.setattr(improvement, "INDICATORS_DIR", tmp_path)
    (tmp_path / "parent.pine").write_text(
        """//@version=6
indicator("Parent", overlay=true)
longSignal = close > open
shortSignal = close < open
plotshape(showLong and longSignal)
plotshape(showShort and shortSignal)
alertcondition(longSignal)
alertcondition(shortSignal)
""",
        encoding="utf-8",
    )
    long_rules = [{"feature": "volatility_20", "op": "le", "value": 0.01}]
    short_rules = [{"feature": "rsi_14", "op": "ge", "value": 40.0}]

    pine = improvement._write_pine("parent", "parent_v2", 2, long_rules, short_rules)
    pine_text = pine.read_text(encoding="utf-8")

    assert "improvedLongSignal = (longSignal) and aiV2LongFilter" in pine_text
    assert "improvedShortSignal = (shortSignal) and aiV2ShortFilter" in pine_text
    assert "and false" not in pine_text.lower()


def test_generated_filter_is_inserted_after_late_signal_declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(improvement, "INDICATORS_DIR", tmp_path)
    (tmp_path / "late_signals.pine").write_text(
        """//@version=6
indicator("Late signals", overlay=true)
showEntry = input.bool(true)
earlyCross = ta.crossover(close, open)
alertcondition(earlyCross, title="一般提醒")
var bool waitingLong = false
var bool waitingShort = false
longEntry = waitingLong and close > open
shortEntry = waitingShort and close < open
if longEntry
    waitingLong := false
if shortEntry
    waitingShort := false
plotshape(showEntry and longEntry, title="做多")
plotshape(showEntry and shortEntry, title="做空")
alertcondition(longEntry, title="做多進場")
alertcondition(shortEntry, title="做空進場")
""",
        encoding="utf-8",
    )

    pine = improvement._write_pine(
        "late_signals",
        "late_signals_v2",
        2,
        [],
        [],
        "(longEntry) or (showEntry and longEntry)",
        "(shortEntry) or (showEntry and shortEntry)",
    )
    pine_text = pine.read_text(encoding="utf-8")

    assert pine_text.index("longEntry =") < pine_text.index("improvedLongSignal =")
    assert pine_text.index("shortEntry =") < pine_text.index("improvedShortSignal =")
    assert pine_text.index("improvedLongSignal =") < pine_text.index("plotshape(")
    assert "alertcondition(earlyCross" in pine_text
    assert 'plotshape(showEntry and improvedLongSignal, title="做多")' in pine_text
    assert 'plotshape(showEntry and improvedShortSignal, title="做空")' in pine_text
    assert 'alertcondition(improvedLongSignal, title="做多進場")' in pine_text
    assert 'alertcondition(improvedShortSignal, title="做空進場")' in pine_text


def test_direction_gain_is_kept_even_when_trade_mix_lowers_combined_rate(monkeypatch):
    data = _training_rows().iloc[:20].copy()
    data["direction"] = ["long"] * 10 + ["short"] * 10
    data["label_text"] = ["win"] * 9 + ["loss"] + ["win", "loss"] * 5

    def fake_filter(side):
        if side["direction"].iloc[0] == "short":
            raise ValueError("no short improvement")
        return {
            "rules": [{"feature": "rsi_14", "op": "ge", "value": 50.0}],
            "rule_text": "RSI 14 ≥ 50",
            "baseline": {
                "all": {"samples": 10, "wins": 9, "losses": 1, "win_rate": 90.0},
                "train": {"samples": 6, "wins": 5, "losses": 1, "win_rate": 83.33},
                "validation": {"samples": 4, "wins": 4, "losses": 0, "win_rate": 100.0},
            },
            "filtered": {
                "all": {"samples": 5, "wins": 5, "losses": 0, "win_rate": 100.0},
                "train": {"samples": 3, "wins": 3, "losses": 0, "win_rate": 100.0},
                "validation": {"samples": 2, "wins": 2, "losses": 0, "win_rate": 100.0},
            },
            "removed_losses": 1,
            "removed_wins": 4,
            "score": 1.0,
        }

    monkeypatch.setattr(improvement, "find_stable_filter", fake_filter)

    result = improvement.find_directional_filters(data)

    assert result["improved_directions"] == ["long"]
    assert result["long"]["rules"]
    assert result["short"]["rules"] == []
    assert result["filtered"]["all"]["win_rate"] < result["baseline"]["all"]["win_rate"]


def test_short_gain_is_kept_when_long_has_no_improvement(monkeypatch):
    data = _training_rows().iloc[:20].copy()
    data["direction"] = ["long"] * 10 + ["short"] * 10

    def fake_filter(side):
        direction = side["direction"].iloc[0]
        if direction == "long":
            raise ValueError("no long improvement")
        return {
            "rules": [{"feature": "volume_ratio_20", "op": "ge", "value": 0.8}],
            "rule_text": "量能／20 根均量 ≥ 0.8",
            "baseline": {
                "all": {"samples": 10, "wins": 5, "losses": 5, "win_rate": 50.0},
                "train": {"samples": 6, "wins": 3, "losses": 3, "win_rate": 50.0},
                "validation": {"samples": 4, "wins": 2, "losses": 2, "win_rate": 50.0},
            },
            "filtered": {
                "all": {"samples": 6, "wins": 5, "losses": 1, "win_rate": 83.33},
                "train": {"samples": 3, "wins": 3, "losses": 0, "win_rate": 100.0},
                "validation": {"samples": 3, "wins": 2, "losses": 1, "win_rate": 66.67},
            },
            "removed_losses": 4,
            "removed_wins": 0,
            "score": 1.0,
        }

    monkeypatch.setattr(improvement, "find_stable_filter", fake_filter)

    result = improvement.find_directional_filters(data)

    assert result["improved_directions"] == ["short"]
    assert result["long"]["rules"] == []
    assert result["short"]["rules"]


def test_no_version_when_neither_direction_improves(monkeypatch):
    data = _training_rows().iloc[:20].copy()
    data["direction"] = ["long"] * 10 + ["short"] * 10
    monkeypatch.setattr(
        improvement,
        "find_stable_filter",
        lambda _side: (_ for _ in ()).throw(ValueError("no improvement")),
    )

    with pytest.raises(ValueError, match="兩邊都沒有通過"):
        improvement.find_directional_filters(data)


def test_unlabeled_signals_and_small_samples_do_not_block_analysis(tmp_path, monkeypatch):
    signals = pd.DataFrame(
        {
            "label": ["win", "loss"] * 25 + [None] * 100,
        }
    )
    training = _training_rows().iloc[:49].copy()
    monkeypatch.setattr(improvement, "STRATEGY_VERSIONS_DIR", tmp_path)
    monkeypatch.setattr(improvement, "list_signals", lambda *_: signals)

    def labeled_training(dataset_id, indicator_name, *, labeled_only):
        assert dataset_id == 7
        assert indicator_name == "strategy"
        assert labeled_only is True
        return training

    monkeypatch.setattr(improvement, "build_training_frame", labeled_training)

    with pytest.raises(ValueError, match="兩邊都沒有通過"):
        improvement.improve_indicator(7, "strategy")


def test_single_win_produces_analysis_and_feature_profile(monkeypatch):
    signals = pd.DataFrame(
        {
            "label": ["win", None],
            "direction": ["long", "short"],
        }
    )
    training = _training_rows().iloc[:1].copy()
    training["label_text"] = "win"
    monkeypatch.setattr(improvement, "list_signals", lambda *_: signals)
    monkeypatch.setattr(improvement, "build_training_frame", lambda *_, **__: training)

    result = improvement.analyze_indicator(7, "strategy")

    assert result["decisive"] == 1
    assert result["remaining"] == 1
    assert result["overall"]["win_rate"] == 100.0
    assert result["feature_comparison"] == []
    assert result["feature_profile"]


def test_generated_version_delete_is_scoped_and_removes_its_artifacts(tmp_path, monkeypatch):
    indicators = tmp_path / "indicators"
    versions = tmp_path / "data" / "strategy_versions"
    samples = tmp_path / "data" / "samples"
    for folder in (indicators, versions, samples / "win"):
        folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(improvement, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(improvement, "INDICATORS_DIR", indicators)
    monkeypatch.setattr(improvement, "STRATEGY_VERSIONS_DIR", versions)
    monkeypatch.setattr(improvement, "SAMPLES_DIR", samples)

    child = "strategy_v2"
    metadata = {
        "root": "strategy",
        "parent": "strategy",
        "child": child,
        "version": 2,
        "dataset_id": 7,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (versions / f"{child}.json").write_text(json.dumps(metadata), encoding="utf-8")
    (indicators / f"{child}.pine").write_text("pine", encoding="utf-8")
    sample = samples / "win" / "signal.json.gz"
    sample.write_text("sample", encoding="utf-8")
    monkeypatch.setattr(
        improvement,
        "list_signals",
        lambda *_: pd.DataFrame({"sample_path": ["data/samples/win/signal.json.gz"]}),
    )
    deleted = []
    monkeypatch.setattr(
        improvement,
        "delete_indicator_signals",
        lambda dataset_id, name: deleted.append((dataset_id, name)) or 3,
    )

    result = improvement.delete_improvement_version(7, child)

    assert result["signals"] == 3
    assert deleted == [(7, child)]
    assert not sample.exists()
    assert not (indicators / f"{child}.pine").exists()
    assert not (versions / f"{child}.json").exists()
