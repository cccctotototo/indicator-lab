import numpy as np
import pandas as pd

from quant_labeler.features import FEATURE_COLUMNS, add_features, forward_outcome


def candle_frame(rows=100):
    close = np.linspace(100, 130, rows) + np.sin(np.arange(rows))
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
        "open": close - 0.2,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.linspace(10, 30, rows),
    })


def test_add_features_is_length_preserving():
    result = add_features(candle_frame())
    assert len(result) == 100
    assert set(FEATURE_COLUMNS).issubset(result.columns)
    assert result.iloc[-1]["rsi_14"] >= 0


def test_forward_long_and_short_have_opposite_pnl():
    frame = candle_frame()
    long = forward_outcome(frame, 50, "long", 10)
    short = forward_outcome(frame, 50, "short", 10)
    assert np.isclose(long["pnl_pct"], -short["pnl_pct"])
    assert long["entry_price"] == short["entry_price"]
