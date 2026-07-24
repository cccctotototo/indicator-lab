from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

from quant_labeler.config import LABEL_ZH, ensure_directories
from quant_labeler.deletion import (
    delete_market,
    delete_strategy,
    delete_version_branch,
    version_branch_names,
)
from quant_labeler.improvement import (
    analyze_indicator,
    improve_indicator,
    list_improvements,
)
from quant_labeler.labeling import save_label_snapshot
from quant_labeler.market import (
    INTERVAL_MS,
    load_binance_symbol_catalog,
    load_history_cache,
    load_saved_frame,
    sync_full_history,
)
from quant_labeler.storage import (
    ensure_dataset,
    get_dataset,
    initialize_database,
    list_datasets,
    list_signals,
    update_dataset_market_file,
)
from quant_labeler.strategy_import import import_strategy_v1, normalize_strategy_name
from quant_labeler.ui import (
    install_app_shell,
    page_header,
    selected_from_chart,
    sidebar_brand,
    signal_chart,
    signal_status_legend,
)

PAGE_IMPORT = "匯入策略"
PAGE_LABEL = "標記訊號"
PAGE_IMPROVE = "AI 改善"
PAGE_VERSIONS = "策略版本"
WORKFLOW_PAGES = (PAGE_IMPORT, PAGE_LABEL, PAGE_IMPROVE, PAGE_VERSIONS)

st.set_page_config(
    page_title="Indicator Lab",
    page_icon="IL",
    layout="wide",
    initial_sidebar_state="expanded",
)
install_app_shell()
ensure_directories()
initialize_database()


def version_number(name: str) -> int:
    if "_v" not in name:
        return 1
    try:
        return int(name.rsplit("_v", 1)[1])
    except ValueError:
        return 1


def strategy_root(name: str) -> str:
    return re.sub(r"_v\d+$", "", name)


def dataset_label(row) -> str:
    market = "U 本位永續" if row.market_type == "futures" else "現貨"
    return f"{row.symbol} · {row.interval} · {market}"


