from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import ADAPTERS_DIR, INDICATORS_DIR


@dataclass(frozen=True)
class IndicatorInfo:
    stem: str
    pine_path: Path
    adapter_path: Path | None
    title: str
    version: str

    @property
    def ready(self) -> bool:
        return self.adapter_path is not None


def inspect_pine(path: Path) -> IndicatorInfo:
    text = path.read_text(encoding="utf-8", errors="replace")
    title_match = re.search(r"(?:indicator|strategy)\s*\(\s*[\"']([^\"']+)", text)
    version_match = re.search(r"//@version=(\d+)", text)
    adapter = ADAPTERS_DIR / f"{path.stem}.py"
    return IndicatorInfo(
        stem=path.stem,
        pine_path=path,
        adapter_path=adapter if adapter.exists() else None,
        title=title_match.group(1) if title_match else path.stem,
        version=version_match.group(1) if version_match else "未知",
    )


def discover_indicators() -> list[IndicatorInfo]:
    return [inspect_pine(path) for path in sorted(INDICATORS_DIR.glob("*.pine"))]


def run_adapter(frame: pd.DataFrame, adapter_path: str | Path) -> pd.DataFrame:
    path = Path(adapter_path)
    spec = importlib.util.spec_from_file_location(f"indicator_adapter_{path.stem}", path)
    if not spec or not spec.loader:
        raise ImportError(f"無法載入適配器：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "compute_signals"):
        raise AttributeError("適配器必須提供 compute_signals(df) 函式")
    result = module.compute_signals(frame.copy())
    if not isinstance(result, pd.DataFrame):
        raise TypeError("compute_signals(df) 必須回傳 DataFrame")
    missing = {"long_signal", "short_signal"} - set(result.columns)
    if missing:
        raise ValueError(f"適配器缺少欄位：{', '.join(sorted(missing))}")
    if len(result) != len(frame):
        raise ValueError("適配器回傳列數必須與行情資料相同")
    output = pd.DataFrame({
        "timestamp": pd.to_datetime(frame["timestamp"], utc=True),
        "long_signal": result["long_signal"].fillna(False).astype(bool),
        "short_signal": result["short_signal"].fillna(False).astype(bool),
    })
    return output


def normalize_signal_csv(source) -> pd.DataFrame:
    df = pd.read_csv(source)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    if "time" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"time": "timestamp"})
    if "timestamp" not in df.columns:
        raise ValueError("訊號 CSV 缺少 timestamp 欄位")
    raw_ts = df["timestamp"]
    if pd.api.types.is_numeric_dtype(raw_ts):
        unit = "ms" if float(raw_ts.dropna().abs().median()) > 10_000_000_000 else "s"
        df["timestamp"] = pd.to_datetime(raw_ts, unit=unit, utc=True, errors="coerce")
    else:
        df["timestamp"] = pd.to_datetime(raw_ts, utc=True, errors="coerce")
    if "direction" in df.columns:
        directions = df["direction"].astype(str).str.lower().str.strip()
        df["long_signal"] = directions.eq("long")
        df["short_signal"] = directions.eq("short")
    else:
        for column in ("long_signal", "short_signal"):
            if column not in df.columns:
                raise ValueError("訊號 CSV 需要 direction，或 long_signal 與 short_signal 欄位")
            values = df[column]
            df[column] = values.astype(str).str.lower().isin({"1", "true", "yes", "long", "short"})
    return df.dropna(subset=["timestamp"])[["timestamp", "long_signal", "short_signal"]]


def signals_to_records(signals: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for row in signals.itertuples(index=False):
        timestamp = pd.Timestamp(row.timestamp).isoformat()
        if bool(row.long_signal):
            records.append({"timestamp": timestamp, "direction": "long"})
        if bool(row.short_signal):
            records.append({"timestamp": timestamp, "direction": "short"})
    return records
