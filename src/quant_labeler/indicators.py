from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import INDICATORS_DIR


@dataclass(frozen=True)
class IndicatorInfo:
    stem: str
    pine_path: Path
    title: str
    version: str
    engine: str = "PineTS"


def inspect_pine(path: Path) -> IndicatorInfo:
    text = path.read_text(encoding="utf-8", errors="replace")
    title_match = re.search(r"indicator\s*\(\s*[\"']([^\"']+)", text)
    version_match = re.search(r"//@version=(\d+)", text)
    return IndicatorInfo(
        stem=path.stem,
        pine_path=path,
        title=title_match.group(1) if title_match else path.stem,
        version=version_match.group(1) if version_match else "未知",
    )


def discover_indicators() -> list[IndicatorInfo]:
    return [inspect_pine(path) for path in sorted(INDICATORS_DIR.glob("*.pine"))]


def signals_to_records(signals: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for row in signals.itertuples(index=False):
        timestamp = pd.Timestamp(row.timestamp).isoformat()
        if bool(row.long_signal):
            records.append({"timestamp": timestamp, "direction": "long"})
        if bool(row.short_signal):
            records.append({"timestamp": timestamp, "direction": "short"})
    return records