@st.cache_resource(show_spinner=False)
def cached_frame(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns
    return load_saved_frame(path)


def dataset_frame(dataset_id: int) -> pd.DataFrame:
    dataset = get_dataset(dataset_id)
    path = Path(dataset["resolved_path"])
    return cached_frame(str(path), path.stat().st_mtime_ns)


def pine_source(indicator_name: str) -> str | None:
    path = Path("indicators") / f"{indicator_name}.pine"
    return path.read_text(encoding="utf-8") if path.exists() else None


def indicators_for_dataset(dataset_id: int) -> list[str]:
    signals = list_signals(dataset_id)
    if signals.empty:
        return []
    return sorted(
        signals["indicator_name"].unique().tolist(),
        key=lambda name: (strategy_root(name), -version_number(name)),
    )


def default_indicator(dataset_id: int, indicators: list[str]) -> str | None:
    for name in indicators:
        signals = list_signals(dataset_id, name)
        if not signals.empty and signals["label"].isna().any():
            return name
    return indicators[0] if indicators else None


def switch_to(page: str, indicator: str | None = None) -> None:
    st.session_state.navigation = page
    if indicator:
        st.session_state.active_indicator = indicator


def delete_version_action(dataset_id: int, indicator_name: str) -> None:
    try:
        result = delete_version_branch(dataset_id, indicator_name)
    except (KeyError, ValueError) as exc:
        st.session_state.delete_error = str(exc)
        return
    st.session_state.pending_strategy_selection = {
        "dataset_id": dataset_id,
        "indicator_name": result["parent"],
    }
    st.session_state.selected_signal_id = None
    st.session_state.navigation = PAGE_VERSIONS
    st.session_state.delete_notice = (
        f'已刪除 {"、".join(f"V{version_number(name)}" for name in result["deleted"])}，'
        f'共清除 {result["signals"]:,} 筆訊號。'
    )
    cached_frame.clear()


def delete_strategy_action(dataset_id: int, root_name: str) -> None:
    try:
        result = delete_strategy(dataset_id, root_name)
    except (KeyError, ValueError) as exc:
        st.session_state.delete_error = str(exc)
        return
    remaining = indicators_for_dataset(dataset_id)
    st.session_state.selected_signal_id = None
    if remaining:
        next_indicator = remaining[0]
        st.session_state.pending_strategy_selection = {
            "dataset_id": dataset_id,
            "indicator_name": strategy_root(next_indicator),
        }
        st.session_state.navigation = PAGE_VERSIONS
    else:
        st.session_state.pop("active_strategy", None)
        st.session_state.pop("active_indicator", None)
        st.session_state.navigation = PAGE_IMPORT
    st.session_state.delete_notice = (
        f'已刪除策略 {result["deleted"]}、全部版本與 {result["signals"]:,} 筆訊號。'
    )
    cached_frame.clear()


def delete_market_action(dataset_id: int) -> None:
    try:
        result = delete_market(dataset_id)
    except (KeyError, ValueError) as exc:
        st.session_state.delete_error = str(exc)
        return
    for key in (
        "active_dataset",
        "active_strategy",
        "active_indicator",
        "selected_signal_id",
    ):
        st.session_state.pop(key, None)
    st.session_state.navigation = PAGE_IMPORT
    st.session_state.delete_notice = (
        f'已刪除市場 {result["market"]}、{result["strategies"]:,} 個策略與 '
        f'{result["signals"]:,} 筆訊號。'
    )
    cached_frame.clear()


@st.cache_data(ttl=21_600, show_spinner=False)
def symbol_catalog(market_type: str) -> tuple[list[dict], str | None]:
    return load_binance_symbol_catalog(market_type)


def symbol_label(row: dict) -> str:
    market = "永續" if row["market_type"] == "futures" else "現貨"
    return f"{row['base_asset']} / {row['quote_asset']}　·　{row['symbol']}　·　{market}"


FEATURE_NAMES = {
    "rsi_14": "RSI 14",
    "volume_ratio_20": "量能／20 根均量",
    "trend_9_21": "EMA 9／21 趨勢差",
    "volatility_20": "20 根波動率",
    "close_position_20": "20 根區間位置",
}


def rule_value_text(rule: dict) -> str:
    feature = rule["feature"]

    def value_text(value: float) -> str:
        raw = f"{float(value):.10g}"
        if feature in {"trend_9_21", "volatility_20", "close_position_20"}:
            return f"{raw}（{float(value) * 100:.6f}%）"
        if feature == "volume_ratio_20":
            return f"{raw} 倍"
        return raw

    if rule["op"] == "between":
        return f"{value_text(rule['low'])} ～ {value_text(rule['high'])}"
    operator = "≤" if rule["op"] == "le" else "≥"
    return f"{operator} {value_text(rule['value'])}"


def render_direction_rules(
    direction: str,
    item: dict,
    decisive: pd.DataFrame,
) -> None:
    direction_name = "做多" if direction == "long" else "做空"
    arrow = "↑" if direction == "long" else "↓"
    all_rules = item.get(f"{direction}_rules", [])
    new_rules = item.get(f"new_{direction}_rules", [])
    improved = direction in item.get("improved_directions", []) or bool(new_rules)
    side = decisive[decisive["direction"] == direction]
    direction_result = item.get("direction_results", {}).get(direction, {})
    if not side.empty:
        wins = int((side["label"] == "win").sum())
        rate = wins / len(side) * 100
        performance = f"實際 {rate:.1f}% · {wins} 贏／{len(side) - wins} 輸"
    else:
        stats = direction_result.get("filtered", {}).get("all", {})
        rate = stats.get("win_rate")
        performance = (
            f"AI 回測估計 {rate:.1f}% · {stats.get('samples', 0)} 筆樣本"
            if rate is not None
            else "尚無標記結果"
        )
    state = "本版 AI 改善" if improved else "完整沿用上一版"
    st.subheader(f"{arrow} {direction_name}")
    st.caption(performance)
    st.info(state)
    st.markdown("**有效過濾條件**")
    if not all_rules:
        st.caption("不增加 AI 數值過濾，保留上一版的原始訊號。")
    else:
        rows = [
            {
                "特徵": FEATURE_NAMES.get(rule["feature"], rule["feature"]),
                "來源": "本版新增" if rule in new_rules else "前版沿用",
                "條件": rule_value_text(rule),
            }
            for rule in all_rules
        ]
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={
                "特徵": st.column_config.TextColumn(width="medium"),
                "來源": st.column_config.TextColumn(width="small"),
                "條件": st.column_config.TextColumn(width="large"),
            },
        )
    validation = direction_result.get("filtered", {}).get("validation", {})
    baseline = direction_result.get("baseline", {}).get("all", {})
    filtered = direction_result.get("filtered", {}).get("all", {})
    if baseline.get("win_rate") is not None and filtered.get("win_rate") is not None:
        st.caption(
            f'AI 回測比較 {baseline["win_rate"]:.1f}% → {filtered["win_rate"]:.1f}% · '
            f'後段驗證 {validation.get("win_rate", 0):.1f}%'
        )


def render_workflow(navigation: str) -> None:
    active_step = WORKFLOW_PAGES.index(navigation) + 1
    st.progress(
        (active_step - 1) / (len(WORKFLOW_PAGES) - 1),
        text=f"步驟 {active_step}／{len(WORKFLOW_PAGES)} · {navigation}",
    )
    st.caption(" → ".join(WORKFLOW_PAGES))


def select_signal(signal_id: int) -> None:
    st.session_state.selected_signal_id = int(signal_id)


def mark_signal(
    signal_id: int,
    label: str,
    next_signal_id: int,
    frame: pd.DataFrame,
) -> None:
    """Persist one decision from the in-memory market frame, then advance."""
    save_label_snapshot(
        int(signal_id),
        label,
        "",
        20,
        60,
        30,
        frame=frame,
    )
    st.session_state.selected_signal_id = int(next_signal_id)


