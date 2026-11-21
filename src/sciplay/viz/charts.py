"""Interactive Plotly charts for the audit (and, later, the dashboard).

Each function takes tables produced by `sciplay.audit.checks` and returns a Figure.
Style: fixed categorical order, thin marks, recessive grid, hover on every mark,
one y-axis per panel (no dual axes).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
NA_COLOR = "#f0efec"

FONT = dict(family="Inter, Segoe UI, Helvetica, Arial, sans-serif", size=12, color=TEXT_SECONDARY)


def _layout(fig: go.Figure, title: str, height: int = 420, subtitle: str | None = None) -> go.Figure:
    text = f"<b>{title}</b>" + (f"<br><span style='font-size:12px;color:{TEXT_SECONDARY}'>{subtitle}</span>" if subtitle else "")
    fig.update_layout(
        title=dict(text=text, x=0, xanchor="left", font=dict(size=15, color=TEXT_PRIMARY)),
        height=height,
        font=FONT,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin=dict(l=60, r=20, t=115 if subtitle else 70, b=50),
        hoverlabel=dict(bgcolor="white", font_size=12, font_color=TEXT_PRIMARY),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, traceorder="normal"),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #


def daily_coverage(daily: pd.DataFrame) -> go.Figure:
    """Small multiples sharing the date axis: active players, installs, payers, revenue."""
    panels = [
        ("players", "Active players", "{:,.0f}"),
        ("installs", "Installs (day-0 rows)", "{:,.0f}"),
        ("payers", "Paying players", "{:,.0f}"),
        ("revenue", "Revenue (sum of REVENUE, gross)", "${:,.0f}"),
    ]
    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=[p[1] for p in panels])
    for i, (col, label, _) in enumerate(panels, start=1):
        hover = "%{x|%a %d %b %Y}<br>" + label + ": " + ("$%{y:,.0f}" if col == "revenue" else "%{y:,.0f}") + "<extra></extra>"
        fig.add_trace(
            go.Scatter(x=daily.index, y=daily[col], mode="lines", line=dict(color=SERIES[0], width=2),
                       name=label, hovertemplate=hover, showlegend=False),
            row=i, col=1,
        )
        fig.update_yaxes(rangemode="tozero", row=i, col=1)
    fig.update_xaxes(showspikes=True, spikemode="across", spikecolor=GRID, spikethickness=1)
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", font=dict(size=12, color=TEXT_SECONDARY))
    return _layout(fig, "Daily coverage of the sample", height=720,
                   subtitle="Hover for exact values. The Nov 1–4 install spike is a full 100-player cohort packed into 4 days.")


def active_by_cohort(active: pd.DataFrame) -> go.Figure:
    """Stacked area of daily active players by install month."""
    pivot = active.pivot(index="DATE", columns="install_cohort", values="players").fillna(0)
    fig = go.Figure()
    for i, cohort in enumerate(pivot.columns):
        fig.add_trace(go.Scatter(
            x=pivot.index, y=pivot[cohort], name=cohort, stackgroup="one", mode="lines",
            line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i % len(SERIES)],
            hovertemplate="%{x|%d %b %Y}<br>Cohort " + cohort + ": %{y:,.0f} players<extra></extra>",
        ))
    fig.update_yaxes(title="Active players")
    return _layout(fig, "Who is active each day, by install month",
                   subtitle="Daily actives grow because a new 100-install cohort joins every month, not because the game grows.")


def cohort_activity_heatmap(matrix: pd.DataFrame, age_labels: list[str]) -> go.Figure:
    """Share of each install cohort active per age bucket; unobserved cells shown as n/a."""
    z = matrix.pivot(index="install_cohort", columns="age_bucket", values="active_share")[age_labels]
    n = matrix.pivot(index="install_cohort", columns="age_bucket", values="eligible_players")[age_labels]
    text = np.where(z.isna(), "n/a", (z * 100).round(0).astype("Int64").astype(str) + "%")
    custom = np.dstack([n.values, text])
    fig = go.Figure(go.Heatmap(
        z=z.values, x=age_labels, y=z.index, colorscale=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)],
        zmin=0, zmax=0.5, text=text, texttemplate="%{text}", textfont=dict(size=11),
        customdata=custom, xgap=2, ygap=2, hoverongaps=False,
        colorbar=dict(title="Active", tickformat=".0%", thickness=12),
        hovertemplate="Cohort %{y}, %{x}<br>Active: %{customdata[1]}<br>Players who lived through this age: %{customdata[0]}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", title="Install month", showgrid=False)
    fig.update_xaxes(side="top")
    fig.update_layout(plot_bgcolor=NA_COLOR)
    return _layout(fig, "Share of each install cohort active, by age",
                   subtitle="Columns = days since install. Only players who lived through the whole bucket count; n/a = not yet observable. Colour capped at 50%.",
                   height=460)


def rows_per_player(dist: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=dist["rows_per_player"].astype(str), y=dist["players"], marker_color=SERIES[0],
        customdata=dist["share"], text=[f"{v:,}" for v in dist["players"]], textposition="outside",
        hovertemplate="%{x} rows: %{y:,} players (%{customdata:.0%})<extra></extra>",
    ))
    fig.update_xaxes(title="Rows (active days) per player")
    fig.update_yaxes(title="Players")
    return _layout(fig, "Players by number of active days observed",
                   subtitle="Almost half the players were seen on a single day.", height=380)


# --------------------------------------------------------------------------- #
# Field groups and missingness
# --------------------------------------------------------------------------- #


def field_groups_bar(profile: pd.DataFrame) -> go.Figure:
    """Stacked bars per field group; hover lists the column names in each segment."""
    def status(r):
        if r.is_all_null:
            return "All null"
        if r.is_constant:
            return "Constant"
        return "Has variation"

    p = profile.assign(status=profile.apply(status, axis=1))
    order = p["field_group"].value_counts().index.tolist()[::-1]
    fig = go.Figure()
    for i, st in enumerate(["Has variation", "Constant", "All null"]):
        sub = p[p["status"] == st]
        counts = sub.groupby("field_group").size().reindex(order, fill_value=0)
        names = sub.groupby("field_group")["column"].apply(
            lambda s: "<br>".join(", ".join(s.iloc[j:j + 4]) for j in range(0, len(s), 4))
        ).reindex(order, fill_value="")
        fig.add_trace(go.Bar(
            y=order, x=counts.values, orientation="h", name=st, marker_color=SERIES[i],
            marker_line=dict(color=SURFACE, width=2), customdata=names.values,
            hovertemplate="<b>%{y}</b> · " + st + ": %{x}<br>%{customdata}<extra></extra>",
        ))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title="Columns", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False)
    return _layout(fig, "Columns per field group",
                   subtitle="Hover a segment to see its columns. 85 of 409 columns carry no information.",
                   height=560)


def missingness_strip(profile: pd.DataFrame) -> go.Figure:
    """Every column as a dot: null share by field group, hover for the name."""
    order = profile.groupby("field_group")["null_share"].median().sort_values().index.tolist()
    rng = np.random.default_rng(0)
    p = profile.assign(y=profile["field_group"].map({g: i for i, g in enumerate(order)}))
    p["y_jit"] = p["y"] + rng.uniform(-0.25, 0.25, len(p))
    fig = go.Figure(go.Scatter(
        x=p["null_share"], y=p["y_jit"], mode="markers",
        marker=dict(size=8, color=SERIES[0], opacity=0.7, line=dict(color=SURFACE, width=1)),
        customdata=np.stack([p["column"], p["field_group"], p["n_unique"]], axis=1),
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Null: %{x:.1%}<br>Distinct values: %{customdata[2]}<extra></extra>",
    ))
    fig.update_yaxes(tickvals=list(range(len(order))), ticktext=order, showgrid=False)
    fig.update_xaxes(title="Share of rows null", tickformat=".0%", showgrid=True, gridcolor=GRID, range=[-0.03, 1.03])
    return _layout(fig, "Null share of every column, by field group",
                   subtitle="Each dot is a column. Most high-null columns are structural (no purchase that day, never paid, not applicable).",
                   height=560)


# --------------------------------------------------------------------------- #
# Quality evidence
# --------------------------------------------------------------------------- #


def d365_vs_lifetime(df: pd.DataFrame) -> go.Figure:
    """Q1: D365_SPEND against LIFETIME_REVENUE, coloured by age. Points on y = x mean identical."""
    x = df[df["D365_SPEND"].notna()]
    fig = go.Figure()
    top = float(max(x["LIFETIME_REVENUE"].max(), x["D365_SPEND"].max())) * 1.05
    fig.add_trace(go.Scatter(x=[0, top], y=[0, top], mode="lines", name="y = x",
                             line=dict(color=TEXT_SECONDARY, width=1, dash="dot"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x["LIFETIME_REVENUE"], y=x["D365_SPEND"], mode="markers", name="Player snapshot",
        marker=dict(size=8, color=x["DAYS_SINCE_INSTALL"], colorscale=[[i / 6, c] for i, c in enumerate(SEQUENTIAL)],
                    colorbar=dict(title="Days since<br>install", thickness=12), line=dict(color=SURFACE, width=1)),
        customdata=np.stack([x["PLAYER_ID"], x["DATE"].dt.strftime("%Y-%m-%d"), x["DAYS_SINCE_INSTALL"]], axis=1),
        hovertemplate="Player %{customdata[0]} on %{customdata[1]} (day %{customdata[2]})<br>LIFETIME_REVENUE $%{x:,.2f}<br>D365_SPEND $%{y:,.2f}<extra></extra>",
    ))
    fig.update_xaxes(title="LIFETIME_REVENUE ($)", type="log")
    fig.update_yaxes(title="D365_SPEND ($)", type="log")
    return _layout(fig, "Q1 · D365_SPEND is just lifetime revenue so far",
                   subtitle="Every snapshot sits on y = x, including players only days old. Log scales.", height=480)


def update_lag(lag_rows: pd.DataFrame) -> go.Figure:
    """Q3: data date vs last update date for every row."""
    counts = lag_rows.groupby(["DATE", "last_update"]).size().rename("rows").reset_index()
    counts["lag"] = (counts["last_update"] - counts["DATE"]).dt.days
    fig = go.Figure()
    lo, hi = lag_rows["DATE"].min(), lag_rows["DATE"].max()
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="Updated same day",
                             line=dict(color=TEXT_SECONDARY, width=1, dash="dot"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=counts["DATE"], y=counts["last_update"], mode="markers", name="Rows",
        marker=dict(size=np.clip(np.sqrt(counts["rows"]) * 3, 5, 18), color=SERIES[0], opacity=0.75,
                    line=dict(color=SURFACE, width=1)),
        customdata=np.stack([counts["rows"], counts["lag"]], axis=1),
        hovertemplate="Data date %{x|%d %b %Y}<br>Last updated %{y|%d %b %Y}<br>%{customdata[0]} rows, lag %{customdata[1]} days<extra></extra>",
    ))
    fig.update_xaxes(title="Data date (DATE)")
    fig.update_yaxes(title="LAST_UPDATE_DATETIME")
    return _layout(fig, "Q3 · Rows keep being rewritten for 91 days after their date",
                   subtitle="Each row is updated until 91 days after its date, then freezes (May rows froze at the first batch, 3 Sep). Recent rows are still open.",
                   height=460)


def revenue_offset(df: pd.DataFrame) -> go.Figure:
    """Q2: daily REVENUE vs change in LIFETIME_REVENUE into the same row and into the next row."""
    s = df.sort_values(["PLAYER_ID", "DATE"]).copy()
    s["same"] = s.groupby("PLAYER_ID")["LIFETIME_REVENUE"].diff()
    s["next"] = s.groupby("PLAYER_ID")["same"].shift(-1)
    paid = s[s["REVENUE"].fillna(0) > 0]
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.06,
                        subplot_titles=["Change into the same row", "Change into the next row"])
    top = float(paid["REVENUE"].max()) * 1.05
    for i, col in enumerate(["same", "next"], start=1):
        sub = paid.dropna(subset=[col])
        match = (sub["REVENUE"] - sub[col]).abs() < 0.01
        fig.add_trace(go.Scatter(x=[0, top], y=[0, top], mode="lines", line=dict(color=TEXT_SECONDARY, width=1, dash="dot"),
                                 hoverinfo="skip", showlegend=False), row=1, col=i)
        fig.add_trace(go.Scatter(
            x=sub["REVENUE"], y=sub[col], mode="markers", showlegend=False,
            marker=dict(size=8, color=np.where(match, SERIES[0], SERIES[1]), line=dict(color=SURFACE, width=1)),
            hovertemplate="REVENUE $%{x:,.2f}<br>Lifetime change $%{y:,.2f}<extra></extra>",
        ), row=1, col=i)
        fig.layout.annotations[i - 1].update(text=f"{fig.layout.annotations[i - 1].text}: {match.mean():.0%} match")
        fig.update_xaxes(title="REVENUE that day ($)", row=1, col=i)
    fig.update_yaxes(title="Change in LIFETIME_REVENUE ($)", row=1, col=1)
    for ann in fig.layout.annotations:
        ann.update(font=dict(size=12, color=TEXT_SECONDARY))
    return _layout(fig, "Q2 · Today's revenue shows up in tomorrow's lifetime total",
                   subtitle="Blue = exact match, orange = mismatch. LIFETIME_REVENUE is a start-of-day value.", height=440)
