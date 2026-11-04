"""Plotly figure builders (presentation only; data comes from analytics_service)."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from cyberlead360.ui.theme import BLUE, CHART_SEQUENCE, CYAN, NAVY

_LAYOUT = dict(
    margin=dict(l=10, r=10, t=40, b=10),
    font=dict(family="Inter, Segoe UI, sans-serif", size=13, color=NAVY),
    plot_bgcolor="white",
    paper_bgcolor="white",
    colorway=CHART_SEQUENCE,
    height=340,
)


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=15)), **_LAYOUT)
    fig.update_xaxes(gridcolor="#EEF2F7")
    fig.update_yaxes(gridcolor="#EEF2F7")
    return fig


def funnel_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Funnel(
            y=df["step"],
            x=df["companies"],
            textinfo="value+percent initial",
            marker=dict(
                color=[BLUE, "#3B82F6", CYAN, "#22D3EE", "#0EA5E9", "#7C3AED", "#16A34A"][: len(df)]
            ),
        )
    )
    return _style(fig, "Prospect funnel (distinct companies)")


def bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    horizontal: bool = False,
    color: str | None = None,
    text_auto: bool | str = True,
) -> go.Figure:
    if horizontal:
        fig = px.bar(df, x=y, y=x, orientation="h", color=color, text_auto=text_auto)
        fig.update_yaxes(categoryorder="total ascending")
    else:
        fig = px.bar(df, x=x, y=y, color=color, text_auto=text_auto)
    if color is None:
        fig.update_traces(marker_color=BLUE)
    return _style(fig, title)


def histogram(df: pd.DataFrame, column: str, title: str) -> go.Figure:
    fig = px.histogram(df, x=column, nbins=10, range_x=[0, 100])
    fig.update_traces(marker_color=CYAN, marker_line_color="white", marker_line_width=1)
    fig.update_layout(bargap=0.05)
    fig.update_xaxes(title="Lead score (0–100)")
    fig.update_yaxes(title="Companies")
    return _style(fig, title)


def stacked_time(df: pd.DataFrame, x: str, y: str, color: str, title: str) -> go.Figure:
    fig = px.bar(df, x=x, y=y, color=color)
    fig.update_xaxes(dtick="M1", tickformat="%b %Y")
    return _style(fig, title)
