from __future__ import annotations

import math
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import INDICATORS_DIR, PROJECT_ROOT
from .deletion import delete_market, delete_strategy, delete_version_branch, strategy_root
from .improvement import analyze_indicator, improve_indicator, list_improvements
from .labeling import delete_label_snapshot, locate_signal_index, save_label_snapshot
from .market import (
    INTERVAL_MS,
    load_binance_symbol_catalog,
    load_saved_frame,
    sync_full_history,
)
from .storage import (
    ensure_dataset,
    get_dataset,
    get_signal,
    initialize_database,
    list_datasets,
    list_review_signals,
    list_signals,
)
from .strategy_import import import_strategy_v1


class LabelRequest(BaseModel):
    label: Literal["win", "loss", "breakeven", "invalid"]
    notes: str = ""
    bars_held: int = Field(default=20, ge=1, le=5000)
    context_before: int = Field(default=60, ge=5, le=1000)
    context_after: int = Field(default=30, ge=5, le=1000)


class ImportRequest(BaseModel):
    strategy_name: str = Field(min_length=1, max_length=120)
    pine_source: str = Field(min_length=1, max_length=1_000_000)
    dataset_id: int | None = None
    symbol: str = "BTCUSDT"
    interval: str = "15m"
    market_type: Literal["spot", "futures"] = "futures"
    timezone: str = "Asia/Taipei"
    long_expression: str | None = None
    short_expression: str | None = None


class ImproveRequest(BaseModel):
    indicator_name: str
    force_new: bool = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Indicator Lab API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return _clean(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return _clean(value.to_dict())
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if value is pd.NA or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    return value


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, (KeyError, FileNotFoundError)):
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@lru_cache(maxsize=12)
def _cached_market_frame(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns
    return load_saved_frame(path)


def _market_frame(dataset_id: int) -> tuple[dict, pd.DataFrame]:
    dataset = get_dataset(dataset_id)
    path = Path(dataset["resolved_path"])
    if not path.exists():
        raise FileNotFoundError(f"行情檔案不存在：{path.name}")
    return dataset, _cached_market_frame(str(path), path.stat().st_mtime_ns)


def _version_number(name: str) -> int:
    match = re.search(r"_v(\d+)$", name)
    return int(match.group(1)) if match else 1


def _signal_record(row: pd.Series | dict) -> dict:
    item = dict(row)
    return _clean(
        {
            "id": item.get("id"),
            "timestamp": item.get("timestamp"),
            "direction": item.get("direction"),
            "label": item.get("label"),
            "notes": item.get("notes") or "",
            "pnl_pct": item.get("pnl_pct"),
            "bars_held": item.get("bars_held"),
            "indicator_name": item.get("indicator_name"),
        }
    )


def _signal_reference(row: Any) -> dict:
    return {
        "id": int(row.id),
        "label": None if pd.isna(row.label) else str(row.label),
    }


def _strategy_rows(dataset_id: int) -> list[dict]:
    signals = list_signals(dataset_id)
    if signals.empty:
        return []
    rows: list[dict] = []
    for name, group in signals.groupby("indicator_name", sort=False):
        labels = group["label"]
        decisive = labels.isin(["win", "loss"])
        wins = int((labels == "win").sum())
        losses = int((labels == "loss").sum())
        rows.append(
            {
                "name": str(name),
                "root": strategy_root(str(name)),
                "version": _version_number(str(name)),
                "signals": len(group),
                "labeled": int(labels.notna().sum()),
                "unlabeled": int(labels.isna().sum()),
                "wins": wins,
                "losses": losses,
                "invalid": int((labels == "invalid").sum()),
                "win_rate": wins / int(decisive.sum()) * 100 if decisive.any() else None,
                "long": int((group["direction"] == "long").sum()),
                "short": int((group["direction"] == "short").sum()),
            }
        )
    return sorted(rows, key=lambda row: (row["root"], row["version"]))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "product": "Indicator Lab", "frontend": "react"}


