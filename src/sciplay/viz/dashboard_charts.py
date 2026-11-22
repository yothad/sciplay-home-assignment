"""Charts for the dashboard and the HTML snapshot (Plotly, same style as the audit charts)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from sciplay.metrics.kpis import KPI_BY_KEY
from sciplay.viz.charts import GRID, SERIES, SURFACE, TEXT_SECONDARY, _layout

HOVER = {"count": "%{y:,.1f}", "money": "$%{y:,.2f}", "pct": "%{y:.1%}"}
TICK = {"count": ",.0f", "money": "$,.2f", "pct": ".0%"}


def kpi_trend(daily: pd.DataFrame, smooth: pd.DataFrame | None, key: str, title_suffix: str = "",
              score_date: pd.Timestamp | None = None, height: int = 300) -> go.Figure:
    """One KPI over time: faint daily line plus a bold smoothed line (7-day or weekly)."""
    k = KPI_BY_KEY[key]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily.index, y=daily[key], mode="lines", name="Daily",
                             line=dict(color=SERIES[0], width=1), opacity=0.35,
                             hovertemplate="%{x|%a %d %b}<br>" + HOVER[k.unit] + "<extra>Daily</extra>"))
    if smooth is not None:
        fig.add_trace(go.Scatter(x=smooth.index, y=smooth[key], mode="lines", name=title_suffix or "Smoothed",
                                 line=dict(color=SERIES[0], width=2.5),
                                 hovertemplate="%{x|%d %b}<br>" + HOVER[k.unit] + f"<extra>{title_suffix}</extra>"))
    if score_date is not None:
        fig.add_vline(x=pd.Timestamp(score_date), line=dict(color=TEXT_SECONDARY, width=1, dash="dot"))
    fig.update_yaxes(tickformat=TICK[k.unit], rangemode="tozero")
    return _layout(fig, k.label, height=height, subtitle=k.meaning)


def weekly_bars(weekly: pd.DataFrame, key: str, height: int = 300) -> go.Figure:
    """Weekly values as bars; a partial week is shown lighter and labelled."""
    k = KPI_BY_KEY[key]
    full = weekly["days_in_week"] == 7
    colors = [SERIES[0] if f else "#B9A6D6" for f in full]
    text = ["" if f else f"{int(d)} days" for f, d in zip(full, weekly["days_in_week"])]
    fig = go.Figure(go.Bar(x=weekly.index, y=weekly[key], marker_color=colors, text=text, textposition="outside",
                           marker_line=dict(color=SURFACE, width=2),
                           hovertemplate="Week of %{x|%d %b}<br>" + HOVER[k.unit] + "<extra></extra>"))
    fig.update_yaxes(tickformat=TICK[k.unit], rangemode="tozero")
    return _layout(fig, f"{k.label}, weekly", height=height,
                   subtitle="Counts and revenue are per-day averages; lighter bar = partial week")


def cumulative_revenue(curves: pd.DataFrame, height: int = 420) -> go.Figure:
    """Cumulative revenue per install by age: one line per install month, pooled line bold."""
    fig = go.Figure()
    cohorts = [c for c in curves["install_cohort"].unique() if c != "All cohorts"]
    for i, c in enumerate(cohorts):
        sub = curves[curves["install_cohort"] == c]
        fig.add_trace(go.Scatter(x=sub["age_days"], y=sub["revenue_per_install"], mode="lines", name=c,
                                 line=dict(color=SERIES[i % len(SERIES)], width=1.5), opacity=0.8,
                                 customdata=sub["players"],
                                 hovertemplate=f"{c}, day %{{x}}<br>$%{{y:.2f}} per install<br>%{{customdata}} players<extra></extra>"))
    pooled = curves[curves["install_cohort"] == "All cohorts"]
    fig.add_trace(go.Scatter(x=pooled["age_days"], y=pooled["revenue_per_install"], mode="lines", name="All cohorts",
                             line=dict(color="#1A1423", width=3), customdata=pooled["players"],
                             hovertemplate="All cohorts, day %{x}<br>$%{y:.2f} per install<br>%{customdata} players<extra></extra>"))
    fig.update_xaxes(title="Days since install")
    fig.update_yaxes(title="Cumulative revenue per install", tickformat="$,.0f", rangemode="tozero")
    return _layout(fig, "Cumulative revenue per install, by age", height=height,
                   subtitle="Only players who have reached each age are counted; a cohort line stops below 20 players, the pooled line below 50")


def player_timeline(rows: pd.DataFrame, score_date: pd.Timestamp | None = None, height: int = 380) -> go.Figure:
    """A player's sessions and revenue per day played (two panels, one axis each)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=["Sessions", "Revenue (USD)"])
    fig.add_trace(go.Bar(x=rows["DATE"], y=rows["SESSIONS"], marker_color=SERIES[0], showlegend=False,
                         hovertemplate="%{x|%d %b}: %{y} sessions<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Bar(x=rows["DATE"], y=rows["revenue"], marker_color=SERIES[1], showlegend=False,
                         hovertemplate="%{x|%d %b}: $%{y:.2f}<extra></extra>"), row=2, col=1)
    if score_date is not None:
        for r in (1, 2):
            fig.add_vline(x=pd.Timestamp(score_date), line=dict(color=TEXT_SECONDARY, width=1, dash="dot"), row=r, col=1)
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", font=dict(size=12, color=TEXT_SECONDARY))
    fig.update_yaxes(gridcolor=GRID)
    return _layout(fig, "Days played", height=height, subtitle="Bars only on days with a row; gaps are days not played")


