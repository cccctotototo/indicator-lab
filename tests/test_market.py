import pandas as pd
import pytest

import quant_labeler.market as market
from quant_labeler.market import normalize_market_frame


def test_normalize_aliases_and_sort():
    frame = pd.DataFrame({
        "Time": ["2026-01-02", "2026-01-01"],
        "Open": [2, 1], "High": [3, 2], "Low": [1, 0], "Close": [2.5, 1.5], "Vol": [20, 10],
    })
    result = normalize_market_frame(frame)
    assert list(result.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert result.iloc[0]["close"] == 1.5
    assert str(result["timestamp"].dt.tz) == "UTC"


def test_history_cache_extends_from_recent_toward_older_data(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "MARKET_DIR", tmp_path)

    def fake_fetch(symbol, interval, start, end, market_type):
        timestamps = pd.DatetimeIndex([pd.Timestamp(start), pd.Timestamp(end)])
        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100, 101],
                "high": [102, 103],
                "low": [99, 100],
                "close": [101, 102],
                "volume": [10, 11],
            }
        )

    monkeypatch.setattr(market, "fetch_binance_klines", fake_fetch)

    recent, path, first_added = market.extend_history_backward(
        "BTCUSDT", "1h", "futures", days=30
    )
    first_start = recent["timestamp"].min()
    extended, same_path, second_added = market.extend_history_backward(
        "BTCUSDT", "1h", "futures", days=30
    )

    assert path == same_path
    assert first_added == 2
    assert second_added == 2
    assert extended["timestamp"].min() < first_start
    assert extended["timestamp"].is_monotonic_increasing


def test_full_history_sync_fills_both_ends_of_existing_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "MARKET_DIR", tmp_path)
    recent = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-02", periods=2, freq="h", tz="UTC"),
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [10, 11],
        }
    )
    market._save_history_cache(recent, "BTCUSDT", "1h", "futures")
    calls = []

    def fake_fetch(symbol, interval, start, end, market_type):
        calls.append((pd.Timestamp(start), pd.Timestamp(end)))
        timestamp = (
            pd.Timestamp("2019-09-08 00:00:00", tz="UTC")
            if pd.Timestamp(start) == market.FULL_HISTORY_START
            else pd.Timestamp(start)
        )
        return pd.DataFrame(
            {
                "timestamp": [timestamp],
                "open": [90],
                "high": [92],
                "low": [89],
                "close": [91],
                "volume": [9],
            }
        )

    monkeypatch.setattr(market, "fetch_binance_klines", fake_fetch)
    result, path, added = market.sync_full_history("BTCUSDT", "1h", "futures")

    assert path == market.history_cache_path("BTCUSDT", "1h", "futures")
    assert len(calls) == 2
    assert result["timestamp"].min() == pd.Timestamp("2019-09-08", tz="UTC")
    assert result["timestamp"].max() > recent["timestamp"].max()
    assert added == 2


def test_symbol_catalog_keeps_active_perpetuals_and_prioritizes_popular_usdt(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "symbols": [
                    {"symbol": "ALTUSDT", "baseAsset": "ALT", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"},
                    {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"},
                    {"symbol": "BTCUSDT_260925", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "contractType": "CURRENT_QUARTER"},
                    {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT", "status": "CLOSE", "contractType": "PERPETUAL"},
                ]
            }

    monkeypatch.setattr(market.requests, "get", lambda *args, **kwargs: FakeResponse())

    result = market.fetch_binance_symbols("futures")

    assert [row["symbol"] for row in result] == ["ETHUSDT", "ALTUSDT"]


def test_rate_limit_with_long_retry_after_fails_without_repeated_requests(monkeypatch):
    class FakeResponse:
        status_code = 429
        headers = {"Retry-After": "120"}

        def raise_for_status(self):
            return None

    class FakeSession:
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    session = FakeSession()
    with pytest.raises(market.BinanceRateLimitError, match="等待約 120 秒"):
        market._request_with_backoff(
            session,
            market.BINANCE_ENDPOINTS["futures"],
            params={"symbol": "BTCUSDT"},
            timeout=20,
        )

    assert session.calls == 1
