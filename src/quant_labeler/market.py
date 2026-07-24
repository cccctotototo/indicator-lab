from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

from .config import MARKET_DIR
from .features import add_features

BINANCE_ENDPOINTS = {
    "spot": "https://api.binance.com/api/v3/klines",
    "futures": "https://fapi.binance.com/fapi/v1/klines",
}

BINANCE_EXCHANGE_INFO_ENDPOINTS = {
    "spot": "https://api.binance.com/api/v3/exchangeInfo",
    "futures": "https://fapi.binance.com/fapi/v1/exchangeInfo",
}

POPULAR_BASE_ASSETS = (
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK",
    "SUI", "LTC", "BCH", "DOT", "TRX", "TON", "NEAR", "APT", "ARB",
    "OP", "PEPE", "SHIB",
)

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
FULL_HISTORY_START = pd.Timestamp("2010-01-01", tz="UTC")
BINANCE_PAGE_PAUSE_SECONDS = 0.25
BINANCE_MAX_RETRIES = 5
BINANCE_MAX_RETRY_WAIT_SECONDS = 60.0


class BinanceRateLimitError(RuntimeError):
    """Raised after Binance keeps rejecting a request due to IP rate limits."""


class BinanceEmptyDataError(ValueError):
    """Raised when Binance returns no closed candles for a requested range."""


def _request_with_backoff(
    session: requests.Session,
    url: str,
    *,
    params: dict,
    timeout: int,
):
    """Respect Binance Retry-After and retry temporary API failures."""
    last_wait = 0.0
    for attempt in range(BINANCE_MAX_RETRIES + 1):
        response = session.get(url, params=params, timeout=timeout)
        status = int(getattr(response, "status_code", 200))
        if status not in {418, 429} and not 500 <= status < 600:
            response.raise_for_status()
            return response

        if status in {418, 429}:
            retry_header = getattr(response, "headers", {}).get("Retry-After")
            try:
                requested_wait = float(retry_header) if retry_header else 0.0
            except (TypeError, ValueError):
                requested_wait = 0.0
            last_wait = max(requested_wait, min(2 ** (attempt + 1), 30))
            if last_wait > BINANCE_MAX_RETRY_WAIT_SECONDS:
                break
        else:
            last_wait = min(2 ** attempt, 8)

        if attempt == BINANCE_MAX_RETRIES:
            break
        time.sleep(last_wait)

    wait_text = max(1, round(last_wait))
    raise BinanceRateLimitError(
        f"Binance 正在限制大量歷史查詢，請等待約 {wait_text} 秒後再試；"
        "已載入的 K 線會保留。"
    )


