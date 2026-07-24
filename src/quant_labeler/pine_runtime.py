"""Execute TradingView indicators with the local PineTS runtime.

This module intentionally contains no Pine expression parser or indicator
implementation.  Pine syntax and series semantics are delegated to PineTS.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pandas as pd

from .config import PROJECT_ROOT

RUNNER_PATH = PROJECT_ROOT / "runtime" / "pinets_runner.mjs"


def _node_executable() -> str:
    executable = shutil.which("node")
    if not executable:
        raise RuntimeError(
            "找不到 Node.js。PineTS 需要 Node.js 20 以上版本，請先安裝再重新啟動。"
        )
    return executable


def _timestamps_in_ms(frame: pd.DataFrame) -> np.ndarray:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    return (timestamps.astype("int64") // 1_000_000).to_numpy(dtype=np.int64)


def _bar_duration_ms(timestamps: np.ndarray) -> int:
    if len(timestamps) > 1:
        differences = np.diff(timestamps)
        positive = differences[differences > 0]
        if len(positive):
            return int(np.median(positive))
    return 60_000


def _infer_mintick(frame: pd.DataFrame) -> float:
    values = pd.concat(
        [pd.to_numeric(frame[column], errors="coerce") for column in ("open", "high", "low", "close")],
        ignore_index=True,
    ).dropna()
    if values.empty:
        return 0.01
    rendered = values.tail(2_000).map(lambda value: f"{float(value):.12f}".rstrip("0"))
    decimals = rendered.map(
        lambda value: len(value.split(".", 1)[1]) if "." in value else 0
    )
    return float(10 ** (-min(int(decimals.max()), 12)))


def _bars_payload(frame: pd.DataFrame) -> list[dict]:
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"K 線缺少欄位：{', '.join(missing)}")
    if frame.empty:
        raise ValueError("K 線資料是空的。")

    timestamps = _timestamps_in_ms(frame)
    duration = _bar_duration_ms(timestamps)
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric.isna().any().any():
        raise ValueError("K 線含有無法計算的價格或成交量。")

    bars: list[dict] = []
    for index, row in enumerate(numeric.itertuples(index=False)):
        open_time = int(timestamps[index])
        bars.append(
            {
                "openTime": open_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "closeTime": open_time + duration - 1,
            }
        )
    return bars


def compute_pine_signals(
    frame: pd.DataFrame,
    source: str,
    *,
    ticker: str = "LOCAL",
    timeframe: str = "15m",
    timezone: str = "UTC",
    exchange_timezone: str = "Etc/UTC",
    mintick: float | None = None,
    long_expression: str | None = None,
    short_expression: str | None = None,
    timeout: int = 180,
) -> pd.DataFrame:
    """Run an indicator in PineTS and return aligned long/short signal columns."""
    if not RUNNER_PATH.exists():
        raise RuntimeError(f"找不到 PineTS 執行器：{RUNNER_PATH}")
    package_path = PROJECT_ROOT / "node_modules" / "pinets" / "package.json"
    if not package_path.exists():
        raise RuntimeError(
            "PineTS 尚未安裝。請執行 npm.cmd install，或重新執行啟動程式。"
        )

    payload = {
        "source": source,
        "bars": _bars_payload(frame),
        "ticker": ticker or "LOCAL",
        "timeframe": timeframe or "15m",
        "timezone": timezone or "UTC",
        "exchangeTimezone": exchange_timezone or "Etc/UTC",
        "mintick": float(mintick) if mintick is not None else _infer_mintick(frame),
        "longExpression": long_expression or "",
        "shortExpression": short_expression or "",
    }
    try:
        result = subprocess.run(
            [_node_executable(), str(RUNNER_PATH)],
            cwd=PROJECT_ROOT,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"PineTS 執行超過 {timeout} 秒；請縮短資料範圍或檢查指標是否有大量迴圈。"
        ) from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        try:
            detail = json.loads(detail).get("error", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ValueError(f"PineTS 執行失敗：{detail}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PineTS 回傳格式錯誤。") from exc

    long_values = output.get("long", [])
    short_values = output.get("short", [])
    if len(long_values) != len(frame) or len(short_values) != len(frame):
        raise RuntimeError("PineTS 訊號數量與 K 線數量不一致。")
    signals = pd.DataFrame(
        {
            "long_signal": pd.Series(long_values, index=frame.index, dtype=bool),
            "short_signal": pd.Series(short_values, index=frame.index, dtype=bool),
        },
        index=frame.index,
    )
    signals.attrs["engine"] = output.get("engine", "PineTS")
    signals.attrs["long_expression"] = output.get("longExpression", "")
    signals.attrs["short_expression"] = output.get("shortExpression", "")
    signals.attrs["warnings"] = output.get("warnings", [])
    return signals
