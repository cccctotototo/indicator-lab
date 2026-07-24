from __future__ import annotations

import numpy as np
import pandas as pd

from quant_labeler import strategy_import
from quant_labeler.pine_runtime import compute_pine_signals

PINE = """//@version=6
indicator("Wickless", overlay = true)
longSignal = close > open
shortSignal = close < open
plotshape(longSignal, title = "做多", location = location.belowbar)
plotshape(shortSignal, title = "做空", location = location.abovebar)
"""


def _frame() -> pd.DataFrame:
    open_ = np.array([100.0, 101.0, 100.0, 102.0, 101.0, 103.0])
    close = np.array([101.0, 100.0, 102.0, 101.0, 103.0, 102.0])
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-01-01", periods=len(open_), freq="15min", tz="UTC"
            ),
            "open": open_,
            "high": np.maximum(open_, close) + 0.2,
            "low": np.minimum(open_, close) - 0.2,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_pinets_executes_both_long_and_short_signals():
    output = compute_pine_signals(_frame(), PINE)

    assert output["long_signal"].tolist() == [True, False, True, False, True, False]
    assert output["short_signal"].tolist() == [False, True, False, True, False, True]
    assert output.attrs["engine"] == "PineTS"


def test_pinets_supports_ternary_and_state_assignment():
    source = """//@version=6
indicator("Stateful", overlay = true)
var float previous = na
previous := close[1]
rangeValue = ta.highest(high, 2) - ta.lowest(low, 2)
position = rangeValue != 0 ? (close - ta.lowest(low, 2)) / rangeValue : 0.5
longSignal = not na(previous) and close > previous and position >= 0.5
shortSignal = not na(previous) and close < previous and position < 0.5
"""

    output = compute_pine_signals(_frame(), source)

    assert output["long_signal"].sum() > 0
    assert output["short_signal"].sum() > 0


def test_pinets_infers_custom_signal_names_from_plotshape():
    source = """//@version=6
indicator("Custom names", overlay = true)
bullish = close > open
bearish = close < open
plotshape(bullish, title = "做多", location = location.belowbar)
plotshape(bearish, title = "做空", location = location.abovebar)
"""

    output = compute_pine_signals(_frame(), source)

    assert output.attrs["long_expression"] == "bullish"
    assert output.attrs["short_expression"] == "bearish"


def test_pinets_prefers_entry_variables_over_auxiliary_plot_conditions():
    source = """//@version=6
indicator("Entry priority", overlay = true)
pullbackLong = close > open
pullbackShort = close < open
longEntry = pullbackLong and close > close[1]
shortEntry = pullbackShort and close < close[1]
plotshape(pullbackLong, title = "Long pullback", location = location.belowbar)
plotshape(longEntry, title = "Long entry", location = location.belowbar)
plotshape(pullbackShort, title = "Short pullback", location = location.abovebar)
plotshape(shortEntry, title = "Short entry", location = location.abovebar)
"""

    output = compute_pine_signals(_frame(), source)

    assert output.attrs["long_expression"] == "longEntry"
    assert output.attrs["short_expression"] == "shortEntry"
    assert output["long_signal"].tolist() == [False, False, True, False, True, False]
    assert output["short_signal"].tolist() == [False, True, False, True, False, True]


def test_pinets_keeps_log_output_out_of_json_protocol():
    source = """//@version=6
indicator("Logging", overlay = true)
longSignal = close > open
shortSignal = close < open
if longSignal
    log.info("close {0}", close)
"""

    output = compute_pine_signals(_frame(), source)

    assert len(output) == len(_frame())
    assert output.attrs["warnings"]


def test_web_import_creates_v1_pine_and_registered_signals(tmp_path, monkeypatch):
    indicators = tmp_path / "indicators"
    indicators.mkdir()
    monkeypatch.setattr(strategy_import, "INDICATORS_DIR", indicators)
    monkeypatch.setattr(strategy_import, "list_signals", lambda *_: pd.DataFrame())
    monkeypatch.setattr(
        strategy_import,
        "get_dataset",
        lambda *_: {
            "symbol": "BTCUSDT",
            "interval": "15m",
            "timezone": "Asia/Taipei",
        },
    )
    captured = []
    monkeypatch.setattr(
        strategy_import,
        "register_signals",
        lambda dataset_id, name, source, records: captured.extend(records) or len(records),
    )

    result = strategy_import.import_strategy_v1(7, _frame(), "My Strategy", PINE)

    assert result["indicator_name"] == "my_strategy"
    assert result["long"] == 3
    assert result["short"] == 3
    assert result["engine"] == "PineTS"
    assert len(captured) == 6
    assert (indicators / "my_strategy.pine").exists()