@st.fragment
def render_labeling_page(dataset_id: int, active_indicator: str) -> None:
    """Keep rapid labeling inside a fragment so the whole app does not rerun."""
    signals = (
        list_signals(dataset_id, active_indicator)
        .sort_values(["timestamp", "id"], ascending=[False, False])
        .reset_index(drop=True)
    )
    total = len(signals)
    completed = int(signals["label"].notna().sum())
    remaining = total - completed
    version = version_number(active_indicator)
    page_header(
        f"{PAGE_LABEL} · V{version}",
        "逐筆標記訊號為贏、輸或無效；完成後會自動前往下一筆，所有標記都能回頭修改。",
    )
    st.progress(
        completed / total if total else 0,
        text=f"已完成 {completed}／{total} 筆，剩下 {remaining} 筆",
    )
    if signals.empty:
        st.warning("目前版本沒有訊號。")
        return

    ids = signals["id"].astype(int).tolist()
    current = st.session_state.get("selected_signal_id")
    if current not in ids:
        unlabeled_ids = signals.loc[signals["label"].isna(), "id"].astype(int).tolist()
        current = unlabeled_ids[0] if unlabeled_ids else ids[-1]
        st.session_state.selected_signal_id = current
    position = ids.index(int(current))
    selected_row = signals.loc[signals["id"].astype(int) == int(current)].iloc[0]
    direction_text = "做多" if selected_row.direction == "long" else "做空"
    label_text = LABEL_ZH.get(selected_row.label, "未標記")
    local_time = selected_row.timestamp.tz_convert("Asia/Taipei").strftime(
        "%Y-%m-%d %H:%M"
    )
    top_left, top_middle, top_right = st.columns([1, 2.5, 1])
    top_left.button(
        "上一筆",
        disabled=position == 0,
        width="stretch",
        on_click=select_signal,
        args=(ids[position - 1] if position > 0 else int(current),),
    )
    with top_middle.container(border=True):
        st.markdown(f"**#{int(current)} · {direction_text}**")
        st.caption(
            f"{local_time} · 第 {position + 1}／{total} 筆 · 目前：{label_text}"
        )
    top_right.button(
        "下一筆",
        disabled=position == len(ids) - 1,
        width="stretch",
        on_click=select_signal,
        args=(
            ids[position + 1] if position + 1 < len(ids) else int(current),
        ),
    )

    frame = dataset_frame(dataset_id)
    signal_status_legend()
    event = st.plotly_chart(
        signal_chart(frame, signals, int(current), "Asia/Taipei", 60),
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key=f"chart_{dataset_id}_{active_indicator}",
    )
    clicked = selected_from_chart(event)
    if clicked is not None and clicked != int(current):
        st.session_state.selected_signal_id = clicked
        st.rerun(scope="fragment")

    st.subheader("標記這筆訊號")
    st.caption("可以返回上一筆重新修改；無效訊號不會交給 AI 學習。")
    next_signal_id = (
        ids[position + 1] if position + 1 < len(ids) else int(current)
    )
    win_column, loss_column, invalid_column = st.columns(3)
    win_column.button(
        "贏",
        type="primary",
        width="stretch",
        on_click=mark_signal,
        args=(int(current), "win", next_signal_id, frame),
    )
    loss_column.button(
        "輸",
        width="stretch",
        on_click=mark_signal,
        args=(int(current), "loss", next_signal_id, frame),
    )
    invalid_column.button(
        "無效",
        width="stretch",
        on_click=mark_signal,
        args=(int(current), "invalid", next_signal_id, frame),
    )
    if remaining == 0:
        st.success("這一版已全部標記完成；仍可用上一筆／下一筆回頭修改。")
        if st.button(
            f"前往 {PAGE_IMPROVE}",
            type="primary",
            width="stretch",
        ):
            switch_to(PAGE_IMPROVE, active_indicator)
            st.rerun(scope="app")


pending_selection = st.session_state.pop("pending_strategy_selection", None)
if pending_selection:
    st.session_state.active_dataset = pending_selection["dataset_id"]
    st.session_state.active_strategy = pending_selection["indicator_name"]
    st.session_state.active_indicator = pending_selection["indicator_name"]


datasets = list_datasets()
real_datasets = datasets[datasets["source"] != "demo:synthetic"] if not datasets.empty else datasets
available_datasets = real_datasets if not real_datasets.empty else datasets
if st.session_state.get("navigation") == "版本紀錄":
    st.session_state.navigation = PAGE_VERSIONS
if st.session_state.get("navigation") not in WORKFLOW_PAGES:
    st.session_state.navigation = PAGE_LABEL

