from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.semi_supervised import SelfTrainingClassifier

from .config import MODELS_DIR, PROJECT_ROOT
from .features import FEATURE_COLUMNS
from .market import load_saved_frame
from .storage import add_model_run, list_signals, save_predictions


@lru_cache(maxsize=8)
def _feature_lookup(path_text: str, modified_ns: int) -> pd.DataFrame:
    """Keep the immutable candle feature index ready for repeated label analysis."""
    del modified_ns
    frame = load_saved_frame(path_text)
    feature_columns = [
        feature for feature in FEATURE_COLUMNS if feature in frame.columns
    ]
    lookup = frame[["timestamp", *feature_columns]].copy()
    if not isinstance(lookup["timestamp"].dtype, pd.DatetimeTZDtype):
        lookup["timestamp"] = pd.to_datetime(lookup["timestamp"], utc=True)
    return (
        lookup.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .set_index("timestamp")
    )


def build_training_frame(
    dataset_id: int | None = None,
    indicator_name: str | None = None,
    *,
    labeled_only: bool = False,
) -> pd.DataFrame:
    """Build signal features with one vectorized timestamp join per dataset."""
    signals = list_signals(dataset_id, indicator_name)
    if signals.empty:
        return pd.DataFrame()
    if labeled_only:
        signals = signals[signals["label"].isin(["win", "loss"])].copy()
        if signals.empty:
            return pd.DataFrame()
    groups: list[pd.DataFrame] = []
    for (dataset_id, dataset_path), group in signals.groupby(["dataset_id", "dataset_path"]):
        path = Path(dataset_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        resolved_path = path.resolve()
        candles = _feature_lookup(
            str(resolved_path),
            resolved_path.stat().st_mtime_ns,
        )
        signal_rows = group[
            [
                "id",
                "symbol",
                "interval",
                "direction",
                "indicator_name",
                "timestamp",
                "label",
            ]
        ].copy()
        signal_rows["timestamp"] = pd.to_datetime(signal_rows["timestamp"], utc=True)
        signal_rows = signal_rows.sort_values("timestamp")
        positions = candles.index.get_indexer(signal_rows["timestamp"], method="nearest")
        feature_rows = candles.iloc[np.maximum(positions, 0)].reset_index(drop=True)
        if (positions < 0).any():
            feature_rows.loc[positions < 0, :] = np.nan
        merged = pd.concat(
            [signal_rows.reset_index(drop=True), feature_rows],
            axis=1,
        )
        merged = merged.rename(columns={"id": "signal_id", "label": "label_text"})
        merged.insert(1, "dataset_id", int(dataset_id))
        merged["direction_short"] = merged["direction"].eq("short").astype(float)
        for feature in FEATURE_COLUMNS:
            if feature not in merged.columns:
                merged[feature] = np.nan
            merged[feature] = pd.to_numeric(merged[feature], errors="coerce")
        groups.append(merged)
    return pd.concat(groups, ignore_index=True)


def train_semisupervised(
    confidence_threshold: float = 0.85,
    min_labeled: int = 10,
    random_state: int = 42,
) -> dict:
    data = build_training_frame()
    if data.empty:
        raise ValueError("尚無訊號可訓練。")
    valid = data["label_text"].isin(["win", "loss"])
    labeled_count = int(valid.sum())
    if labeled_count < min_labeled:
        raise ValueError(f"至少需要 {min_labeled} 筆贏／輸標記，目前只有 {labeled_count} 筆。")
    y_labeled = data.loc[valid, "label_text"].map({"loss": 0, "win": 1}).astype(int)
    if y_labeled.nunique() < 2:
        raise ValueError("贏與輸兩個分類都至少需要一筆資料。")

    feature_names = [*FEATURE_COLUMNS, "direction_short"]
    x_all = data[feature_names].replace([np.inf, -np.inf], np.nan)
    y_all = np.full(len(data), -1, dtype=int)
    y_all[valid.to_numpy()] = y_labeled.to_numpy()

    base = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("forest", RandomForestClassifier(
            n_estimators=350, min_samples_leaf=3, class_weight="balanced_subsample",
            random_state=random_state, n_jobs=-1,
        )),
    ])

    accuracy = None
    roc_auc = None
    report = None
    labeled_indices = np.flatnonzero(valid.to_numpy())
    class_counts = y_labeled.value_counts()
    if labeled_count >= 16 and class_counts.min() >= 3:
        train_idx, test_idx = train_test_split(
            labeled_indices, test_size=0.25, stratify=y_all[labeled_indices], random_state=random_state
        )
        evaluator = Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("forest", RandomForestClassifier(
                n_estimators=350, min_samples_leaf=3, class_weight="balanced_subsample",
                random_state=random_state, n_jobs=-1,
            )),
        ])
        evaluator.fit(x_all.iloc[train_idx], y_all[train_idx])
        pred = evaluator.predict(x_all.iloc[test_idx])
        proba = evaluator.predict_proba(x_all.iloc[test_idx])[:, 1]
        accuracy = float(accuracy_score(y_all[test_idx], pred))
        if len(np.unique(y_all[test_idx])) == 2:
            roc_auc = float(roc_auc_score(y_all[test_idx], proba))
        report = classification_report(y_all[test_idx], pred, target_names=["loss", "win"], output_dict=True, zero_division=0)

    model = SelfTrainingClassifier(
        estimator=base,
        threshold=float(confidence_threshold),
        criterion="threshold",
        max_iter=12,
        verbose=False,
    )
    model.fit(x_all, y_all)
    probabilities = model.predict_proba(x_all)[:, 1]
    predictions = np.where(probabilities >= 0.5, "win", "loss")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"semisupervised_{stamp}"
    model_path = MODELS_DIR / f"{name}.joblib"
    metadata_path = MODELS_DIR / f"{name}.json"
    pseudo_count = int(np.sum((model.transduction_ != -1) & (y_all == -1)))
    metadata = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_names": feature_names,
        "labeled_count": labeled_count,
        "unlabeled_count": int((~valid).sum()),
        "pseudo_labeled_count": pseudo_count,
        "confidence_threshold": float(confidence_threshold),
        "accuracy": accuracy,
        "roc_auc": roc_auc,
        "classification_report": report,
        "warning": "模型機率是研究排序工具，不代表保證獲利。評估僅使用已標記資料的保留集。",
    }
    joblib.dump({"model": model, "feature_names": feature_names}, model_path)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    run_id = add_model_run(metadata, model_path, metadata_path)
    prediction_rows = [
        (int(signal_id), float(probability), str(label))
        for signal_id, probability, label in zip(data["signal_id"], probabilities, predictions)
    ]
    save_predictions(run_id, prediction_rows)
    metadata["run_id"] = run_id
    return metadata


def feature_importance_from_latest(model_path: str | Path) -> pd.DataFrame:
    path = Path(model_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    bundle = joblib.load(path)
    model = bundle["model"]
    names = bundle["feature_names"]
    estimator = model.estimator_
    forest = estimator.named_steps["forest"]
    importances = forest.feature_importances_
    if len(importances) > len(names):
        names = [*names, *(f"missing_{i}" for i in range(len(importances) - len(names)))]
    return pd.DataFrame({"feature": names[: len(importances)], "importance": importances}).sort_values("importance", ascending=False)
