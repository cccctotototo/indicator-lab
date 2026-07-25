from __future__ import annotations

import pandas as pd

from quant_labeler import api


def test_health_identifies_react_frontend():
    assert api.health() == {
        "status": "ok",
        "product": "Indicator Lab",
        "frontend": "react",
    }


def test_review_returns_chart_window_and_newest_unlabeled(monkeypatch):
    timestamps = pd.date_range("2026-01-01", periods=80, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": range(80),
            "high": [value + 2 for value in range(80)],
            "low": [value - 1 for value in range(80)],
            "close": [value + 1 for value in range(80)],
            "volume": [100.0] * 80,
        }
    )
    signals = pd.DataFrame(
        [
            {
                "id": 1,
                "timestamp": timestamps[30],
                "direction": "long",
                "label": "win",
                "notes": "",
                "pnl_pct": 1.2,
                "bars_held": 20,
                "indicator_name": "demo",
            },
            {
                "id": 2,
                "timestamp": timestamps[50],
                "direction": "short",
                "label": None,
                "notes": "",
                "pnl_pct": None,
                "bars_held": None,
                "indicator_name": "demo",
            },
        ]
    )
    monkeypatch.setattr(
        api,
        "_market_frame",
        lambda dataset_id: (
            {"id": dataset_id, "symbol": "BTCUSDT", "interval": "15m"},
            frame,
        ),
    )
    monkeypatch.setattr(api, "list_review_signals", lambda dataset_id, indicator: signals)

    result = api.review(1, "demo", None, 20, 10)

    assert result["selected"]["id"] == 2
    assert result["summary"]["total"] == 2
    assert result["summary"]["labeled"] == 1
    assert len(result["candles"]) == 31
    assert result["signals"] == [{"id": 2, "label": None}, {"id": 1, "label": "win"}]


def test_label_endpoint_reuses_cached_market_frame(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(api, "get_signal", lambda signal_id: {"id": signal_id, "dataset_id": 4})
    monkeypatch.setattr(api, "_market_frame", lambda dataset_id: ({"id": dataset_id}, "cached-frame"))

    def fake_save(signal_id, label, **kwargs):
        calls.update({"signal_id": signal_id, "label": label, **kwargs})
        return {"classification": {"label": label}}

    monkeypatch.setattr(api, "save_label_snapshot", fake_save)
    result = api.label_signal(99, api.LabelRequest(label="loss", notes="test"))

    assert result["saved"] is True
    assert calls["frame"] == "cached-frame"
    assert calls["label"] == "loss"