with st.sidebar:
    sidebar_brand()
    navigation = st.radio(
        "流程",
        WORKFLOW_PAGES,
        key="navigation",
    )
    st.divider()
    st.subheader("AI 研究工作區")
    if available_datasets.empty:
        dataset_id = None
        st.info(f"先從「{PAGE_IMPORT}」建立第一個市場與 V1。")
    else:
        dataset_options = available_datasets["id"].astype(int).tolist()
        label_map = {
            int(row.id): dataset_label(row)
            for row in available_datasets.itertuples(index=False)
        }
        market_labels = [label_map[value] for value in dataset_options]
        dataset_by_label = {label: value for value, label in label_map.items()}
        selected_state = st.session_state.get("active_dataset")
        if isinstance(selected_state, int) and selected_state in label_map:
            st.session_state.active_dataset = label_map[selected_state]
        elif selected_state not in market_labels:
            st.session_state.active_dataset = market_labels[0]
        market_selection = st.selectbox(
            "研究市場",
            market_labels,
            key="active_dataset",
            help=(
                f"這裡只列出可供{PAGE_LABEL}與{PAGE_IMPROVE}使用的固定研究資料；"
                f"新增研究市場請按下方「{PAGE_IMPORT}」。"
            ),
        )
        dataset_id = dataset_by_label.get(market_selection)
    all_indicators = indicators_for_dataset(dataset_id) if dataset_id else []
    if all_indicators:
        strategy_options = sorted({strategy_root(name) for name in all_indicators})
        active_name = st.session_state.get("active_indicator", "")
        inferred_strategy = strategy_root(active_name) if active_name else ""
        if st.session_state.get("active_strategy") not in strategy_options:
            st.session_state.active_strategy = (
                inferred_strategy if inferred_strategy in strategy_options else strategy_options[0]
            )
        active_strategy = st.selectbox(
            "目前策略",
            strategy_options,
            key="active_strategy",
            format_func=lambda name: name,
        )
        indicators = [
            name for name in all_indicators if strategy_root(name) == active_strategy
        ]
        improvement_records = list_improvements()
        rejected = {
            item["child"]: item["parent"]
            for item in improvement_records
            if item.get("recommended") is False
        }
        superseded = {
            item["child"]: item["superseded_by"]
            for item in improvement_records
            if item.get("superseded_by") in indicators
        }
        if st.session_state.get("active_indicator") in superseded:
            st.session_state.active_indicator = superseded[
                st.session_state.active_indicator
            ]
        selectable_indicators = [name for name in indicators if name not in rejected]
        initial = default_indicator(dataset_id, selectable_indicators)
        if st.session_state.get("active_indicator") not in indicators:
            st.session_state.active_indicator = initial
        active_indicator = st.selectbox(
            "目前策略版本",
            indicators,
            key="active_indicator",
            format_func=lambda name: (
                f"V{version_number(name)} · {name}"
                + (" · 不採用" if name in rejected else "")
            ),
        )
    else:
        active_strategy = None
        active_indicator = None
        st.info(f"這個市場還沒有策略，請從「{PAGE_IMPORT}」建立 V1。")
    st.caption("AI 只能降低歷史資料中的輸單特徵，不能保證未來獲利。")
    if dataset_id:
        current_market = get_dataset(dataset_id)
        with st.expander("刪除資料"):
            if active_strategy:
                st.markdown(f"**刪除策略**　{active_strategy}")
                st.caption("刪除 V1、全部改善版本、訊號與人工標記；市場 K 線保留。")
                confirm_strategy = st.checkbox(
                    "我確認刪除這個策略的全部版本",
                    key=f"confirm_strategy_delete_{dataset_id}_{active_strategy}",
                )
                st.button(
                    "刪除目前策略",
                    disabled=not confirm_strategy,
                    width="stretch",
                    key=f"delete_strategy_{dataset_id}_{active_strategy}",
                    on_click=delete_strategy_action,
                    args=(dataset_id, active_strategy),
                )
                st.divider()
            st.markdown(
                f'**刪除市場**　{current_market["symbol"]} · {current_market["interval"]}'
            )
            st.caption("刪除這個市場、其本機 K 線、全部策略、版本、訊號與人工標記。")
            confirm_market = st.checkbox(
                "我確認刪除這個市場的全部資料",
                key=f"confirm_market_delete_{dataset_id}",
            )
            st.button(
                "刪除目前市場",
                disabled=not confirm_market,
                width="stretch",
                key=f"delete_market_{dataset_id}",
                on_click=delete_market_action,
                args=(dataset_id,),
            )

render_workflow(navigation)
delete_notice = st.session_state.pop("delete_notice", None)
delete_error = st.session_state.pop("delete_error", None)
if delete_notice:
    st.success(delete_notice)
if delete_error:
    st.error(delete_error)


