from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .config import DB_PATH, PROJECT_ROOT, ensure_directories

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    market_type TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    path TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    indicator_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('long','short')),
    source TEXT NOT NULL,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(dataset_id, indicator_name, timestamp, direction)
);
CREATE TABLE IF NOT EXISTS labels (
    signal_id INTEGER PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK(label IN ('win','loss','breakeven','invalid')),
    notes TEXT NOT NULL DEFAULT '',
    entry_price REAL,
    exit_price REAL,
    pnl_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    bars_held INTEGER NOT NULL DEFAULT 20,
    context_before INTEGER NOT NULL DEFAULT 60,
    context_after INTEGER NOT NULL DEFAULT 30,
    sample_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata_path TEXT NOT NULL,
    labeled_count INTEGER NOT NULL,
    unlabeled_count INTEGER NOT NULL,
    accuracy REAL,
    roc_auc REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS predictions (
    model_run_id INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
    signal_id INTEGER NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    win_probability REAL NOT NULL,
    predicted_label TEXT NOT NULL,
    PRIMARY KEY(model_run_id, signal_id)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect():
    ensure_directories()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def add_dataset(
    symbol: str,
    interval: str,
    market_type: str,
    timezone_name: str,
    frame: pd.DataFrame,
    path: str | Path,
    source: str,
) -> int:
    path = Path(path).resolve()
    try:
        stored_path = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        stored_path = str(path)
    with connect() as conn:
        cursor = conn.execute(
            """INSERT INTO datasets
            (symbol, interval, market_type, timezone, start_time, end_time, path, row_count, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol.upper(), interval, market_type, timezone_name,
                pd.Timestamp(frame["timestamp"].min()).isoformat(),
                pd.Timestamp(frame["timestamp"].max()).isoformat(), stored_path,
                len(frame), source, _now(),
            ),
        )
        return int(cursor.lastrowid)


def ensure_dataset(
    symbol: str,
    interval: str,
    market_type: str,
    timezone_name: str,
    frame: pd.DataFrame,
    path: str | Path,
    source: str,
) -> int:
    """Reuse a market file already registered in the app, refreshing its range."""
    resolved = Path(path).resolve()
    try:
        stored_path = str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        stored_path = str(resolved)
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM datasets WHERE path=? ORDER BY id DESC LIMIT 1",
            (stored_path,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE datasets SET symbol=?, interval=?, market_type=?, timezone=?,
                   start_time=?, end_time=?, row_count=?, source=? WHERE id=?""",
                (
                    symbol.upper(),
                    interval,
                    market_type,
                    timezone_name,
                    pd.Timestamp(frame["timestamp"].min()).isoformat(),
                    pd.Timestamp(frame["timestamp"].max()).isoformat(),
                    len(frame),
                    source,
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])
    return add_dataset(
        symbol, interval, market_type, timezone_name, frame, resolved, source
    )


def update_dataset_market_file(
    dataset_id: int,
    symbol: str,
    interval: str,
    market_type: str,
    timezone_name: str,
    frame: pd.DataFrame,
    path: str | Path,
    source: str,
) -> None:
    """Replace one dataset's market file without changing its identity or labels."""
    resolved = Path(path).resolve()
    try:
        stored_path = str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        stored_path = str(resolved)
    with connect() as conn:
        cursor = conn.execute(
            """UPDATE datasets SET symbol=?, interval=?, market_type=?, timezone=?,
               start_time=?, end_time=?, path=?, row_count=?, source=? WHERE id=?""",
            (
                symbol.upper(),
                interval,
                market_type,
                timezone_name,
                pd.Timestamp(frame["timestamp"].min()).isoformat(),
                pd.Timestamp(frame["timestamp"].max()).isoformat(),
                stored_path,
                len(frame),
                source,
                dataset_id,
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"找不到資料集：{dataset_id}")


def list_datasets() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query("SELECT * FROM datasets ORDER BY id DESC", conn)


def get_dataset(dataset_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if not row:
        raise KeyError(f"找不到資料集 {dataset_id}")
    result = dict(row)
    path = Path(result["path"])
    result["resolved_path"] = str(path if path.is_absolute() else PROJECT_ROOT / path)
    return result


def delete_dataset_record(dataset_id: int) -> dict:
    """Delete one dataset and its cascaded signals/labels from SQLite."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM datasets WHERE id=?",
            (dataset_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"找不到資料集 {dataset_id}")
        signal_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM signals WHERE dataset_id=?",
                (dataset_id,),
            ).fetchone()[0]
        )
        conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
    result = dict(row)
    result["signals"] = signal_count
    return result


def dataset_path_reference_count(path: str, exclude_dataset_id: int | None = None) -> int:
    """Count dataset rows that still reference the exact stored market path."""
    query = "SELECT COUNT(*) FROM datasets WHERE path=?"
    params: list = [path]
    if exclude_dataset_id is not None:
        query += " AND id<>?"
        params.append(exclude_dataset_id)
    with connect() as conn:
        return int(conn.execute(query, params).fetchone()[0])


def register_signals(dataset_id: int, indicator_name: str, source: str, records: list[dict]) -> int:
    created = _now()
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO signals
            (dataset_id, indicator_name, timestamp, direction, source, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (dataset_id, indicator_name, row["timestamp"], row["direction"], source, json.dumps(row, ensure_ascii=False), created)
                for row in records
            ],
        )
        return conn.total_changes - before


def delete_indicator_signals(dataset_id: int, indicator_name: str) -> int:
    """Delete one exact indicator version and its cascaded labels."""
    with connect() as conn:
        count = int(
            conn.execute(
                "SELECT COUNT(*) FROM signals WHERE dataset_id=? AND indicator_name=?",
                (dataset_id, indicator_name),
            ).fetchone()[0]
        )
        conn.execute(
            "DELETE FROM signals WHERE dataset_id=? AND indicator_name=?",
            (dataset_id, indicator_name),
        )
    return count


def list_signals(dataset_id: int | None = None, indicator_name: str | None = None) -> pd.DataFrame:
    query = """
    SELECT s.*, d.symbol, d.interval, d.market_type, d.path AS dataset_path,
           l.label, l.notes, l.entry_price, l.exit_price, l.pnl_pct, l.mfe_pct, l.mae_pct,
           l.bars_held, l.sample_path, l.updated_at AS labeled_at
    FROM signals s
    JOIN datasets d ON d.id=s.dataset_id
    LEFT JOIN labels l ON l.signal_id=s.id
    WHERE 1=1
    """
    params: list = []
    if dataset_id is not None:
        query += " AND s.dataset_id=?"
        params.append(dataset_id)
    if indicator_name:
        query += " AND s.indicator_name=?"
        params.append(indicator_name)
    query += " ORDER BY s.timestamp, s.id"
    with connect() as conn:
        frame = pd.read_sql_query(query, conn, params=params)
    if not frame.empty:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def list_review_signals(dataset_id: int, indicator_name: str) -> pd.DataFrame:
    """Load only the fields needed by the interactive labeling screen."""
    query = """
    SELECT s.id, s.timestamp, s.direction, s.indicator_name,
           l.label, l.notes, l.pnl_pct, l.bars_held
    FROM signals s
    LEFT JOIN labels l ON l.signal_id=s.id
    WHERE s.dataset_id=? AND s.indicator_name=?
    ORDER BY s.timestamp, s.id
    """
    with connect() as conn:
        frame = pd.read_sql_query(query, conn, params=[dataset_id, indicator_name])
    if not frame.empty:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def get_signal(signal_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            """SELECT s.*, d.symbol, d.interval, d.market_type, d.path AS dataset_path,
                      l.sample_path AS existing_sample_path
               FROM signals s JOIN datasets d ON d.id=s.dataset_id
               LEFT JOIN labels l ON l.signal_id=s.id WHERE s.id=?""",
            (signal_id,),
        ).fetchone()
    if not row:
        raise KeyError(f"找不到訊號 {signal_id}")
    result = dict(row)
    path = Path(result["dataset_path"])
    result["resolved_path"] = str(path if path.is_absolute() else PROJECT_ROOT / path)
    return result


def upsert_label(signal_id: int, payload: dict) -> None:
    now = _now()
    with connect() as conn:
        existing = conn.execute("SELECT created_at FROM labels WHERE signal_id=?", (signal_id,)).fetchone()
        created = existing["created_at"] if existing else now
        conn.execute(
            """INSERT INTO labels
            (signal_id,label,notes,entry_price,exit_price,pnl_pct,mfe_pct,mae_pct,bars_held,
             context_before,context_after,sample_path,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(signal_id) DO UPDATE SET
              label=excluded.label, notes=excluded.notes, entry_price=excluded.entry_price,
              exit_price=excluded.exit_price, pnl_pct=excluded.pnl_pct, mfe_pct=excluded.mfe_pct,
              mae_pct=excluded.mae_pct, bars_held=excluded.bars_held,
              context_before=excluded.context_before, context_after=excluded.context_after,
              sample_path=excluded.sample_path, updated_at=excluded.updated_at""",
            (
                signal_id, payload["label"], payload.get("notes", ""), payload.get("entry_price"),
                payload.get("exit_price"), payload.get("pnl_pct"), payload.get("mfe_pct"),
                payload.get("mae_pct"), payload.get("bars_held", 20), payload.get("context_before", 60),
                payload.get("context_after", 30), payload["sample_path"], created, now,
            ),
        )


def delete_label(signal_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM labels WHERE signal_id=?", (signal_id,))


def analysis_frame() -> pd.DataFrame:
    with connect() as conn:
        df = pd.read_sql_query(
            """SELECT s.id AS signal_id, s.indicator_name, s.timestamp, s.direction,
                      d.symbol, d.interval, d.market_type,
                      l.label, l.notes, l.entry_price, l.exit_price, l.pnl_pct,
                      l.mfe_pct, l.mae_pct, l.bars_held, l.context_before,
                      l.context_after, l.sample_path, l.created_at, l.updated_at
               FROM labels l JOIN signals s ON s.id=l.signal_id
               JOIN datasets d ON d.id=s.dataset_id ORDER BY l.updated_at DESC""",
            conn,
        )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def add_model_run(metadata: dict, path: Path, metadata_path: Path) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """INSERT INTO model_runs
            (name,path,metadata_path,labeled_count,unlabeled_count,accuracy,roc_auc,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                metadata["name"], str(path.relative_to(PROJECT_ROOT)), str(metadata_path.relative_to(PROJECT_ROOT)),
                metadata["labeled_count"], metadata["unlabeled_count"], metadata.get("accuracy"),
                metadata.get("roc_auc"), metadata["created_at"],
            ),
        )
        return int(cursor.lastrowid)


def save_predictions(model_run_id: int, rows: list[tuple[int, float, str]]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO predictions(model_run_id,signal_id,win_probability,predicted_label) VALUES (?,?,?,?)",
            [(model_run_id, *row) for row in rows],
        )


def list_model_runs() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query("SELECT * FROM model_runs ORDER BY id DESC", conn)


def latest_predictions() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """SELECT p.*, s.timestamp, s.direction, s.indicator_name, d.symbol, d.interval
               FROM predictions p JOIN signals s ON s.id=p.signal_id
               JOIN datasets d ON d.id=s.dataset_id
               WHERE p.model_run_id=(SELECT MAX(id) FROM model_runs)
               ORDER BY p.win_probability DESC""",
            conn,
        )
