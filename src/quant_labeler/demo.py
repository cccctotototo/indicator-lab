from __future__ import annotations

import numpy as np
import pandas as pd

from .config import INDICATORS_DIR
from .indicators import signals_to_records
from .labeling import save_label_snapshot
from .market import load_saved_frame, save_market_frame
from .pine_runtime import compute_pine_signals
from .storage import add_dataset, get_dataset, list_datasets, list_signals, register_signals


def seed_demo() -> tuple[int, int, int]:
    """Create an idempotent synthetic dataset for onboarding and UI verification."""
    existing = list_datasets()
    demo_rows = existing[existing["source"] == "demo:synthetic"] if not existing.empty else existing
    if not demo_rows.empty:
        dataset_id = int(demo_rows.iloc[0]["id"])
        frame = load_saved_frame(get_dataset(dataset_id)["resolved_path"])
        extra = [
            {"timestamp": pd.Timestamp(frame.iloc[index]["timestamp"]).isoformat(), "direction": "long" if n % 2 == 0 else "short"}
            for n, index in enumerate(range(100, min(len(frame), 1700), 100))
        ]
        register_signals(dataset_id, "demo_unlabeled_candidates", "demo:synthetic", extra)
        signals = list_signals(dataset_id)
        return dataset_id, len(signals), int(signals["label"].notna().sum()) if not signals.empty else 0

    rng = np.random.default_rng(20260721)
    rows = 1_800
    t = np.arange(rows)
    regime = np.where((t // 240) % 2 == 0, 0.035, -0.018)
    cycle = 3.8 * np.sin(t / 17) + 7.5 * np.sin(t / 73)
    noise = rng.normal(0, 0.6, rows).cumsum() * 0.08
    close = 100 + np.cumsum(regime) + cycle + noise
    open_ = np.r_[close[0], close[:-1]] + rng.normal(0, 0.24, rows)
    spread = rng.uniform(0.35, 1.15, rows)
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
        "open": open_,
        "high": np.maximum(open_, close) + spread,
        "low": np.minimum(open_, close) - spread,
        "close": close,
        "volume": rng.lognormal(mean=6.3, sigma=0.35, size=rows) * (1 + 0.35 * np.abs(np.sin(t / 17))),
    })
    path = save_market_frame(frame, "DEMOUSDT", "1h", "custom")
    enriched = load_saved_frame(path)
    dataset_id = add_dataset("DEMOUSDT", "1h", "custom", "Asia/Taipei", enriched, path, "demo:synthetic")
    pine_path = INDICATORS_DIR / "candle_long_short_indicator.pine"
    output = compute_pine_signals(
        enriched,
        pine_path.read_text(encoding="utf-8"),
        ticker="DEMOUSDT",
        timeframe="1h",
        timezone="Asia/Taipei",
    )
    output.insert(0, "timestamp", pd.to_datetime(enriched["timestamp"], utc=True))
    records = signals_to_records(output)
    register_signals(dataset_id, "candle_long_short_indicator", f"pinets:{pine_path.name}", records)
    extra = [
        {"timestamp": pd.Timestamp(enriched.iloc[index]["timestamp"]).isoformat(), "direction": "long" if n % 2 == 0 else "short"}
        for n, index in enumerate(range(100, min(len(enriched), 1700), 100))
    ]
    register_signals(dataset_id, "demo_unlabeled_candidates", "demo:synthetic", extra)
    signals = list_signals(dataset_id)
    real_indicator_signals = signals[signals["indicator_name"] == "candle_long_short_indicator"]
    for index, row in enumerate(real_indicator_signals.head(12).itertuples(index=False)):
        # Demo labels are deterministic and clearly marked; they are not real trading evidence.
        label = "win" if index % 3 != 1 else "loss"
        save_label_snapshot(int(row.id), label, "[示範資料] 僅供熟悉介面", 20, 60, 30)
    return dataset_id, len(signals), min(12, len(real_indicator_signals))