if navigation == PAGE_IMPORT:
    page_header(
        PAGE_IMPORT,
        "選擇市場並加入 Pine 原碼，建立可標記的 V1。資料只保存在這台電腦。",
    )

    st.subheader("策略來源")
    source_column, setup_column = st.columns([1.35, 1])
    with source_column:
        strategy_name_input = st.text_input(
            "策略名稱",
            placeholder="例如 wickless_candle_long_short",
            help="使用英文字母、數字與底線；系統會自動整理成安全檔名。",
            key="import_strategy_name",
        )
        pine_upload = st.file_uploader(
            "上傳 Pine 檔",
            type=["pine", "txt"],
            key="import_pine_file",
        )
        pine_paste = st.text_area(
            "或直接貼上完整 Pine 程式碼",
            height=310,
            placeholder="//@version=6\nindicator(...)\n...",
            key="import_pine_text",
        )
    with setup_column:
        st.markdown("**Pine 執行引擎**")
        st.success("PineTS · 本機直接執行指標")
        st.caption(
            "系統會從 longSignal／shortSignal、買賣提示與 plotshape 自動辨識做多和做空。"
        )
        with st.expander("訊號名稱辨識不到時才需要填寫"):
            import_long_expression = st.text_input(
                "做多條件名稱或運算式",
                placeholder="例如 buySignal",
                key="import_long_expression",
            )
            import_short_expression = st.text_input(
                "做空條件名稱或運算式",
                placeholder="例如 sellSignal",
                key="import_short_expression",
            )
            st.caption("一般指標請留空；只有自動辨識方向失敗時才需要指定。")

    st.divider()
    st.subheader("市場與研究範圍")
    market_choices = ["建立新的 Binance 研究市場"]
    if dataset_id is not None:
        market_choices.append("使用左側目前市場")
    market_source = st.radio(
        "V1 要套用在哪一份行情",
        market_choices,
        horizontal=True,
        key="import_market_source",
    )
    if market_source == "建立新的 Binance 研究市場":
        import_market_col, import_symbol_col, import_interval_col, import_timezone_col = st.columns([1.1, 2.5, 1, 1.35])
        import_market_type = import_market_col.selectbox(
            "市場",
            ["futures", "spot"],
            format_func=lambda value: "U 本位永續" if value == "futures" else "現貨",
            key="import_market_type",
        )
        catalog, catalog_error = symbol_catalog(import_market_type)
        catalog_by_symbol = {row["symbol"]: row for row in catalog}
        symbol_options = list(catalog_by_symbol)
        preferred_symbol = st.session_state.get("import_symbol", "BTCUSDT")
        symbol_key = f"import_symbol_choice_{import_market_type}"
        if st.session_state.get(symbol_key) not in symbol_options:
            st.session_state[symbol_key] = (
                preferred_symbol if preferred_symbol in symbol_options else symbol_options[0]
            )
        import_symbol = import_symbol_col.selectbox(
            "交易對",
            symbol_options,
            format_func=lambda value: symbol_label(catalog_by_symbol[value]),
            key=symbol_key,
            help="直接輸入 ETH、ETHUSDT 或報價幣即可搜尋，不需要自己建立代號。",
        )
        import_interval = import_interval_col.selectbox(
            "K 線週期",
            list(INTERVAL_MS),
            index=list(INTERVAL_MS).index("15m"),
            key="import_interval",
        )
        import_timezone = import_timezone_col.selectbox(
            "顯示時區",
            ["Asia/Taipei", "UTC", "Asia/Tokyo", "Asia/Hong_Kong", "America/New_York", "Europe/London"],
            key="import_timezone",
        )
        st.caption(
            f"資料範圍：全部可用歷史 · 可搜尋 {len(symbol_options):,} 個 Binance "
            f"{'永續合約' if import_market_type == 'futures' else '現貨交易對'}。"
        )
        if catalog_error:
            st.warning("目前無法更新完整交易對目錄，暫時顯示離線熱門清單；連線恢復後會自動更新。")
        import_cache = load_history_cache(import_symbol, import_interval, import_market_type) if import_symbol else pd.DataFrame()
        if not import_cache.empty:
            st.caption(
                f"本機已有 {len(import_cache):,} 根 K 線："
                f"{import_cache['timestamp'].min():%Y-%m-%d} → {import_cache['timestamp'].max():%Y-%m-%d}；"
                "建立 V1 時會自動補到 Binance 最早可用 K 線，並更新至現在。"
            )

    st.divider()
    if st.button("驗證策略並建立 V1", type="primary", width="stretch"):
        try:
            pine_source_text = (
                pine_upload.getvalue().decode("utf-8-sig")
                if pine_upload is not None
                else pine_paste
            )
            normalized_name = normalize_strategy_name(strategy_name_input)
            with st.spinner("正在同步全部歷史行情，並用 PineTS 執行指標…"):
                if market_source == "使用左側目前市場":
                    target_dataset_id = int(dataset_id)
                    current_dataset = get_dataset(target_dataset_id)
                    if current_dataset["market_type"] in ("futures", "spot"):
                        target_frame, cache_path, _ = sync_full_history(
                            current_dataset["symbol"],
                            current_dataset["interval"],
                            current_dataset["market_type"],
                        )
                        update_dataset_market_file(
                            target_dataset_id,
                            current_dataset["symbol"],
                            current_dataset["interval"],
                            current_dataset["market_type"],
                            current_dataset["timezone"],
                            target_frame,
                            cache_path,
                            "web:binance-full-history",
                        )
                        cached_frame.clear()
                    else:
                        target_frame = dataset_frame(target_dataset_id)
                else:
                    target_frame, cache_path, _ = sync_full_history(
                        import_symbol,
                        import_interval,
                        import_market_type,
                    )
                    target_dataset_id = ensure_dataset(
                        import_symbol,
                        import_interval,
                        import_market_type,
                        import_timezone,
                        target_frame,
                        cache_path,
                        "web:binance-full-history",
                    )
                result = import_strategy_v1(
                    target_dataset_id,
                    target_frame,
                    normalized_name,
                    pine_source_text,
                    long_expression=import_long_expression or None,
                    short_expression=import_short_expression or None,
                )
            st.session_state.strategy_import_result = result
            st.session_state.pending_strategy_selection = {
                "dataset_id": target_dataset_id,
                "indicator_name": normalized_name,
            }
            st.session_state.selected_signal_id = None
        except Exception as exc:
            st.error(f"{PAGE_IMPORT}失敗：{exc}")

    imported = st.session_state.get("strategy_import_result")
    if imported:
        st.success(
            f"V1 · {imported['indicator_name']} 已建立：共 {imported['signals']:,} 筆訊號，"
            f"做多 {imported['long']:,} 筆、做空 {imported['short']:,} 筆。"
        )
        if imported["long"] == 0 or imported["short"] == 0:
            st.warning("這份 V1 只有單一方向訊號；AI 不會憑空建立另一個方向，請先確認原始 Pine 條件。")
        if st.button(
            f"前往 {PAGE_LABEL} · V1",
            type="primary",
            width="stretch",
            on_click=switch_to,
            args=(PAGE_LABEL, imported["indicator_name"]),
        ):
            pass
    st.stop()