@app.get("/api/datasets")
def datasets() -> list[dict]:
    return _clean(list_datasets().to_dict(orient="records"))


@app.get("/api/workspace")
def workspace() -> dict:
    datasets_frame = list_datasets()
    dataset_rows = _clean(datasets_frame.to_dict(orient="records"))
    for row in dataset_rows:
        row["strategies"] = _strategy_rows(int(row["id"]))
    return {"datasets": dataset_rows}


@app.get("/api/datasets/{dataset_id}/strategies")
def strategies(dataset_id: int) -> list[dict]:
    try:
        get_dataset(dataset_id)
        return _clean(_strategy_rows(dataset_id))
    except Exception as exc:
        _raise_http(exc)


@app.get("/api/datasets/{dataset_id}/review")
def review(
    dataset_id: int,
    indicator: str,
    signal_id: int | None = None,
    before: int = Query(default=90, ge=20, le=500),
    after: int = Query(default=50, ge=10, le=300),
) -> dict:
    try:
        dataset, frame = _market_frame(dataset_id)
        signals = list_review_signals(dataset_id, indicator)
        if signals.empty:
            raise ValueError("這個版本目前沒有訊號。")
        ordered = signals.sort_values(["timestamp", "id"], ascending=[False, False]).reset_index(drop=True)
        if signal_id is None:
            candidates = ordered[ordered["label"].isna()]
            selected_row = candidates.iloc[0] if not candidates.empty else ordered.iloc[0]
        else:
            matches = ordered[ordered["id"] == signal_id]
            if matches.empty:
                raise KeyError(f"找不到訊號 {signal_id}")
            selected_row = matches.iloc[0]
        center = locate_signal_index(frame, selected_row["timestamp"])
        start = max(0, center - before)
        end = min(len(frame), center + after + 1)
        candles = frame.iloc[start:end][["timestamp", "open", "high", "low", "close", "volume"]]
        window_start = candles["timestamp"].iloc[0]
        window_end = candles["timestamp"].iloc[-1]
        visible = signals[
            (signals["timestamp"] >= window_start) & (signals["timestamp"] <= window_end)
        ]
        labeled = int(ordered["label"].notna().sum())
        selected_position = int(ordered.index[ordered["id"] == selected_row["id"]][0])
        return _clean(
            {
                "dataset": dataset,
                "indicator": indicator,
                "summary": {
                    "total": len(ordered),
                    "labeled": labeled,
                    "unlabeled": int(len(ordered) - labeled),
                    "wins": int((ordered["label"] == "win").sum()),
                    "losses": int((ordered["label"] == "loss").sum()),
                    "invalid": int((ordered["label"] == "invalid").sum()),
                    "selected_position": selected_position,
                },
                "selected": _signal_record(selected_row),
                "signals": [_signal_reference(row) for row in ordered.itertuples(index=False)],
                "visible_signals": [_signal_record(row) for _, row in visible.iterrows()],
                "candles": candles.to_dict(orient="records"),
            }
        )
    except Exception as exc:
        _raise_http(exc)


@app.put("/api/signals/{signal_id}/label")
def label_signal(signal_id: int, request: LabelRequest) -> dict:
    try:
        signal = get_signal(signal_id)
        _, frame = _market_frame(int(signal["dataset_id"]))
        result = save_label_snapshot(
            signal_id,
            request.label,
            notes=request.notes,
            bars_held=request.bars_held,
            context_before=request.context_before,
            context_after=request.context_after,
            frame=frame,
        )
        return {"saved": True, "signal_id": signal_id, "classification": result["classification"]}
    except Exception as exc:
        _raise_http(exc)


@app.delete("/api/signals/{signal_id}/label")
def remove_label(signal_id: int) -> dict:
    try:
        get_signal(signal_id)
        snapshot_deleted = delete_label_snapshot(signal_id)
        return {
            "deleted": True,
            "signal_id": signal_id,
            "snapshot_deleted": snapshot_deleted,
        }
    except Exception as exc:
        _raise_http(exc)