def fetch_binance_symbols(market_type: str, timeout: int = 12) -> list[dict]:
    """Return active Binance pairs for a TradingView-style searchable selector."""
    if market_type not in BINANCE_EXCHANGE_INFO_ENDPOINTS:
        raise ValueError("市場類型必須是 spot 或 futures")
    response = requests.get(BINANCE_EXCHANGE_INFO_ENDPOINTS[market_type], timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows: list[dict] = []
    for item in payload.get("symbols", []):
        if item.get("status") != "TRADING":
            continue
        if market_type == "futures" and item.get("contractType") != "PERPETUAL":
            continue
        if market_type == "spot" and item.get("isSpotTradingAllowed") is False:
            continue
        symbol = str(item.get("symbol", "")).upper()
        base = str(item.get("baseAsset", "")).upper()
        quote = str(item.get("quoteAsset", "")).upper()
        if not symbol or not base or not quote:
            continue
        rows.append(
            {
                "symbol": symbol,
                "base_asset": base,
                "quote_asset": quote,
                "market_type": market_type,
            }
        )
    if not rows:
        raise ValueError("Binance 沒有回傳可交易市場。")
    popular_order = {asset: index for index, asset in enumerate(POPULAR_BASE_ASSETS)}
    return sorted(
        rows,
        key=lambda row: (
            row["quote_asset"] != "USDT",
            popular_order.get(row["base_asset"], len(popular_order)),
            row["symbol"],
        ),
    )


def fallback_binance_symbols(market_type: str) -> list[dict]:
    """Small offline catalog used only when Binance exchangeInfo is unavailable."""
    return [
        {
            "symbol": f"{base}USDT",
            "base_asset": base,
            "quote_asset": "USDT",
            "market_type": market_type,
        }
        for base in POPULAR_BASE_ASSETS
    ]


def load_binance_symbol_catalog(
    market_type: str, max_age_hours: int = 24
) -> tuple[list[dict], str | None]:
    """Use a local catalog first, refresh it from Binance, and remain usable offline."""
    path = MARKET_DIR / "catalog" / f"binance_{market_type}_symbols.json"
    cached: list[dict] = []
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = []
        age_seconds = time.time() - path.stat().st_mtime
        if cached and age_seconds <= max_age_hours * 3600:
            return cached, None
    try:
        rows = fetch_binance_symbols(market_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return rows, None
    except (requests.RequestException, OSError, ValueError, TypeError) as exc:
        if cached:
            return cached, "交易對目錄暫時無法更新，目前使用上次成功同步的完整清單。"
        return fallback_binance_symbols(market_type), f"交易對目錄暫時無法更新：{exc}"


def normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {"time": "timestamp", "date": "timestamp", "datetime": "timestamp", "vol": "volume"}
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"行情 CSV 缺少欄位：{', '.join(missing)}")
    raw_ts = df["timestamp"]
    if pd.api.types.is_numeric_dtype(raw_ts):
        unit = "ms" if float(raw_ts.dropna().abs().median()) > 10_000_000_000 else "s"
        df["timestamp"] = pd.to_datetime(raw_ts, unit=unit, utc=True, errors="coerce")
    else:
        df["timestamp"] = pd.to_datetime(raw_ts, utc=True, errors="coerce")
    for column in REQUIRED_COLUMNS[1:]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=REQUIRED_COLUMNS).drop_duplicates("timestamp", keep="last")
    return df.sort_values("timestamp").reset_index(drop=True)


def fetch_binance_klines(
    symbol: str,
    interval: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    market_type: str = "spot",
    timeout: int = 20,
) -> pd.DataFrame:
    if interval not in INTERVAL_MS:
        raise ValueError(f"不支援的週期：{interval}")
    if market_type not in BINANCE_ENDPOINTS:
        raise ValueError("市場類型必須是 spot 或 futures")
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[list] = []
    with requests.Session() as session:
        while cursor <= end_ms:
            response = _request_with_backoff(
                session,
                BINANCE_ENDPOINTS[market_type],
                params={"symbol": symbol.upper().replace("/", ""), "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000},
                timeout=timeout,
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0]) + INTERVAL_MS[interval]
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < 1000:
                break
            time.sleep(BINANCE_PAGE_PAUSE_SECONDS)
    if not rows:
        raise BinanceEmptyDataError(
            "Binance 沒有回傳資料，請檢查幣種、日期或市場類型。"
        )
    frame = pd.DataFrame(rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
    ])
    # Pine's barstate.isconfirmed excludes the currently forming candle.
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    frame["close_time"] = pd.to_numeric(frame["close_time"], errors="coerce")
    frame = frame[frame["close_time"] <= min(end_ms, now_ms)]
    return normalize_market_frame(frame[REQUIRED_COLUMNS])


def read_market_csv(source) -> pd.DataFrame:
    return normalize_market_frame(pd.read_csv(source))


