from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import LABEL_ZH
from .labeling import locate_signal_index

TIMEZONES = [
    "Asia/Taipei",
    "UTC",
    "Asia/Tokyo",
    "Asia/Hong_Kong",
    "America/New_York",
    "Europe/London",
]

SIGNAL_STATUS_COLORS = {
    "win": "#138A72",
    "loss": "#D24B39",
    "breakeven": "#587189",
    "invalid": "#8B8588",
    "unlabeled": "#777174",
    "selected": "#2563EB",
}


def signal_marker_color(
    label: str | None,
    signal_id: int,
    selected_id: int | None,
) -> str:
    """Return a semantic status color, with the current signal in focus blue."""
    if selected_id is not None and signal_id == selected_id:
        return SIGNAL_STATUS_COLORS["selected"]
    return SIGNAL_STATUS_COLORS.get(label or "unlabeled", SIGNAL_STATUS_COLORS["unlabeled"])


APP_SHELL_STYLE = """
<style>
:root {
    --il-signal-red: oklch(0.57 0.18 14);
    --il-canvas: oklch(1 0 0);
    --il-ink: oklch(0.20 0.012 14);
    --il-muted-ink: oklch(0.47 0.018 14);
    --il-rule: oklch(0.89 0.008 14);
}

/* Indicator Lab app shell: remove Streamlit chrome without disabling sidebar controls. */
header[data-testid="stHeader"] {
    height: 0 !important;
    min-height: 0 !important;
    background: transparent !important;
    border: 0 !important;
    overflow: visible !important;
    visibility: visible !important;
}

header[data-testid="stHeader"] [data-testid="stAppDeployButton"],
header[data-testid="stHeader"] [data-testid="stMainMenu"],
header[data-testid="stHeader"] [data-testid="stToolbarActions"] {
    display: none !important;
}

header[data-testid="stHeader"] [data-testid="stToolbar"] {
    display: flex !important;
    height: 0 !important;
    min-height: 0 !important;
    padding: 0 !important;
    background: transparent !important;
    overflow: visible !important;
    pointer-events: none !important;
}

[data-testid="stMainBlockContainer"] {
    padding-top: 1rem !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
    height: 0 !important;
    min-height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: visible !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
    position: absolute !important;
    top: 0.5rem !important;
    right: 0 !important;
    z-index: 2 !important;
    display: flex !important;
    width: 2.75rem !important;
    height: 2.75rem !important;
    align-items: center !important;
    justify-content: center !important;
    visibility: visible !important;
    opacity: 1 !important;
}

[data-testid="stSidebarCollapsedControl"] {
    display: block !important;
    position: fixed !important;
    top: 0.5rem !important;
    left: 0.5rem !important;
    z-index: 100 !important;
}

[data-testid="stExpandSidebarButton"] {
    position: fixed !important;
    top: 0.5rem !important;
    left: 0.5rem !important;
    z-index: 101 !important;
    display: flex !important;
    width: 2.75rem !important;
    height: 2.75rem !important;
    min-width: 2.75rem !important;
    min-height: 2.75rem !important;
    align-items: center !important;
    justify-content: center !important;
    color: var(--il-ink) !important;
    background: var(--il-canvas) !important;
    border: 1px solid var(--il-rule) !important;
    border-radius: 0.375rem !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
}

.indicator-lab-brand {
    display: flex;
    min-height: 2.75rem;
    align-items: center;
    gap: 0.625rem;
    padding: 0 2.75rem 0 0;
    margin: 0.5rem 0 1rem;
    font-family: "Noto Sans TC", system-ui, sans-serif;
}

.indicator-lab-brand__mark {
    display: inline-flex;
    width: 2.125rem;
    height: 2.125rem;
    flex: 0 0 2.125rem;
    align-items: center;
    justify-content: center;
    border-radius: 0.375rem;
    color: var(--il-canvas);
    background: var(--il-signal-red);
    font-size: 0.75rem;
    font-weight: 750;
    line-height: 1;
}

.indicator-lab-brand__copy {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 0.125rem;
}

.indicator-lab-brand__title {
    color: var(--il-ink);
    font-size: 0.875rem;
    font-weight: 700;
    line-height: 1.2;
}

.indicator-lab-brand__subtitle {
    color: var(--il-muted-ink);
    font-size: 0.6875rem;
    font-weight: 400;
    line-height: 1.25;
    white-space: normal;
}
</style>
"""


