from __future__ import annotations

import numpy as np
import pandas as pd


def summary_metrics(labels: pd.DataFrame) -> dict:
    if labels.empty:
        return {"total": 0, "decisive": 0, "win_rate": None, "avg_pnl": None, "profit_factor": None}
    decisive = labels[labels["label"].isin(["win", "loss"])]
    pnl = pd.to_numeric(labels["pnl_pct"], errors="coerce").dropna()
    gains = pnl[pnl > 0].sum()
    losses = abs(pnl[pnl < 0].sum())
    return {
        "total": len(labels),
        "decisive": len(decisive),
        "win_rate": float((decisive["label"] == "win").mean() * 100) if len(decisive) else None,
        "avg_pnl": float(pnl.mean()) if len(pnl) else None,
        "profit_factor": float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else None),
    }


def grouped_performance(labels: pd.DataFrame, group: str) -> pd.DataFrame:
    if labels.empty or group not in labels.columns:
        return pd.DataFrame()
    valid = labels[labels["label"].isin(["win", "loss"])].copy()
    if valid.empty:
        return pd.DataFrame()
    result = valid.groupby(group, dropna=False).agg(
        samples=("signal_id", "count"),
        wins=("label", lambda x: int((x == "win").sum())),
        avg_pnl=("pnl_pct", "mean"),
        avg_mfe=("mfe_pct", "mean"),
        avg_mae=("mae_pct", "mean"),
    ).reset_index()
    result["win_rate"] = result["wins"] / result["samples"] * 100
    return result.sort_values(["win_rate", "samples"], ascending=[False, False])


def confidence_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (np.nan, np.nan)
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return (max(0.0, center - spread) * 100, min(1.0, center + spread) * 100)
