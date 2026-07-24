from __future__ import annotations

import re

import pandas as pd

from .config import ADAPTERS_DIR, INDICATORS_DIR
from .indicators import normalize_signal_csv, run_adapter, signals_to_records
from .pine_runtime import compute_pine_signals, write_pine_adapter
from .storage import list_signals, register_signals


def normalize_strategy_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    if not name:
        raise ValueError("策略名稱至少需要一個英文字母或數字。")
    if re.search(r"_v\d+$", name):
        raise ValueError("匯入的是 V1，策略名稱結尾不能使用 _v2、_v3 等版本編號。")
    return name


def _validate_source(source: str, *, require_signal_variables: bool = True) -> str:
    source = source.strip()
    if not source:
        raise ValueError("請上傳或貼上 Pine 程式碼。")
    if len(source.encode("utf-8")) > 1_000_000:
        raise ValueError("Pine 程式碼超過 1 MB，請移除不需要的內容。")
    if not re.search(r"//@version=\d+", source):
        raise ValueError("找不到 //@version，請確認這是完整 Pine 程式碼。")
    if not re.search(r"\b(?:indicator|strategy)\s*\(", source):
        raise ValueError("找不到 indicator() 或 strategy() 宣告。")
    if require_signal_variables and (
        not re.search(r"\blongSignal\s*=", source)
        or not re.search(r"\bshortSignal\s*=", source)
    ):
        raise ValueError("請將原始多空布林條件命名為 longSignal 與 shortSignal。")
    return source


def import_strategy_v1(
    dataset_id: int,
    frame: pd.DataFrame,
    strategy_name: str,
    pine_source: str,
    *,
    signal_csv=None,
) -> dict:
    """Create an immutable V1 from Pine and either parsed or imported signals."""
    name = normalize_strategy_name(strategy_name)
    generated_adapter = signal_csv is None
    source = _validate_source(
        pine_source,
        require_signal_variables=generated_adapter,
    )
    pine_path = INDICATORS_DIR / f"{name}.pine"
    adapter_path = ADAPTERS_DIR / f"{name}.py"
    if pine_path.exists() or adapter_path.exists() or not list_signals(dataset_id, name).empty:
        raise ValueError(f"策略 {name} 已存在；請換一個名稱，原始 V1 不會被覆蓋。")

    if generated_adapter:
        output = compute_pine_signals(frame.copy(), source)
        output.insert(0, "timestamp", pd.to_datetime(frame["timestamp"], utc=True))
        signal_source = f"pine:auto:{pine_path.name}"
    else:
        output = normalize_signal_csv(signal_csv)
        available = set(pd.to_datetime(frame["timestamp"], utc=True))
        output = output[output["timestamp"].isin(available)].copy()
        signal_source = f"tradingview:csv:{pine_path.name}"
    records = signals_to_records(output)
    if not records:
        raise ValueError("這段行情沒有產生任何訊號；請檢查市場、週期與策略條件。")

    pine_path.write_text(source + "\n", encoding="utf-8")
    try:
        if generated_adapter:
            write_pine_adapter(source, adapter_path)
            run_adapter(frame, adapter_path)
        added = register_signals(dataset_id, name, signal_source, records)
    except Exception:
        pine_path.unlink(missing_ok=True)
        adapter_path.unlink(missing_ok=True)
        raise
    if added == 0:
        pine_path.unlink(missing_ok=True)
        adapter_path.unlink(missing_ok=True)
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
        "adapter_ready": generated_adapter,
        "pine_path": str(pine_path),
        "adapter_path": str(adapter_path) if generated_adapter else None,
    }
