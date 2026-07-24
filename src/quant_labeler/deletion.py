from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .config import (
    ADAPTERS_DIR,
    INDICATORS_DIR,
    MARKET_DIR,
    PROJECT_ROOT,
    SAMPLES_DIR,
    STRATEGY_VERSIONS_DIR,
)
from .improvement import list_improvements
from .storage import (
    dataset_path_reference_count,
    delete_dataset_record,
    delete_indicator_signals,
    get_dataset,
    list_signals,
)


def strategy_root(indicator_name: str) -> str:
    return re.sub(r"_v\d+$", "", indicator_name)


def _is_within(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path != resolved_root and resolved_root in resolved_path.parents


def _sample_targets(signals: pd.DataFrame) -> list[Path]:
    targets: set[Path] = set()
    values = signals.get("sample_path", pd.Series(dtype=str)).dropna().unique()
    for relative in values:
        path = Path(str(relative))
        target = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
        if not _is_within(target, SAMPLES_DIR):
            raise ValueError(f"標記快照不在安全目錄內：{target.name}")
        targets.add(target)
    return sorted(targets)


def _artifact_targets(
    names: set[str],
    metadata_names: set[str],
    preserve_shared: set[str],
) -> list[Path]:
    targets: set[Path] = set()
    for name in names - preserve_shared:
        targets.add((INDICATORS_DIR / f"{name}.pine").resolve())
        targets.add((ADAPTERS_DIR / f"{name}.py").resolve())
    for name in metadata_names:
        targets.add((STRATEGY_VERSIONS_DIR / f"{name}.json").resolve())

    allowed_roots = {
        INDICATORS_DIR.resolve(),
        ADAPTERS_DIR.resolve(),
        STRATEGY_VERSIONS_DIR.resolve(),
    }
    for target in targets:
        if target.parent not in allowed_roots:
            raise ValueError(f"策略檔案不在安全目錄內：{target.name}")
    return sorted(targets)


def _remove_files(targets: list[Path]) -> int:
    removed = 0
    for target in targets:
        if target.is_file():
            target.unlink()
            removed += 1
    return removed


def _dataset_improvements(dataset_id: int) -> list[dict]:
    return [
        item
        for item in list_improvements()
        if int(item.get("dataset_id", -1)) == int(dataset_id)
    ]


def version_branch_names(dataset_id: int, indicator_name: str) -> list[str]:
    """Return the selected generated version and every descendant that depends on it."""
    records = _dataset_improvements(dataset_id)
    by_name = {item["child"]: item for item in records}
    start = by_name.get(indicator_name)
    if start is None or int(start.get("version", 1)) <= 1:
        raise ValueError("只能從 V2 之後的版本刪除分支；V1 請刪除整個策略。")

    children: dict[str, list[str]] = {}
    for item in records:
        children.setdefault(str(item.get("parent", "")), []).append(item["child"])

    branch: set[str] = set()
    pending = [indicator_name]
    while pending:
        name = pending.pop()
        if name in branch:
            continue
        branch.add(name)
        pending.extend(children.get(name, []))
    return sorted(branch, key=lambda name: int(by_name[name]["version"]))


def delete_version_branch(dataset_id: int, indicator_name: str) -> dict:
    """Delete one generated version and all later versions that inherit from it."""
    records = _dataset_improvements(dataset_id)
    by_name = {item["child"]: item for item in records}
    names = version_branch_names(dataset_id, indicator_name)
    name_set = set(names)
    signals = list_signals(dataset_id)
    selected_signals = signals[signals["indicator_name"].isin(name_set)]
    sample_targets = _sample_targets(selected_signals)

    shared = set()
    for name in name_set:
        all_uses = list_signals(indicator_name=name)
        if not all_uses.empty and (all_uses["dataset_id"] != dataset_id).any():
            shared.add(name)
    artifact_targets = _artifact_targets(name_set, name_set, shared)

    removed_signals = 0
    for name in reversed(names):
        removed_signals += delete_indicator_signals(dataset_id, name)
    removed_files = _remove_files([*sample_targets, *artifact_targets])
    return {
        "deleted": names,
        "parent": by_name[indicator_name]["parent"],
        "signals": removed_signals,
        "files": removed_files,
    }


def delete_strategy(dataset_id: int, root_name: str) -> dict:
    """Delete one V1 strategy, all of its generated versions, signals and labels."""
    root_name = strategy_root(root_name)
    signals = list_signals(dataset_id)
    strategy_signals = signals[
        signals["indicator_name"].map(strategy_root) == root_name
    ]
    records = [
        item
        for item in _dataset_improvements(dataset_id)
        if item.get("root", strategy_root(item["child"])) == root_name
    ]
    names = set(strategy_signals["indicator_name"].unique().tolist())
    names.update(item["child"] for item in records)
    if (
        root_name not in names
        and not (INDICATORS_DIR / f"{root_name}.pine").exists()
        and not (ADAPTERS_DIR / f"{root_name}.py").exists()
    ):
        raise ValueError(f"找不到策略：{root_name}")
    names.add(root_name)

    sample_targets = _sample_targets(strategy_signals)
    shared = set()
    for name in names:
        all_uses = list_signals(indicator_name=name)
        if not all_uses.empty and (all_uses["dataset_id"] != dataset_id).any():
            shared.add(name)
    metadata_names = {item["child"] for item in records}
    artifact_targets = _artifact_targets(names, metadata_names, shared)

    removed_signals = sum(
        delete_indicator_signals(dataset_id, name) for name in sorted(names)
    )
    removed_files = _remove_files([*sample_targets, *artifact_targets])
    return {
        "deleted": root_name,
        "versions": sorted(names, key=lambda name: (name != root_name, name)),
        "signals": removed_signals,
        "files": removed_files,
    }


def delete_market(dataset_id: int) -> dict:
    """Delete one market record and every locally owned artifact attached to it."""
    dataset = get_dataset(dataset_id)
    signals = list_signals(dataset_id)
    names = set(signals["indicator_name"].unique().tolist())
    records = _dataset_improvements(dataset_id)
    names.update(item["child"] for item in records)
    names.update(item.get("root") for item in records if item.get("root"))

    sample_targets = _sample_targets(signals)
    shared = set()
    for name in names:
        all_uses = list_signals(indicator_name=name)
        if not all_uses.empty and (all_uses["dataset_id"] != dataset_id).any():
            shared.add(name)
    metadata_names = {item["child"] for item in records}
    artifact_targets = _artifact_targets(names, metadata_names, shared)

    market_target = Path(dataset["resolved_path"]).resolve()
    other_market_references = dataset_path_reference_count(
        dataset["path"],
        exclude_dataset_id=dataset_id,
    )
    remove_market_file = (
        market_target.is_file()
        and _is_within(market_target, MARKET_DIR)
        and other_market_references == 0
    )

    deleted_record = delete_dataset_record(dataset_id)
    targets = [*sample_targets, *artifact_targets]
    if remove_market_file:
        targets.append(market_target)
    removed_files = _remove_files(targets)
    return {
        "deleted": dataset_id,
        "market": f'{dataset["symbol"]} · {dataset["interval"]}',
        "signals": deleted_record["signals"],
        "strategies": len({strategy_root(name) for name in names}),
        "files": removed_files,
        "market_file_deleted": remove_market_file,
    }
