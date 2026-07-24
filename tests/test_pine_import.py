from __future__ import annotations

from io import StringIO

import numpy as np
import pandas as pd

import quant_labeler.strategy_import as strategy_import
from quant_labeler.pine_runtime import compute_pine_signals


PINE = '''//@version=6
indicator("Wickless", overlay = true)
showLong = input.bool(true, "顯示做多")
showShort = input.bool(true, "顯示做空")
allowedWickTicks = input.int(0, "容許影線", minval = 0,
     tooltip = "零代表沒有影線")
maxOppositeWickRatio = input.float(0.40, "另一側影線／實體上限")
maxWickLength = allowedWickTicks * syminfo.mintick
bodySize = math.abs(close - open)
lowerWick = math.min(open, close) - low
upperWick = high - math.max(open, close)
longSignal = barstate.isconfirmed and close > open and
     lowerWick <= maxWickLength and upperWick <= bodySize * maxOppositeWickRatio
shortSignal = barstate.isconfirmed and close < open and
     upperWick <= maxWickLength and lowerWick <= bodySize * maxOppositeWickRatio
plotshape(
     showLong and longSignal,
     title = "做多",
     location = location.belowbar)
plotshape(showShort and shortSignal, title = "做空")
'''


def _frame() -> pd.DataFrame:
    open_ = np.array([100.0, 101.0, 100.0, 102.0, 101.0, 103.0])
    close = np.array([101.0, 100.0, 102.0, 101.0, 103.0, 102.0])
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=len(open_), freq="15min", tz="UTC"),
            "open": open_,
            "high": np.maximum(open_, close) + np.array([0.2, 0.0, 0.2, 0.0, 0.2, 0.0]),
            "low": np.minimum(open_, close) - np.array([0.0, 0.2, 0.0, 0.2, 0.0, 0.2]),
            "close": close,
            "volume": 1000.0,
        }
    )


def test_common_pine_is_parsed_with_both_long_and_short_signals():
    output = compute_pine_signals(_frame(), PINE)

    assert output["long_signal"].tolist() == [True, False, True, False, True, False]
    assert output["short_signal"].tolist() == [False, True, False, True, False, True]


def test_pine_ternary_expression_is_supported():
    frame = _frame()
    source = '''//@version=6
indicator("Ternary", overlay = true)
aiV4Range = ta.highest(high, 2) - ta.lowest(low, 2)
aiV4ClosePosition = aiV4Range != 0 ? (close - ta.lowest(low, 2)) / aiV4Range : 0.5
longSignal = aiV4ClosePosition >= 0.5
shortSignal = aiV4ClosePosition < 0.5
'''

    output = compute_pine_signals(frame, source)

    assert output["long_signal"].tolist() == [False, False, True, False, True, False]
    assert output["short_signal"].tolist() == [False, True, False, True, False, True]


def test_web_import_creates_v1_pine_adapter_and_registered_signals(tmp_path, monkeypatch):
    indicators = tmp_path / "indicators"
    adapters = tmp_path / "adapters"
    indicators.mkdir()
    adapters.mkdir()
    monkeypatch.setattr(strategy_import, "INDICATORS_DIR", indicators)
    monkeypatch.setattr(strategy_import, "ADAPTERS_DIR", adapters)
    monkeypatch.setattr(strategy_import, "list_signals", lambda *_: pd.DataFrame())
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
    assert len(captured) == 6
    assert (indicators / "my_strategy.pine").exists()
    assert (adapters / "my_strategy.py").exists()


def test_full_pine_source_with_unsupported_syntax_imports_via_signal_csv(
    tmp_path, monkeypatch
):
    indicators = tmp_path / "indicators"
    adapters = tmp_path / "adapters"
    indicators.mkdir()
    adapters.mkdir()
    monkeypatch.setattr(strategy_import, "INDICATORS_DIR", indicators)
    monkeypatch.setattr(strategy_import, "ADAPTERS_DIR", adapters)
    monkeypatch.setattr(strategy_import, "list_signals", lambda *_: pd.DataFrame())
    captured = []
    monkeypatch.setattr(
        strategy_import,
        "register_signals",
        lambda dataset_id, name, source, records: captured.extend(records) or len(records),
    )
    source = '''//@version=6
strategy("Any Pine", overlay=true)
var float state = na
state := request.security(syminfo.tickerid, "60", close)
if ta.crossover(close, state)
    strategy.entry("Long", strategy.long)
'''
    csv = StringIO(
        "timestamp,direction\n"
        f"{_frame().iloc[0].timestamp.isoformat()},long\n"
        f"{_frame().iloc[1].timestamp.isoformat()},short\n"
    )

    result = strategy_import.import_strategy_v1(
        7,
        _frame(),
        "Any Pine",
        source,
        signal_csv=csv,
    )

    assert result["signals"] == 2
    assert result["adapter_ready"] is False
    assert len(captured) == 2
    assert (indicators / "any_pine.pine").read_text(encoding="utf-8").startswith(
        "//@version=6"
    )
    assert not (adapters / "any_pine.py").exists()