if dataset_id is None or active_indicator is None:
    st.title("尚未準備好策略資料")
    st.info(f"請先到「{PAGE_IMPORT}」建立 V1。")
    st.stop()


if navigation == PAGE_LABEL:
    render_labeling_page(int(dataset_id), active_indicator)


elif navigation == PAGE_IMPROVE:
    initial_analysis = analyze_indicator(dataset_id, active_indicator)
    remaining = initial_analysis["remaining"]
    current_version = version_number(active_indicator)
    page_header(
        f"{PAGE_IMPROVE} · V{current_version}",
        f"比較多空表現與贏輸特徵。只有你按下「使用 {PAGE_IMPROVE}」，系統才會建立下一版。",
    )
    long_actual = initial_analysis["directions"]["long"]
    short_actual = initial_analysis["directions"]["short"]
    overall_actual = initial_analysis["overall"]

    def analysis_rate(stats: dict) -> str:
        return "—" if stats["win_rate"] is None else f"{stats['win_rate']:.1f}%"

    m1, m2, m3 = st.columns(3)
    m1.metric(
        "做多勝率",
        analysis_rate(long_actual),
        help=f"{long_actual['wins']} 贏／{long_actual['losses']} 輸，共 {long_actual['samples']} 筆",
    )
    m2.metric(
        "做空勝率",
        analysis_rate(short_actual),
        help=f"{short_actual['wins']} 贏／{short_actual['losses']} 輸，共 {short_actual['samples']} 筆",
    )
    m3.metric(
        "綜合勝率",
        analysis_rate(overall_actual),
        help=f"{overall_actual['wins']} 贏／{overall_actual['losses']} 輸，共 {overall_actual['samples']} 筆有效標記",
    )
    st.caption(
        f'有效標記 {initial_analysis["decisive"]} 筆 · '
        f'無效 {initial_analysis["invalid"]} 筆'
    )
    comparisons = initial_analysis["feature_comparison"]
    if comparisons:
        st.subheader("贏輸特徵比較")
        feature_rows = [
            {
                "特徵": row["name"],
                "贏單中位數": f'{row["win_median"]:.4g}',
                "輸單中位數": f'{row["loss_median"]:.4g}',
                "判讀": f'贏單{row["winner_tendency"]}，輸單{row["loser_tendency"]}',
            }
            for row in comparisons[:5]
        ]
        st.dataframe(
            pd.DataFrame(feature_rows),
            hide_index=True,
            width="stretch",
            column_config={
                "特徵": st.column_config.TextColumn(width="medium"),
                "贏單中位數": st.column_config.TextColumn(width="small"),
                "輸單中位數": st.column_config.TextColumn(width="small"),
                "判讀": st.column_config.TextColumn(width="large"),
            },
        )
    elif initial_analysis["decisive"]:
        profile_rows = [
            {
                "特徵": row["name"],
                "目前樣本中位數": f'{row["median"]:.4g}',
                "有效數值": row["samples"],
            }
            for row in initial_analysis.get("feature_profile", [])
        ]
        st.subheader("目前已標記樣本特徵")
        if profile_rows:
            st.dataframe(
                pd.DataFrame(profile_rows),
                hide_index=True,
                width="stretch",
            )
        st.info(
            "分析已完成。目前只有贏或只有輸，因此先顯示現有樣本特徵；"
            "未來若出現另一類標記，系統會自動增加贏輸差異比較。"
        )
    else:
        st.info(f"先完成「{PAGE_LABEL} · V1」，這裡就會自動出現多空實際勝率與贏輸特徵。")
    if remaining:
        st.info(
            f"尚有 {remaining} 筆未標記；不影響分析。"
            f"本次只使用目前 {initial_analysis['decisive']} 筆贏／輸標記，"
            "未標記、無效與打平資料不會被當成贏或輸。"
        )
        if st.button(
            f"繼續 {PAGE_LABEL}（選用）",
            width="stretch",
            on_click=switch_to,
            args=(PAGE_LABEL, active_indicator),
        ):
            pass

    existing = next(
        (
            item
            for item in list_improvements()
            if item["parent"] == active_indicator
            and int(item["dataset_id"]) == dataset_id
            and item.get("recommended", True)
        ),
        None,
    )
    if existing is None:
        if st.button(
            f"執行 {PAGE_IMPROVE}，產生 V{current_version + 1}",
            type="primary",
            width="stretch",
        ):
            try:
                with st.spinner("正在比較特徵、用後段資料驗證，並產生下一版…"):
                    existing = improve_indicator(dataset_id, active_indicator)
                st.session_state.latest_improvement = existing
                st.rerun()
            except ValueError as exc:
                st.info(f"分析完成：{exc}")
            except Exception as exc:
                st.error(f"{PAGE_IMPROVE}失敗：{exc}")
    else:
        st.session_state.latest_improvement = existing
    result = st.session_state.get("latest_improvement")
    if result and result.get("parent") == active_indicator:
        st.subheader(f"{PAGE_IMPROVE}結果 · V{result['version']}")
        st.success(
            f'{result["rule_text"]} · 減少 {result["removed_losses"]} 筆輸單，'
            f'同時犧牲 {result["removed_wins"]} 筆贏單。'
        )
        before = result["baseline"]["all"]["win_rate"]
        after = result["filtered"]["all"]["win_rate"]
        validation = result["filtered"]["validation"]["win_rate"]
        r1, r2, r3 = st.columns(3)
        r1.metric("原本勝率", f"{before:.1f}%")
        r2.metric("過濾後綜合勝率", f"{after:.1f}%", delta=f"{after-before:+.1f}%")
        r3.metric("後段驗證勝率", f"{validation:.1f}%")
        improved_directions = result.get("improved_directions", [])
        if improved_directions:
            improved_text = "、".join(
                "做多" if direction == "long" else "做空"
                for direction in improved_directions
            )
            st.info(
                f"{PAGE_IMPROVE}方向：{improved_text}。"
                "多、空分別驗收；未進步的方向完整沿用上一版。"
            )
        direction_results = result.get("direction_results", {})
        if direction_results:
            long_rate = direction_results["long"]["filtered"]["all"]["win_rate"]
            short_rate = direction_results["short"]["filtered"]["all"]["win_rate"]
            st.caption(
                f"分方向量化結果：做多 {long_rate:.1f}% · 做空 {short_rate:.1f}%"
            )
        st.success(
            f"已產生 {result['child']}，共 {result['signals_created']} 筆新訊號："
            f"做多 {result.get('direction_counts', {}).get('long', 0)} 筆、"
            f"做空 {result.get('direction_counts', {}).get('short', 0)} 筆。"
        )
        code = pine_source(result["child"])
        if code:
            with st.expander("複製 Pine 到 TradingView", expanded=True):
                st.caption("按程式碼框右上角的複製圖示，再貼到 TradingView Pine Editor。")
                st.code(code, language="javascript", line_numbers=True)
        if st.button(
            f"前往 {PAGE_LABEL} · V{result['version']}",
            type="primary",
            width="stretch",
            on_click=switch_to,
            args=(PAGE_LABEL, result["child"]),
        ):
            pass


