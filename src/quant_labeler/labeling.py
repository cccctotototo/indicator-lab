from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import LABELS, PROJECT_ROOT, SAMPLES_DIR
from .features import FEATURE_COLUMNS, forward_outcome
from .market import load_saved_frame
from .storage import get_signal, upsert_label


def _json_value(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if pd.isna(value):
        return None
    return value


def locate_signal_index(frame: pd.DataFrame, timestamp) -> int:
    times = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    target = pd.Timestamp(timestamp)
    target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
    values = times.asi8
    if not values.size:
        raise ValueError("行情資料是空的，無法定位訊號。")
    position = int(np.searchsorted(values, target.value))
    if position < len(values) and values[position] == target.value:
        return position
    if position <= 0:
        return 0
    if position >= len(values):
        return len(values) - 1
    before = position - 1
    return before if target.value - values[before] <= values[position] - target.value else position


def save_label_snapshot(
    signal_id: int,
    label: str,
    notes: str = "",
    bars_held: int = 20,
    context_before: int = 60,
    context_after: int = 30,
    exit_price: float | None = None,
    frame: pd.DataFrame | None = None,
) -> dict:
    if label not in LABELS:
        raise ValueError(f"未知分類：{label}")
    signal = get_signal(signal_id)
    if frame is None:
        frame = load_saved_frame(signal["resolved_path"])
    index = locate_signal_index(frame, signal["timestamp"])
    outcome = forward_outcome(frame, index, signal["direction"], bars_held)
    if exit_price is not None and float(exit_price) > 0:
        outcome["exit_price"] = float(exit_price)
        sign = 1 if signal["direction"] == "long" else -1
        outcome["pnl_pct"] = sign * (float(exit_price) / outcome["entry_price"] - 1) * 100

    start = max(0, index - context_before)
    end = min(len(frame), index + context_after + 1)
    context = frame.iloc[start:end].copy()
    candle_records = [
        {key: _json_value(value) for key, value in row.items()}
        for row in context.to_dict(orient="records")
    ]
    signal_row = frame.iloc[index]
    feature_snapshot = {
        column: _json_value(signal_row[column])
        for column in FEATURE_COLUMNS
        if column in signal_row.index
    }
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "signal": {
            "id": signal_id,
            "dataset_id": signal["dataset_id"],
            "indicator_name": signal["indicator_name"],
            "symbol": signal["symbol"],
            "interval": signal["interval"],
            "market_type": signal["market_type"],
            "timestamp": pd.Timestamp(signal["timestamp"]).isoformat(),
            "direction": signal["direction"],
            "source": signal["source"],
        },
        "classification": {
            "label": label,
            "notes": notes.strip(),
            "bars_held": int(bars_held),
            **outcome,
        },
        "context": {
            "before": int(context_before),
            "after": int(context_after),
            "signal_offset": index - start,
            "candles": candle_records,
        },
        "features_at_signal": feature_snapshot,
        "created_at": created_at,
    }
    safe_time = pd.Timestamp(signal["timestamp"]).strftime("%Y%m%dT%H%M%S")
    filename = f"signal_{signal_id}_{signal['symbol']}_{signal['interval']}_{safe_time}.json.gz"
    path = SAMPLES_DIR / label / filename
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    relative = str(path.relative_to(PROJECT_ROOT))
    upsert_label(
        signal_id,
        {
            "label": label,
            "notes": notes.strip(),
            "entry_price": outcome["entry_price"],
            "exit_price": outcome["exit_price"],
            "pnl_pct": outcome["pnl_pct"],
            "mfe_pct": outcome["mfe_pct"],
            "mae_pct": outcome["mae_pct"],
            "bars_held": int(bars_held),
            "context_before": int(context_before),
            "context_after": int(context_after),
            "sample_path": relative,
        },
    )
    old_relative = signal.get("existing_sample_path")
    if old_relative:
        old_path = (PROJECT_ROOT / old_relative).resolve()
        samples_root = SAMPLES_DIR.resolve()
        if old_path != path.resolve() and samples_root in old_path.parents and old_path.exists():
            old_path.unlink()
    return payload


def read_snapshot(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)