@app.get("/api/datasets/{dataset_id}/analysis")
def analysis(dataset_id: int, indicator: str) -> dict:
    try:
        return _clean(analyze_indicator(dataset_id, indicator))
    except Exception as exc:
        _raise_http(exc)


@app.post("/api/datasets/{dataset_id}/improve")
def improve(dataset_id: int, request: ImproveRequest) -> dict:
    try:
        return _clean(
            improve_indicator(
                dataset_id,
                request.indicator_name,
                force_new=request.force_new,
            )
        )
    except Exception as exc:
        _raise_http(exc)


@app.get("/api/datasets/{dataset_id}/versions")
def versions(dataset_id: int, root: str | None = None) -> dict:
    try:
        strategy_rows = _strategy_rows(dataset_id)
        if root:
            strategy_rows = [row for row in strategy_rows if row["root"] == strategy_root(root)]
        metadata = [
            item
            for item in list_improvements()
            if int(item.get("dataset_id", -1)) == dataset_id
            and (not root or item.get("root", strategy_root(item["child"])) == strategy_root(root))
        ]
        by_child = {item["child"]: item for item in metadata}
        for row in strategy_rows:
            row["metadata"] = by_child.get(row["name"])
            row["pine_available"] = (INDICATORS_DIR / f'{row["name"]}.pine').exists()
        return {"versions": _clean(strategy_rows)}
    except Exception as exc:
        _raise_http(exc)


@app.get("/api/strategies/{indicator_name}/pine", response_class=PlainTextResponse)
def pine_source(indicator_name: str) -> PlainTextResponse:
    if not re.fullmatch(r"[A-Za-z0-9_]+", indicator_name):
        raise HTTPException(status_code=400, detail="策略名稱格式不正確。")
    path = (INDICATORS_DIR / f"{indicator_name}.pine").resolve()
    if path.parent != INDICATORS_DIR.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail="找不到這個 Pine 版本。")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/symbols")
def symbols(market_type: Literal["spot", "futures"] = "futures") -> dict:
    rows, warning = load_binance_symbol_catalog(market_type)
    return {"symbols": rows, "warning": warning}


@app.post("/api/import")
def import_indicator(request: ImportRequest) -> dict:
    try:
        if request.dataset_id is None:
            if request.interval not in INTERVAL_MS:
                raise ValueError("不支援這個時間週期。")
            frame, path, added = sync_full_history(
                request.symbol,
                request.interval,
                request.market_type,
            )
            dataset_id = ensure_dataset(
                request.symbol,
                request.interval,
                request.market_type,
                request.timezone,
                frame,
                path,
                "binance_full_history",
            )
        else:
            dataset_id = request.dataset_id
            _, frame = _market_frame(dataset_id)
            added = 0
        result = import_strategy_v1(
            dataset_id,
            frame,
            request.strategy_name,
            request.pine_source,
            long_expression=request.long_expression,
            short_expression=request.short_expression,
        )
        result["market_rows_added"] = int(added)
        return _clean(result)
    except Exception as exc:
        _raise_http(exc)


@app.delete("/api/datasets/{dataset_id}/versions/{indicator_name}")
def remove_version(dataset_id: int, indicator_name: str) -> dict:
    try:
        return _clean(delete_version_branch(dataset_id, indicator_name))
    except Exception as exc:
        _raise_http(exc)


@app.delete("/api/datasets/{dataset_id}/strategies/{root_name}")
def remove_strategy(dataset_id: int, root_name: str) -> dict:
    try:
        return _clean(delete_strategy(dataset_id, root_name))
    except Exception as exc:
        _raise_http(exc)


@app.delete("/api/datasets/{dataset_id}")
def remove_market(dataset_id: int) -> dict:
    try:
        return _clean(delete_market(dataset_id))
    except Exception as exc:
        _raise_http(exc)


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def react_app(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="找不到這個 API。")
        requested = (FRONTEND_DIST / path).resolve()
        if path and FRONTEND_DIST.resolve() in requested.parents and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")