def health_band(band: pd.DataFrame, score_date: pd.Timestamp, height: int = 320) -> go.Figure:
    """Player-days per day with the trailing mean ± 3 standard deviations; the checked date marked."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=band.index, y=band["high"], mode="lines", line=dict(width=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=band.index, y=band["low"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(107,63,160,0.12)", name="Normal range (28-day mean ± 3 sd)",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=band.index, y=band["rows"], mode="lines", name="Player-days",
                             line=dict(color=SERIES[0], width=2),
                             hovertemplate="%{x|%d %b}: %{y} player-days<extra></extra>"))
    d = pd.Timestamp(score_date)
    if d in band.index:
        fig.add_trace(go.Scatter(x=[d], y=[band.loc[d, "rows"]], mode="markers", name="Checked date",
                                 marker=dict(size=11, color=SERIES[1], line=dict(color=SURFACE, width=2)),
                                 hovertemplate="%{x|%d %b}: %{y}<extra>Checked date</extra>"))
    fig.update_yaxes(rangemode="tozero")
    return _layout(fig, "Player-days per day against their normal range", height=height,
                   subtitle="One player-day = one player who played that day, whatever the number of platforms")


def payer_curve(curve: pd.DataFrame, height: int = 380) -> go.Figure:
    fig = go.Figure(go.Scatter(x=curve["days_since_first_purchase"], y=curve["revenue_per_payer"], mode="lines",
                               line=dict(color=SERIES[1], width=3), customdata=curve["payers"],
                               hovertemplate="Day %{x} after first purchase<br>$%{y:.2f} per payer<br>%{customdata} payers<extra></extra>"))
    fig.update_xaxes(title="Days since first purchase")
    fig.update_yaxes(title="Cumulative revenue per payer", tickformat="$,.0f", rangemode="tozero")
    return _layout(fig, "Cumulative revenue per payer, from first purchase", height=height,
                   subtitle="All payers pooled (too few for one line per month); stops where fewer than 5 payers are that far in")


def active_by_install_month(rows: pd.DataFrame, score_date: pd.Timestamp | None = None, height: int = 380) -> go.Figure:
    """Average daily active players per week, stacked by install month."""
    daily = rows.groupby(["DATE", "install_cohort"])["PLAYER_ID"].nunique().unstack(fill_value=0)
    daily = daily.reindex(pd.date_range(rows["DATE"].min(), rows["DATE"].max(), freq="D"), fill_value=0)
    weekly = daily.resample("W-MON", label="left", closed="left").mean()
    fig = go.Figure()
    for i, cohort in enumerate(weekly.columns):
        fig.add_trace(go.Scatter(x=weekly.index, y=weekly[cohort], name=cohort, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i % len(SERIES)],
                                 hovertemplate="Week of %{x|%d %b}<br>" + cohort + ": %{y:.1f} players a day<extra></extra>"))
    if score_date is not None:
        fig.add_vline(x=pd.Timestamp(score_date), line=dict(color=TEXT_SECONDARY, width=1, dash="dot"))
    fig.update_yaxes(title="Active players per day (weekly average)", rangemode="tozero")
    return _layout(fig, "Active players by install month", height=height,
                   subtitle="Daily actives grow because a new 100-player cohort joins every month, not because the game grows")


def engagement_trend(eng: pd.DataFrame, score_date: pd.Timestamp | None = None, height: int = 300) -> go.Figure:
    """Sessions per active player: faint daily line plus a 7-day average (sums over the window, not mean of ratios)."""
    roll = eng[["sessions", "active"]].rolling(7, min_periods=1).sum()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eng.index, y=eng["sessions_per_active"], mode="lines", name="Daily",
                             line=dict(color=SERIES[0], width=1), opacity=0.35,
                             hovertemplate="%{x|%a %d %b}<br>%{y:.2f}<extra>Daily</extra>"))
    fig.add_trace(go.Scatter(x=roll.index, y=roll["sessions"] / roll["active"], mode="lines", name="7-day average",
                             line=dict(color=SERIES[0], width=2.5),
                             hovertemplate="%{x|%d %b}<br>%{y:.2f}<extra>7-day average</extra>"))
    if score_date is not None:
        fig.add_vline(x=pd.Timestamp(score_date), line=dict(color=TEXT_SECONDARY, width=1, dash="dot"))
    fig.update_yaxes(rangemode="tozero")
    return _layout(fig, "Sessions per active player", height=height, subtitle="Engagement: sessions / active players")


def list_volume(hist: pd.DataFrame, score_date: pd.Timestamp | None = None, height: int = 320) -> go.Figure:
    """Players on each daily list over time."""
    from sciplay.lists import config as L
    sizes = (hist.groupby(["score_date", "list_type"]).size().unstack(fill_value=0)
             .reindex(columns=L.PRECEDENCE, fill_value=0))
    sizes.index = pd.to_datetime(sizes.index)
    fig = go.Figure()
    for i, name in enumerate(L.PRECEDENCE):
        fig.add_trace(go.Scatter(x=sizes.index, y=sizes[name], mode="lines", name=name,
                                 line=dict(color=SERIES[i], width=2.5),
                                 hovertemplate="%{x|%a %d %b}<br>%{y} players<extra>" + name + "</extra>"))
    if score_date is not None:
        fig.add_vline(x=pd.Timestamp(score_date), line=dict(color=TEXT_SECONDARY, width=1, dash="dot"))
    fig.update_yaxes(rangemode="tozero")
    fig = _layout(fig, "List volume", height=height, subtitle="Players on each daily list (latest rules version)")
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.32, x=0, xanchor="left"), margin=dict(b=90))
    return fig
