from __future__ import annotations

import re

import pandas as pd

from .config import INDICATORS_DIR
from .indicators import signals_to_records
from .pine_runtime import compute_pine_signals
from .storage import get_dataset, list_signals, register_signals


def normalize_strategy_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    if not name:
        raise ValueError("策略名稱不能是空白，請使用英文字母、數字或底線。")
    if re.search(r"_v\d+$", name):
        raise ValueError("匯入的是原始 V1，名稱不需要加 _v2、_v3 等版本尾碼。")
    return name


def _validate_source(source: str) -> str:
    source = source.strip()
    if not source:
        raise ValueError("請貼上或上傳 Pine 指標原碼。")
    if len(source.encode("utf-8")) > 1_000_000:
        raise ValueError("Pine 原碼超過 1 MB，請移除不必要的內容後再匯入。")
    version = re.search(r"//@version=(\d+)", source)
    if not version:
        raise ValueError("找不到 //@version，請提供完整的 Pine 指標原碼。")
    if not re.search(r"\bindicator\s*\(", source):
        if re.search(r"\bstrategy\s*\(", source):
            raise ValueError("目前是指標訓練工具，請匯入 indicator()，不是 strategy()。")
        raise ValueError("找不到 indicator()，請提供完整的 Pine 指標原碼。")
    return source


def import_strategy_v1(
    dataset_id: int,
    frame: pd.DataFrame,
    strategy_name: str,
    pine_source: str,
    *,
    long_expression: str | None = None,
    short_expression: str | None = None,
) -> dict:
    """Create an immutable V1 by executing the indicator through PineTS."""
    name = normalize_strategy_name(strategy_name)
    source = _validate_source(pine_source)
    pine_path = INDICATORS_DIR / f"{name}.pine"
    if pine_path.exists() or not list_signals(dataset_id, name).empty:
        raise ValueError(
            f"策略 {name} 已存在；請刪除原策略或使用不同名稱，原始 V1 不會被覆蓋。"
        )

    dataset = get_dataset(dataset_id)
    output = compute_pine_signals(
        frame.copy(),
        source,
        ticker=str(dataset.get("symbol") or "LOCAL"),
        timeframe=str(dataset.get("interval") or "15m"),
        timezone=str(dataset.get("timezone") or "UTC"),
        exchange_timezone="Etc/UTC",
        long_expression=long_expression,
        short_expression=short_expression,
    )
    detected_long_expression = str(output.attrs.get("long_expression") or "")
    detected_short_expression = str(output.attrs.get("short_expression") or "")
    output.insert(0, "timestamp", pd.to_datetime(frame["timestamp"], utc=True))
    records = signals_to_records(output)
    if not records:
        raise ValueError(
            "PineTS 已成功執行指標，但這份行情沒有出現做多或做空訊號。"
        )

    pine_path.write_text(source + "\n", encoding="utf-8")
    try:
        added = register_signals(
            dataset_id,
            name,
            f"pinets:{pine_path.name}",
            records,
        )
    except Exception:
        pine_path.unlink(missing_ok=True)
        raise
    if added == 0:
        pine_path.unlink(missing_ok=True)
        raise ValueError("訊號已存在，沒有新增任何資料。")

    counts = {
        direction: sum(record["direction"] == direction for record in records)
        for direction in ("long", "short")
    }
    return {
        "dataset_id": int(dataset_id),
        "indicator_name": name,
        "signals": int(added),
        "long": int(counts["long"]),
        "short": int(counts["short"]),
        "engine": "PineTS",
        "pine_path": str(pine_path),
        "long_expression": detected_long_expression,
        "short_expression": detected_short_expression,
    }
