from __future__ import annotations

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "return_1",
    "return_3",
    "return_12",
    "range_pct",
    "body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "atr_pct",
    "rsi_14",
    "ema_9_gap",
    "ema_21_gap",
    "ema_50_gap",
    "trend_9_21",
    "volatility_20",
    "volume_z20",
    "volume_ratio_20",
    "close_position_20",
    "hour_sin",
    "hour_cos",
]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with causal, candle-close features only."""
    df = frame.copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)
    safe_close = close.replace(0, np.nan)

    df["return_1"] = close.pct_change(1)
    df["return_3"] = close.pct_change(3)
    df["return_12"] = close.pct_change(12)
    df["range_pct"] = (high - low) / safe_close
    df["body_pct"] = (close - open_) / safe_close
    df["upper_wick_pct"] = (high - pd.concat([open_, close], axis=1).max(axis=1)) / safe_close
    df["lower_wick_pct"] = (pd.concat([open_, close], axis=1).min(axis=1) - low) / safe_close

    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    df["atr_pct"] = true_range.ewm(alpha=1 / 14, adjust=False).mean() / safe_close
    df["rsi_14"] = _rsi(close)

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    df["ema_9_gap"] = close / ema9 - 1
    df["ema_21_gap"] = close / ema21 - 1
    df["ema_50_gap"] = close / ema50 - 1
    df["trend_9_21"] = ema9 / ema21 - 1
    df["volatility_20"] = close.pct_change().rolling(20, min_periods=5).std()

    vol_mean = volume.rolling(20, min_periods=5).mean()
    vol_std = volume.rolling(20, min_periods=5).std().replace(0, np.nan)
    df["volume_z20"] = (volume - vol_mean) / vol_std
    df["volume_ratio_20"] = volume / vol_mean.replace(0, np.nan)
    low20 = low.rolling(20, min_periods=5).min()
    high20 = high.rolling(20, min_periods=5).max()
    df["close_position_20"] = (close - low20) / (high20 - low20).replace(0, np.nan)

    ts = pd.to_datetime(df["timestamp"], utc=True)
    hours = ts.dt.hour + ts.dt.minute / 60
    df["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    return df


def forward_outcome(
    frame: pd.DataFrame, signal_index: int, direction: str, bars: int = 20
) -> dict[str, float]:
    if signal_index < 0 or signal_index >= len(frame):
        raise IndexError("訊號索引超出行情範圍")
    entry = float(frame.iloc[signal_index]["close"])
    future = frame.iloc[signal_index + 1 : signal_index + 1 + max(1, bars)]
    if future.empty:
        return {"entry_price": entry, "exit_price": entry, "pnl_pct": 0.0, "mfe_pct": 0.0, "mae_pct": 0.0}
    sign = 1.0 if direction == "long" else -1.0
    pnl = sign * (float(future.iloc[-1]["close"]) / entry - 1) * 100
    if direction == "long":
        favorable = (future["high"].max() / entry - 1) * 100
        adverse = (future["low"].min() / entry - 1) * 100
    else:
        favorable = (1 - future["low"].min() / entry) * 100
        adverse = (1 - future["high"].max() / entry) * 100
    return {
        "entry_price": entry,
        "exit_price": float(future.iloc[-1]["close"]),
        "pnl_pct": float(pnl),
        "mfe_pct": float(max(0, favorable)),
        "mae_pct": float(min(0, adverse)),
    }