def install_app_shell() -> None:
    """Install the minimal shell rules Streamlit does not expose as settings."""
    st.html(APP_SHELL_STYLE)


def sidebar_brand() -> None:
    """Render the compact Indicator Lab identity used by the original sidebar."""
    st.html(
        """
        <div class="indicator-lab-brand" aria-label="Indicator Lab 指標量化研究工作台">
            <span class="indicator-lab-brand__mark" aria-hidden="true">IL</span>
            <span class="indicator-lab-brand__copy">
                <span class="indicator-lab-brand__title">Indicator Lab</span>
                <span class="indicator-lab-brand__subtitle">匯入策略、標記訊號、AI 改善、策略版本</span>
            </span>
        </div>
        """
    )


def page_header(title: str, intro: str) -> None:
    """Render a consistent page heading with native Streamlit components."""
    st.title(title)
    st.caption(intro)


def signal_chart(
    frame: pd.DataFrame,
    signals: pd.DataFrame,
    selected_id: int | None,
    timezone_name: str,
    window: int,
) -> go.Figure:
    if selected_id is not None and selected_id in set(signals["id"].astype(int)):
        selected = signals.loc[signals["id"].astype(int) == selected_id].iloc[0]
        center = locate_signal_index(frame, selected["timestamp"])
        view = frame.iloc[
            max(0, center - window) : min(len(frame), center + window + 1)
        ].copy()
    else:
        view = frame.tail(window * 2 + 1).copy()
    view["display_time"] = pd.to_datetime(
        view["timestamp"], utc=True
    ).dt.tz_convert(timezone_name)
    visible = signals[
        (signals["timestamp"] >= view["timestamp"].min())
        & (signals["timestamp"] <= view["timestamp"].max())
    ].copy()
    visible = visible.join(
        view.set_index("timestamp")[["high", "low"]], on="timestamp"
    )
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=view["display_time"],
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="K 線",
            increasing_line_color="#138A72",
            decreasing_line_color="#D24B39",
            increasing_fillcolor="#138A72",
            decreasing_fillcolor="#D24B39",
        )
    )
    definitions = (
        ("long", "triangle-up", "#138A72", "low", 0.997, "做多"),
        ("short", "triangle-down", "#D24B39", "high", 1.003, "做空"),
    )
    for direction, symbol, color, price_column, multiplier, label in definitions:
        part = visible[visible["direction"] == direction].copy()
        if part.empty:
            continue
        part["display_time"] = part["timestamp"].dt.tz_convert(timezone_name)
        marker_colors = [
            signal_marker_color(row.label, int(row.id), selected_id)
            for row in part.itertuples(index=False)
        ]
        fig.add_trace(
            go.Scatter(
                x=part["display_time"],
                y=part[price_column] * multiplier,
                mode="markers",
                name=label,
                marker={
                    "symbol": symbol,
                    "size": [
                        16 if selected_id == int(value) else 11
                        for value in part["id"]
                    ],
                    "color": marker_colors,
                    "line": {"width": 1, "color": "white"},
                },
                customdata=[
                    [int(row.id), row.direction, LABEL_ZH.get(row.label, "未標記")]
                    for row in part.itertuples(index=False)
                ],
                hovertemplate=(
                    f"{label}<br>%{{x}}<br>分類：%{{customdata[2]}}<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        height=610,
        margin={"l": 8, "r": 8, "t": 34, "b": 12},
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0},
        font={
            "family": "Inter, Noto Sans TC, sans-serif",
            "color": "#292426",
            "size": 12,
        },
        xaxis={"gridcolor": "#ECE8E9", "showspikes": True, "spikemode": "across"},
        yaxis={"gridcolor": "#ECE8E9", "side": "right", "fixedrange": False},
        selectdirection="h",
    )
    return fig


def selected_from_chart(event) -> int | None:
    try:
        points = event.selection.points
    except AttributeError:
        try:
            points = event.get("selection", {}).get("points", [])
        except Exception:
            return None
    if not points:
        return None
    custom = points[-1].get("customdata") if isinstance(points[-1], dict) else None
    return int(custom[0]) if custom else None