def _write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    """Replace a market CSV only after the complete new file is on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        frame.to_csv(temporary, index=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_market_frame(frame: pd.DataFrame, symbol: str, interval: str, market_type: str) -> Path:
    enriched = add_features(normalize_market_frame(frame))
    start_tag = enriched["timestamp"].min().strftime("%Y%m%d")
    end_tag = enriched["timestamp"].max().strftime("%Y%m%d")
    safe_symbol = "".join(c for c in symbol.upper() if c.isalnum())
    path = MARKET_DIR / f"{safe_symbol}_{market_type}_{interval}_{start_tag}_{end_tag}.csv"
    _write_frame_atomic(enriched, path)
    return path


@lru_cache(maxsize=8)
def _cached_saved_frame(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_saved_frame(path: str | Path) -> pd.DataFrame:
    resolved = Path(path).resolve()
    return _cached_saved_frame(
        str(resolved),
        resolved.stat().st_mtime_ns,
    ).copy(deep=False)


def history_cache_path(symbol: str, interval: str, market_type: str) -> Path:
    safe_symbol = "".join(c for c in symbol.upper() if c.isalnum())
    return MARKET_DIR / "history" / f"{safe_symbol}_{market_type}_{interval}.csv"


def load_history_cache(symbol: str, interval: str, market_type: str) -> pd.DataFrame:
    path = history_cache_path(symbol, interval, market_type)
    return load_saved_frame(path) if path.exists() else pd.DataFrame()


def _save_history_cache(
    frame: pd.DataFrame, symbol: str, interval: str, market_type: str
) -> Path:
    path = history_cache_path(symbol, interval, market_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = add_features(normalize_market_frame(frame))
    _write_frame_atomic(enriched, path)
    return path


def extend_history_backward(
    symbol: str,
    interval: str,
    market_type: str,
    days: int = 30,
    target_start: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, Path, int]:
    """Load recent history first, then extend the local cache toward older bars."""
    cached = load_history_cache(symbol, interval, market_type)
    step = pd.to_timedelta(INTERVAL_MS[interval], unit="ms")
    if cached.empty:
        end = pd.Timestamp.now(tz="UTC")
        start = (
            pd.Timestamp(target_start)
            if target_start is not None
            else end - pd.to_timedelta(days, unit="D")
        )
    else:
        end = pd.Timestamp(cached["timestamp"].min()) - step
        start = (
            pd.Timestamp(target_start)
            if target_start is not None
            else end - pd.to_timedelta(days, unit="D")
        )
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    if start >= end:
        raise ValueError("指定日期沒有比目前最早資料更早。")
    older = fetch_binance_klines(symbol, interval, start, end, market_type)
    combined = older if cached.empty else pd.concat([older, cached], ignore_index=True)
    combined = normalize_market_frame(combined)
    path = _save_history_cache(combined, symbol, interval, market_type)
    return load_saved_frame(path), path, int(len(combined) - len(cached))


def sync_full_history(
    symbol: str,
    interval: str,
    market_type: str,
) -> tuple[pd.DataFrame, Path, int]:
    """Synchronize every closed Binance kline available for a market."""
    cached = load_history_cache(symbol, interval, market_type)
    previous_rows = len(cached)
    step = pd.to_timedelta(INTERVAL_MS[interval], unit="ms")
    now = pd.Timestamp.now(tz="UTC")
    pieces = [cached] if not cached.empty else []

    if cached.empty:
        pieces.append(
            fetch_binance_klines(
                symbol,
                interval,
                FULL_HISTORY_START,
                now,
                market_type,
            )
        )
    else:
        older_end = pd.Timestamp(cached["timestamp"].min()) - step
        if FULL_HISTORY_START < older_end:
            try:
                pieces.append(
                    fetch_binance_klines(
                        symbol,
                        interval,
                        FULL_HISTORY_START,
                        older_end,
                        market_type,
                    )
                )
            except BinanceEmptyDataError:
                pass

        newer_start = pd.Timestamp(cached["timestamp"].max()) + step
        if newer_start < now:
            try:
                pieces.append(
                    fetch_binance_klines(
                        symbol,
                        interval,
                        newer_start,
                        now,
                        market_type,
                    )
                )
            except BinanceEmptyDataError:
                pass

    combined = normalize_market_frame(pd.concat(pieces, ignore_index=True))
    path = _save_history_cache(combined, symbol, interval, market_type)
    return load_saved_frame(path), path, int(len(combined) - previous_rows)


def refresh_history_forward(
    symbol: str, interval: str, market_type: str
) -> tuple[pd.DataFrame, Path, int]:
    cached = load_history_cache(symbol, interval, market_type)
    if cached.empty:
        return extend_history_backward(symbol, interval, market_type, days=30)
    step = pd.to_timedelta(INTERVAL_MS[interval], unit="ms")
    start = pd.Timestamp(cached["timestamp"].max()) + step
    end = pd.Timestamp.now(tz="UTC")
    if start >= end:
        path = history_cache_path(symbol, interval, market_type)
        return cached, path, 0
    newer = fetch_binance_klines(symbol, interval, start, end, market_type)
    combined = normalize_market_frame(pd.concat([cached, newer], ignore_index=True))
    path = _save_history_cache(combined, symbol, interval, market_type)
    return load_saved_frame(path), path, int(len(combined) - len(cached))