elif navigation == PAGE_VERSIONS:
    root_indicator = strategy_root(active_indicator)
    page_header(
        PAGE_VERSIONS,
        "選擇一個版本，查看實際表現、多空過濾值與可複製的 Pine 程式碼。",
    )
    root_signals = list_signals(dataset_id, root_indicator)
    root_decisive = root_signals[root_signals["label"].isin(["win", "loss"])]
    root_wins = int((root_decisive["label"] == "win").sum())
    root_rate = root_wins / len(root_decisive) * 100 if len(root_decisive) else None
    improvements = [
        item
        for item in list_improvements()
        if int(item["dataset_id"]) == dataset_id
        and item.get("root", strategy_root(item["child"])) == root_indicator
    ]
    improvements.sort(key=lambda item: int(item["version"]))
    version_views = [
        {
            "version": 1,
            "name": root_indicator,
            "item": None,
            "signals": root_signals,
            "decisive": root_decisive,
            "actual_rate": root_rate,
            "displayed_rate": root_rate,
        }
    ]
    for item in improvements:
        version_signals = list_signals(dataset_id, item["child"])
        decisive = version_signals[version_signals["label"].isin(["win", "loss"])]
        actual_wins = int((decisive["label"] == "win").sum())
        actual_rate = actual_wins / len(decisive) * 100 if len(decisive) else None
        estimated_rate = item.get("filtered", {}).get("all", {}).get("win_rate")
        version_views.append(
            {
                "version": int(item["version"]),
                "name": item["child"],
                "item": item,
                "signals": version_signals,
                "decisive": decisive,
                "actual_rate": actual_rate,
                "displayed_rate": actual_rate if actual_rate is not None else estimated_rate,
            }
        )

    view_by_version = {view["version"]: view for view in version_views}
    version_options = list(view_by_version)
    picker_key = f"version_picker_{dataset_id}_{root_indicator}"
    preferred_version = version_number(active_indicator)
    if st.session_state.get(picker_key) not in version_options:
        st.session_state[picker_key] = (
            preferred_version if preferred_version in version_options else version_options[-1]
        )

    def version_picker_label(value: int) -> str:
        rate = view_by_version[value]["displayed_rate"]
        return f'V{value} · {"—" if rate is None else f"{rate:.1f}%"}'

    st.caption(f"策略：{root_indicator}")
    selected_version = st.segmented_control(
        "選擇版本",
        version_options,
        selection_mode="single",
        format_func=version_picker_label,
        key=picker_key,
        width="stretch",
    )
    selected = view_by_version[selected_version or version_options[-1]]
    selected_item = selected["item"]
    decisive = selected["decisive"]
    displayed_rate = selected["displayed_rate"]
    rate_label = "綜合實際" if selected["actual_rate"] is not None else "AI 回測估計"

    if selected_item is None:
        status_text = "基準版"
        change_text = "原始多空條件"
        meta_items = [
            f'{len(selected["signals"]):,} 筆訊號',
            f'{len(decisive):,} 筆有效標記',
            "未套用 AI 過濾",
        ]
    else:
        improved_directions = selected_item.get("improved_directions", []) or [
            direction
            for direction in ("long", "short")
            if selected_item.get(f"new_{direction}_rules")
        ]
        improved_text = "、".join(
            "做多" if direction == "long" else "做空"
            for direction in improved_directions
        ) or "無新增條件"
        change_text = f"本版 AI 改善：{improved_text}"
        status_text = "已採用"
        if selected_item.get("recommended") is False:
            status_text = "不採用"
        if selected_item.get("superseded_by"):
            status_text = "已被後續版本取代"
        before = selected_item.get("baseline", {}).get("all", {}).get("win_rate")
        after = selected_item.get("filtered", {}).get("all", {}).get("win_rate")
        comparison = (
            f"{before:.1f}% → {after:.1f}%"
            if before is not None and after is not None
            else "資料不足"
        )
        meta_items = [
            f'{len(selected["signals"]):,} 筆訊號',
            f"AI 回測估計 {comparison}",
            f'排除輸單 {selected_item.get("removed_losses", 0)} 筆',
            f'排除贏單 {selected_item.get("removed_wins", 0)} 筆',
        ]

    with st.container(border=True):
        summary_left, summary_right = st.columns([3, 1], vertical_alignment="center")
        summary_left.subheader(f'V{selected["version"]} · {selected["name"]}')
        summary_left.caption(f"{change_text} · {status_text}")
        summary_right.metric(
            rate_label,
            "—" if displayed_rate is None else f"{displayed_rate:.1f}%",
        )
        st.caption(" · ".join(meta_items))
        st.divider()

        long_column, short_column = st.columns(2)
        if selected_item is None:
            for column, direction in ((long_column, "long"), (short_column, "short")):
                with column:
                    side = decisive[decisive["direction"] == direction]
                    wins = int((side["label"] == "win").sum())
                    rate = wins / len(side) * 100 if len(side) else None
                    direction_name = "做多" if direction == "long" else "做空"
                    arrow = "↑" if direction == "long" else "↓"
                    performance = (
                        f"實際 {rate:.1f}% · {wins} 贏／{len(side) - wins} 輸"
                        if rate is not None
                        else "尚無標記結果"
                    )
                    st.subheader(f"{arrow} {direction_name}")
                    st.caption(performance)
                    st.info("原始條件")
                    st.markdown("**有效過濾條件**")
                    st.caption(
                        f'沿用 V1 的 {"longSignal" if direction == "long" else "shortSignal"}；'
                        "沒有額外數值過濾。"
                    )
        else:
            with long_column:
                render_direction_rules("long", selected_item, decisive)
            with short_column:
                render_direction_rules("short", selected_item, decisive)

        action_left, action_right = st.columns([1, 2], vertical_alignment="center")
        if action_left.button(
            f'前往 {PAGE_LABEL} · V{selected["version"]}',
            type="primary",
            width="stretch",
            on_click=switch_to,
            args=(PAGE_LABEL, selected["name"]),
        ):
            pass
        action_right.caption("選中的版本會成為目前版本；原始 Pine 與其他版本不受影響。")

        code = pine_source(selected["name"])
        if code:
            with st.expander(f'複製 V{selected["version"]} Pine 到 TradingView'):
                st.caption("按程式碼框右上角的複製圖示，再貼到 TradingView Pine Editor。")
                st.code(code, language="javascript", line_numbers=True)

        if selected_item is not None:
            delete_name = selected_item["child"]
            branch_names = version_branch_names(dataset_id, delete_name)
            branch_labels = "、".join(
                f"V{version_number(name)}" for name in branch_names
            )
            with st.expander("刪除這個版本"):
                st.caption(
                    f"將刪除 {branch_labels} 的訊號、標記與 Pine 檔；"
                    f"V1 至 V{selected['version'] - 1} 會保留。"
                )
                confirm_version = st.checkbox(
                    f"我確認刪除 {branch_labels}",
                    key=f"confirm_version_delete_{dataset_id}_{delete_name}",
                )
                st.button(
                    f"刪除 {branch_labels}",
                    disabled=not confirm_version,
                    width="stretch",
                    key=f"delete_version_{dataset_id}_{delete_name}",
                    on_click=delete_version_action,
                    args=(dataset_id, delete_name),
                )
