from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    INDICATORS_DIR,
    PROJECT_ROOT,
    SAMPLES_DIR,
    STRATEGY_VERSIONS_DIR,
)
from .indicators import signals_to_records
from .market import load_saved_frame
from .ml import build_training_frame
from .pine_runtime import compute_pine_signals
from .storage import (
    delete_indicator_signals,
    get_dataset,
    list_signals,
    register_signals,
)


SUPPORTED_FEATURES = {
    "rsi_14": "RSI 14",
    "volume_ratio_20": "量能／20 根均量",
    "trend_9_21": "EMA 9／21 趨勢差",
    "volatility_20": "20 根波動率",
    "close_position_20": "20 根區間位置",
}


def _stats(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"samples": 0, "wins": 0, "losses": 0, "win_rate": None}
    wins = int((frame["label_text"] == "win").sum())
    return {
        "samples": int(len(frame)),
        "wins": wins,
        "losses": int(len(frame) - wins),
        "win_rate": float(wins / len(frame) * 100),
    }


def feature_comparison(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    winners = data[data["label_text"] == "win"]
    losers = data[data["label_text"] == "loss"]
    for feature, label in SUPPORTED_FEATURES.items():
        win_values = pd.to_numeric(winners[feature], errors="coerce").dropna()
        loss_values = pd.to_numeric(losers[feature], errors="coerce").dropna()
        if win_values.empty or loss_values.empty:
            continue
        all_std = pd.concat([win_values, loss_values]).std(ddof=1)
        standardized_gap = (
            float((win_values.median() - loss_values.median()) / all_std)
            if all_std and np.isfinite(all_std)
            else 0.0
        )
        rows.append(
            {
                "feature": feature,
                "name": label,
                "win_median": float(win_values.median()),
                "loss_median": float(loss_values.median()),
                "gap": standardized_gap,
                "importance": abs(standardized_gap),
                "winner_tendency": "較高" if standardized_gap > 0 else "較低",
                "loser_tendency": "較低" if standardized_gap > 0 else "較高",
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "feature", "name", "win_median", "loss_median", "gap",
                "importance", "winner_tendency", "loser_tendency",
            ]
        )
    return pd.DataFrame(rows).sort_values("importance", ascending=False).reset_index(drop=True)


def analyze_indicator(dataset_id: int, indicator_name: str) -> dict:
    """Return the label evidence that must be reviewed before creating a child."""
    signals = list_signals(dataset_id, indicator_name)
    decisive = signals[signals["label"].isin(["win", "loss"])].copy()

    def actual_stats(part: pd.DataFrame) -> dict:
        wins = int((part["label"] == "win").sum())
        samples = int(len(part))
        return {
            "samples": samples,
            "wins": wins,
            "losses": samples - wins,
            "win_rate": float(wins / samples * 100) if samples else None,
        }

    direction_stats = {
        direction: actual_stats(decisive[decisive["direction"] == direction])
        for direction in ("long", "short")
    }
    comparison = pd.DataFrame()
    profile: list[dict] = []
    if not decisive.empty:
        training = build_training_frame(
            dataset_id,
            indicator_name,
            labeled_only=True,
        )
        training = training[training["label_text"].isin(["win", "loss"])].copy()
        for feature, name in SUPPORTED_FEATURES.items():
            values = pd.to_numeric(training[feature], errors="coerce").dropna()
            if not values.empty:
                profile.append(
                    {
                        "feature": feature,
                        "name": name,
                        "median": float(values.median()),
                        "samples": int(len(values)),
                    }
                )
        if decisive["label"].nunique() == 2:
            comparison = feature_comparison(training)
    return {
        "indicator_name": indicator_name,
        "total_signals": int(len(signals)),
        "remaining": int(signals["label"].isna().sum()),
        "invalid": int((signals["label"] == "invalid").sum()),
        "decisive": int(len(decisive)),
        "overall": actual_stats(decisive),
        "directions": direction_stats,
        "feature_comparison": comparison.to_dict(orient="records"),
        "feature_profile": profile,
    }


def _candidate_rules(data: pd.DataFrame) -> list[list[dict]]:
    numeric_rules: list[dict] = []
    for feature in SUPPORTED_FEATURES:
        values = pd.to_numeric(data[feature], errors="coerce").dropna()
        if values.nunique() < 8:
            continue
        q25, q50, q75 = values.quantile([0.25, 0.50, 0.75]).tolist()
        numeric_rules.extend(
            [
                {"feature": feature, "op": "le", "value": float(q25)},
                {"feature": feature, "op": "le", "value": float(q50)},
                {"feature": feature, "op": "le", "value": float(q75)},
                {"feature": feature, "op": "ge", "value": float(q25)},
                {"feature": feature, "op": "ge", "value": float(q50)},
                {"feature": feature, "op": "ge", "value": float(q75)},
                {
                    "feature": feature,
                    "op": "between",
                    "low": float(q25),
                    "high": float(q75),
                },
            ]
        )
    # Direction is never a filter candidate: an improved version must retain
    # both long and short signals from a two-sided parent indicator.
    candidates = [[rule] for rule in numeric_rules]
    # Two numeric filters are allowed only when each describes a different feature.
    candidates.extend(
        [list(pair) for pair in combinations(numeric_rules, 2) if pair[0]["feature"] != pair[1]["feature"]]
    )
    return candidates


def _rule_mask(data: pd.DataFrame, rules: list[dict]) -> pd.Series:
    mask = pd.Series(True, index=data.index)
    for rule in rules:
        feature = rule["feature"]
        if rule["op"] == "eq":
            mask &= data[feature].eq(rule["value"])
        elif rule["op"] == "le":
            mask &= pd.to_numeric(data[feature], errors="coerce").le(rule["value"])
        elif rule["op"] == "ge":
            mask &= pd.to_numeric(data[feature], errors="coerce").ge(rule["value"])
        elif rule["op"] == "between":
            mask &= pd.to_numeric(data[feature], errors="coerce").between(
                rule["low"], rule["high"], inclusive="both"
            )
    return mask.fillna(False)


def _describe_rule(rule: dict) -> str:
    if rule["feature"] == "direction":
        return "只保留做多" if rule["value"] == "long" else "只保留做空"
    name = SUPPORTED_FEATURES[rule["feature"]]
    if rule["op"] == "le":
        return f"{name} ≤ {rule['value']:.4g}"
    if rule["op"] == "ge":
        return f"{name} ≥ {rule['value']:.4g}"
    return f"{rule['low']:.4g} ≤ {name} ≤ {rule['high']:.4g}"


def find_stable_filter(data: pd.DataFrame) -> dict:
    data = data.sort_values("timestamp").reset_index(drop=True)
    cutoff_index = max(1, int(len(data) * 0.67))
    train = data.iloc[:cutoff_index]
    validation = data.iloc[cutoff_index:]
    baseline_train = _stats(train)
    baseline_validation = _stats(validation)
    baseline_all = _stats(data)
    min_train = max(20, int(len(train) * 0.12))
    min_validation = max(10, int(len(validation) * 0.12))
    required_directions = set(data["direction"].dropna().unique())
    best: dict | None = None
    for rules in _candidate_rules(data):
        train_filtered = train[_rule_mask(train, rules)]
        validation_filtered = validation[_rule_mask(validation, rules)]
        if len(train_filtered) < min_train or len(validation_filtered) < min_validation:
            continue
        filtered = data[_rule_mask(data, rules)]
        if len(filtered) / len(data) < 0.25:
            continue
        if len(required_directions) > 1:
            train_has_both = all(
                int((train_filtered["direction"] == direction).sum()) >= 10
                for direction in required_directions
            )
            validation_has_both = all(
                int((validation_filtered["direction"] == direction).sum()) >= 5
                for direction in required_directions
            )
            if not train_has_both or not validation_has_both:
                continue
        train_stats = _stats(train_filtered)
        validation_stats = _stats(validation_filtered)
        all_stats = _stats(filtered)
        train_lift = train_stats["win_rate"] - baseline_train["win_rate"]
        validation_lift = validation_stats["win_rate"] - baseline_validation["win_rate"]
        all_lift = all_stats["win_rate"] - baseline_all["win_rate"]
        if train_lift <= 0 or validation_lift <= 0 or all_lift <= 2:
            continue
        coverage = len(filtered) / len(data)
        score = validation_lift * 0.5 + train_lift * 0.25 + all_lift * 0.25 + coverage * 3
        candidate = {
            "rules": rules,
            "rule_text": "，且".join(_describe_rule(rule) for rule in rules),
            "baseline": {
                "all": baseline_all,
                "train": baseline_train,
                "validation": baseline_validation,
            },
            "filtered": {
                "all": all_stats,
                "train": train_stats,
                "validation": validation_stats,
            },
            "removed_losses": int(
                baseline_all["losses"] - all_stats["losses"]
            ),
            "removed_wins": int(baseline_all["wins"] - all_stats["wins"]),
            "score": float(score),
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    if best is None:
        raise ValueError("目前找不到能同時提升前段與後段資料的穩定過濾條件。")
    return best


def _unchanged_direction(data: pd.DataFrame) -> dict:
    data = data.sort_values("timestamp").reset_index(drop=True)
    cutoff_index = max(1, int(len(data) * 0.67))
    baseline = {
        "all": _stats(data),
        "train": _stats(data.iloc[:cutoff_index]),
        "validation": _stats(data.iloc[cutoff_index:]),
    }
    return {
        "rules": [],
        "rule_text": "沒有通過驗證的新增條件，完整沿用上一版",
        "baseline": baseline,
        "filtered": baseline,
        "removed_losses": 0,
        "removed_wins": 0,
        "score": 0.0,
    }


def find_directional_filters(data: pd.DataFrame) -> dict:
    """Apply every direction that improves on its own; preserve the other side."""
    learned: dict[str, dict] = {}
    unchanged: dict[str, dict] = {}
    for direction in ("long", "short"):
        side = data[data["direction"] == direction].copy()
        if side.empty:
            unchanged[direction] = _unchanged_direction(side)
            learned[direction] = unchanged[direction]
            continue
        unchanged[direction] = _unchanged_direction(side)
        try:
            learned[direction] = find_stable_filter(side)
        except ValueError:
            learned[direction] = unchanged[direction]

    def combined(results: dict[str, dict], section: str, split: str) -> dict:
        parts = [results[side][section][split] for side in ("long", "short")]
        samples = sum(item["samples"] for item in parts)
        wins = sum(item["wins"] for item in parts)
        return {
            "samples": samples,
            "wins": wins,
            "losses": samples - wins,
            "win_rate": float(wins / samples * 100) if samples else None,
        }

    baseline = {
        split: combined(unchanged, "baseline", split)
        for split in ("all", "train", "validation")
    }
    improved_directions = [
        direction for direction in ("long", "short") if learned[direction]["rules"]
    ]
    if not improved_directions:
        raise ValueError(
            "做多、做空已分開檢查，但兩邊都沒有通過前段與後段驗證；"
            "因此保留上一版。只要任一方向通過，系統就會只更新該方向並產生新版本。"
        )
    chosen = {
        direction: learned[direction] if direction in improved_directions else unchanged[direction]
        for direction in ("long", "short")
    }
    filtered = {
        split: combined(chosen, "filtered", split)
        for split in ("all", "train", "validation")
    }
    return {
        "long": chosen["long"],
        "short": chosen["short"],
        "improved_directions": improved_directions,
        "rule_text": (
            f"做多：{chosen['long']['rule_text']}；"
            f"做空：{chosen['short']['rule_text']}"
        ),
        "baseline": baseline,
        "filtered": filtered,
        "removed_losses": sum(
            chosen[side]["removed_losses"] for side in ("long", "short")
        ),
        "removed_wins": sum(
            chosen[side]["removed_wins"] for side in ("long", "short")
        ),
        "score": sum(learned[side]["score"] for side in improved_directions),
    }


def _load_metadata(indicator_name: str) -> dict | None:
    path = STRATEGY_VERSIONS_DIR / f"{indicator_name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _next_version(root: str) -> int:
    versions = [1]
    for path in STRATEGY_VERSIONS_DIR.glob(f"{root}_v*.json"):
        match = re.search(r"_v(\d+)$", path.stem)
        if match:
            versions.append(int(match.group(1)))
    return max(versions) + 1


def _pine_expression(rule: dict, prefix: str) -> str:
    variables = {
        "rsi_14": f"{prefix}Rsi",
        "volume_ratio_20": f"{prefix}VolumeRatio",
        "trend_9_21": f"{prefix}Trend",
        "volatility_20": f"{prefix}Volatility",
        "close_position_20": f"{prefix}ClosePosition",
    }
    variable = variables[rule["feature"]]
    if rule["op"] == "le":
        return f"{variable} <= {rule['value']:.10g}"
    if rule["op"] == "ge":
        return f"{variable} >= {rule['value']:.10g}"
    return f"({variable} >= {rule['low']:.10g} and {variable} <= {rule['high']:.10g})"


def _signal_output_insertion_point(
    source: str,
    long_expression: str,
    short_expression: str,
) -> int:
    """Insert filters after signal declarations, before their visual/alert outputs."""
    expressions = f"{long_expression}\n{short_expression}"
    expression_names = set(re.findall(r"\b[A-Za-z_]\w*\b", expressions))
    declaration_ends: list[int] = []
    for name in expression_names:
        declaration = re.compile(
            rf"(?m)^[ \t]*(?:(?:var|varip)\s+)?"
            rf"(?:(?:bool|int|float|color|string)\s+)?"
            rf"{re.escape(name)}\s*=(?!=)"
        )
        declaration_ends.extend(
            source.find("\n", match.end()) + 1
            for match in declaration.finditer(source)
        )
    after_declarations = max(declaration_ends, default=0)
    output_positions = [
        position
        for marker in (
            "plotshape(",
            "plotchar(",
            "strategy.entry(",
            "alertcondition(",
        )
        if (position := source.find(marker, after_declarations)) >= 0
    ]
    if not output_positions:
        raise ValueError(
            "Pine 找不到位於多空訊號宣告後的輸出，無法安全插入過濾器。"
        )
    return min(output_positions)


def _write_pine(
    root: str,
    child: str,
    version: int,
    long_rules: list[dict],
    short_rules: list[dict],
    base_long_expression: str = "longSignal",
    base_short_expression: str = "shortSignal",
) -> Path:
    source_path = INDICATORS_DIR / f"{root}.pine"
    if not source_path.exists():
        raise FileNotFoundError(f"找不到原始 Pine：{source_path.name}")
    source = source_path.read_text(encoding="utf-8")
    split_at = _signal_output_insertion_point(
        source,
        base_long_expression,
        base_short_expression,
    )
    head, tail = source[:split_at], source[split_at:]
    prefix = f"aiV{version}"
    long_expression = " and ".join(
        _pine_expression(rule, prefix) for rule in long_rules
    ) or "true"
    short_expression = " and ".join(
        _pine_expression(rule, prefix) for rule in short_rules
    ) or "true"
    block = f"""
// AI improvement V{version}: learned from manually labeled wins and losses.
{prefix}Rsi = ta.rsi(close, 14)
{prefix}VolumeRatio = volume / ta.sma(volume, 20)
{prefix}Trend = ta.ema(close, 9) / ta.ema(close, 21) - 1
{prefix}Return = close / close[1] - 1
{prefix}Volatility = ta.stdev({prefix}Return, 20, false)
{prefix}Range = ta.highest(high, 20) - ta.lowest(low, 20)
{prefix}ClosePosition = {prefix}Range != 0 ? (close - ta.lowest(low, 20)) / {prefix}Range : 0.5
{prefix}LongFilter = {long_expression}
{prefix}ShortFilter = {short_expression}
improvedLongSignal = ({base_long_expression}) and {prefix}LongFilter
improvedShortSignal = ({base_short_expression}) and {prefix}ShortFilter

"""
    def replace_condition(text: str, expression: str, replacement: str) -> str:
        if re.fullmatch(r"[A-Za-z_]\w*", expression):
            return re.sub(rf"\b{re.escape(expression)}\b", replacement, text)
        replaced = text.replace(expression, replacement)
        if replaced != text:
            return replaced

        # PineTS may combine plotshape and alertcondition into one inferred
        # expression. Replace its latest declared signal variable in the output
        # section instead of requiring that synthetic combined text to exist.
        declarations: dict[str, int] = {}
        for name in set(re.findall(r"\b[A-Za-z_]\w*\b", expression)):
            pattern = re.compile(
                rf"(?m)^[ \t]*(?:(?:var|varip)\s+)?"
                rf"(?:(?:bool|int|float|color|string)\s+)?"
                rf"{re.escape(name)}\s*=(?!=)"
            )
            matches = list(pattern.finditer(source))
            if matches:
                declarations[name] = matches[-1].start()
        if not declarations:
            return text
        latest = max(declarations.values())
        for name, position in declarations.items():
            if position == latest:
                replaced = re.sub(
                    rf"\b{re.escape(name)}\b",
                    replacement,
                    replaced,
                )
        return replaced

    tail = replace_condition(tail, base_long_expression, "improvedLongSignal")
    tail = replace_condition(tail, base_short_expression, "improvedShortSignal")
    improved = head + block + tail
    improved = re.sub(
        r'(?P<kind>indicator|strategy)\("(?P<title>[^"]+)"',
        lambda match: f'{match.group("kind")}("{match.group("title")} AI V{version}"',
        improved,
        count=1,
    )
    target = INDICATORS_DIR / f"{child}.pine"
    target.write_text(improved, encoding="utf-8")
    return target


def improve_indicator(
    dataset_id: int, indicator_name: str, *, force_new: bool = False
) -> dict:
    existing_children = []
    for path in STRATEGY_VERSIONS_DIR.glob("*.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("parent") == indicator_name and metadata.get("dataset_id") == dataset_id:
            existing_children.append(metadata)
    if existing_children and not force_new:
        active_children = [
            item
            for item in existing_children
            if not item.get("superseded_by") and item.get("recommended", True)
        ]
        if active_children:
            return sorted(active_children, key=lambda item: item["version"])[-1]

    signals = list_signals(dataset_id, indicator_name)
    if signals.empty:
        raise ValueError("目前版本沒有訊號。")
    current_metadata = _load_metadata(indicator_name)
    root = current_metadata["root"] if current_metadata else indicator_name
    cumulative_long_rules = current_metadata.get("long_rules", []) if current_metadata else []
    cumulative_short_rules = current_metadata.get("short_rules", []) if current_metadata else []
    data = build_training_frame(
        dataset_id,
        indicator_name,
        labeled_only=True,
    )
    data = data[data["label_text"].isin(["win", "loss"])].copy()
    if data.empty:
        raise ValueError("至少需要 1 筆贏或輸標記才能分析。")
    comparison = feature_comparison(data)
    selected = find_directional_filters(data)
    long_rules = [*cumulative_long_rules, *selected["long"]["rules"]]
    short_rules = [*cumulative_short_rules, *selected["short"]["rules"]]
    version = _next_version(root)
    child = f"{root}_v{version}"
    dataset = get_dataset(dataset_id)
    frame = load_saved_frame(dataset["resolved_path"])
    root_source = (INDICATORS_DIR / f"{root}.pine").read_text(encoding="utf-8")
    root_output = compute_pine_signals(
        frame,
        root_source,
        ticker=str(dataset.get("symbol") or "LOCAL"),
        timeframe=str(dataset.get("interval") or "15m"),
        timezone=str(dataset.get("timezone") or "UTC"),
    )
    base_long_expression = str(root_output.attrs.get("long_expression") or "longSignal")
    base_short_expression = str(root_output.attrs.get("short_expression") or "shortSignal")
    pine_path = _write_pine(
        root,
        child,
        version,
        long_rules,
        short_rules,
        base_long_expression,
        base_short_expression,
    )
    try:
        output = compute_pine_signals(
            frame,
            pine_path.read_text(encoding="utf-8"),
            ticker=str(dataset.get("symbol") or "LOCAL"),
            timeframe=str(dataset.get("interval") or "15m"),
            timezone=str(dataset.get("timezone") or "UTC"),
            long_expression="improvedLongSignal",
            short_expression="improvedShortSignal",
        )
    except Exception:
        # A failed child must not remain as an unregistered strategy file.
        pine_path.unlink(missing_ok=True)
        raise
    output.insert(0, "timestamp", pd.to_datetime(frame["timestamp"], utc=True))
    records = signals_to_records(output)
    added = register_signals(dataset_id, child, f"pinets:{pine_path.name}", records)
    direction_counts = {
        direction: sum(record["direction"] == direction for record in records)
        for direction in ("long", "short")
    }
    metadata = {
        "schema_version": 1,
        "root": root,
        "parent": indicator_name,
        "child": child,
        "version": version,
        "dataset_id": dataset_id,
        "long_rules": long_rules,
        "short_rules": short_rules,
        "new_long_rules": selected["long"]["rules"],
        "new_short_rules": selected["short"]["rules"],
        "improved_directions": selected["improved_directions"],
        "rule_text": selected["rule_text"],
        "baseline": selected["baseline"],
        "filtered": selected["filtered"],
        "removed_losses": selected["removed_losses"],
        "removed_wins": selected["removed_wins"],
        "direction_results": {
            "long": selected["long"],
            "short": selected["short"],
        },
        "feature_comparison": comparison.to_dict(orient="records"),
        "signals_created": len(records),
        "signals_added": added,
        "direction_counts": direction_counts,
        "pine_path": str(pine_path),
        "engine": "PineTS",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    STRATEGY_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    (STRATEGY_VERSIONS_DIR / f"{child}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def list_improvements() -> list[dict]:
    STRATEGY_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in STRATEGY_VERSIONS_DIR.glob("*.json")
    ]
    return sorted(rows, key=lambda item: item["created_at"], reverse=True)


def delete_improvement_version(dataset_id: int, indicator_name: str) -> dict:
    """Delete one generated version after validating its lineage and file scope."""
    metadata = _load_metadata(indicator_name)
    if metadata is None or int(metadata.get("version", 1)) <= 1:
        raise ValueError("V1 是原始策略，不能刪除。")
    if int(metadata.get("dataset_id")) != int(dataset_id):
        raise ValueError("版本與目前資料集不一致，拒絕刪除。")
    children = [
        item["child"]
        for item in list_improvements()
        if int(item.get("dataset_id", -1)) == int(dataset_id)
        and item.get("parent") == indicator_name
    ]
    if children:
        names = "、".join(sorted(children))
        raise ValueError(f"請先刪除後續版本：{names}")

    signals = list_signals(dataset_id, indicator_name)
    samples_root = SAMPLES_DIR.resolve()
    sample_targets: list[Path] = []
    for relative in signals.get("sample_path", pd.Series(dtype=str)).dropna().unique():
        path = Path(str(relative))
        target = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
        if samples_root not in target.parents:
            raise ValueError(f"標記快照不在安全目錄內：{target.name}")
        sample_targets.append(target)

    generated_targets = [
        (INDICATORS_DIR / f"{indicator_name}.pine").resolve(),
        (STRATEGY_VERSIONS_DIR / f"{indicator_name}.json").resolve(),
    ]
    allowed_roots = {
        INDICATORS_DIR.resolve(),
        STRATEGY_VERSIONS_DIR.resolve(),
    }
    for target in generated_targets:
        if target.parent not in allowed_roots:
            raise ValueError(f"版本檔案不在安全目錄內：{target.name}")

    removed_signals = delete_indicator_signals(dataset_id, indicator_name)
    removed_files = 0
    for target in [*sample_targets, *generated_targets]:
        if target.exists():
            target.unlink()
            removed_files += 1
    return {
        "deleted": indicator_name,
        "parent": metadata["parent"],
        "signals": removed_signals,
        "files": removed_files,
    }
