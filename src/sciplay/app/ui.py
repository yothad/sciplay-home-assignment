"""Shared Streamlit helpers: data loading, sidebar filters, banner, tiles, legend."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from sciplay.config import get_settings
from sciplay.metrics import kpis as K
from sciplay.viz.formatting import LEGEND, STYLE, State, classify, fmt

PAGE_TITLE = "SciPlay player performance"


def sample_note(manifest: dict) -> str:
    """Describe the sample from the data itself (installs per month), never a typed-in number."""
    sizes = list(manifest.get("installs_per_month", {}).values())
    if not sizes:
        return "Sample data."
    per_month = f"exactly {sizes[0]}" if len(set(sizes)) == 1 else f"{min(sizes)}–{max(sizes)}"
    return (f"Sample data: {per_month} new players per install month. Totals are sample totals; "
            "compare rates and trends rather than absolute levels.")


@dataclass
class Prepared:
    player_day: pd.DataFrame
    daily: pd.DataFrame
    cohort_activity: pd.DataFrame
    cohort_revenue: pd.DataFrame
    manifest: dict
    processed_dir: Path


DEFAULT_SCORE_DATE = pd.Timestamp("2026-11-04")  # decision: last data day; every inference player has a day-3 forecast


@dataclass
class Filters:
    score_date: pd.Timestamp
    platforms: list[str]
    cohorts: list[str]
    payer_status: str
    countries: list[str]
    acquisition: list[str]

    @property
    def active(self) -> bool:
        return bool(self.platforms or self.cohorts or self.countries or self.acquisition
                    or self.payer_status != K.ALL)


@st.cache_data(show_spinner=False)
def _read(processed_dir: str, mtime: float) -> dict:
    d = Path(processed_dir)
    return {
        "player_day": pd.read_parquet(d / "player_day.parquet"),
        "daily": pd.read_parquet(d / "daily_metrics.parquet").set_index("DATE"),
        "cohort_activity": pd.read_parquet(d / "cohort_activity.parquet"),
        "cohort_revenue": pd.read_parquet(d / "cohort_revenue.parquet"),
        "manifest": json.loads((d / "manifest.json").read_text()),
    }


def load() -> Prepared:
    """Load prepared data, or stop the page with instructions if it has not been built."""
    d = get_settings().processed_dir
    manifest = d / "manifest.json"
    if not manifest.exists():
        st.error("Prepared data not found. Build it first:\n\n`uv run python -m sciplay.pipeline.prepare`")
        st.stop()
    data = _read(str(d), manifest.stat().st_mtime)
    return Prepared(processed_dir=d, **data)


def setup(title: str) -> Prepared:
    st.set_page_config(page_title=f"{title} · {PAGE_TITLE}", layout="wide")
    data = load()
    st.title(title)
    st.caption(f"{sample_note(data.manifest)}  Data through **{data.manifest['data_end']}** · built {data.manifest['built_at'][:16].replace('T', ' ')} UTC")
    return data


def sidebar(data: Prepared, with_filters: bool = True) -> Filters:
    pday = data.player_day
    first, last = pday["DATE"].min().date(), pday["DATE"].max().date()
    st.sidebar.header("Score date")
    default = min(max(DEFAULT_SCORE_DATE.date(), first), last)
    d = st.sidebar.date_input("As of the end of", value=st.session_state.get("score_date", default),
                              min_value=first, max_value=last, key="score_date")
    st.sidebar.caption(f"Default: {last:%d %b}, the last data day: every player installed up to 2 Nov has a day-3 LTV "
                       "forecast. 1–4 Nov hold the whole November cohort.")
    platforms, cohorts, payer, countries, acquisition = [], [], K.ALL, [], []
    if with_filters:
        st.sidebar.header("Filters")
        platforms = st.sidebar.multiselect("Platform", sorted(pday["MAIN_PLATFORM_ID"].dropna().unique()), key="f_platform")
        cohorts = st.sidebar.multiselect("Install month", sorted(pday["install_cohort"].unique()), key="f_cohort")
        countries = st.sidebar.multiselect("Country", sorted(pday["COUNTRY"].dropna().astype(str).unique()), key="f_country")
        acquisition = st.sidebar.multiselect("Acquisition type", sorted(pday["SOURCE_TYPE"].dropna().astype(str).unique()),
                                             key="f_acq")
        payer = st.sidebar.radio("Payer status", K.PAYER_STATUSES, key="f_payer", horizontal=True)
        st.sidebar.caption("Payer status, country and acquisition type are taken from each day's row.")
    with st.sidebar.expander("How values are shown"):
        legend()
    return Filters(pd.Timestamp(d), platforms, cohorts, payer, countries, acquisition)


def filtered_daily(data: Prepared, f: Filters) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filtered player-day rows (up to the score date) and their daily KPIs."""
    rows = K.filter_player_day(data.player_day, f.platforms, f.cohorts, f.payer_status, f.countries, f.acquisition)
    rows = rows[rows["DATE"] <= f.score_date]
    daily = K.daily_kpis(rows, start=data.player_day["DATE"].min(), end=f.score_date)
    return rows, daily


def tile(col, label: str, value, unit: str = "count", change: float | None = None, state: State | None = None,
         help: str | None = None) -> None:
    state = state or classify(value)
    delta = None if change is None or pd.isna(change) or state not in (State.VALUE, State.ZERO) else f"{change:+.0%}"
    col.metric(label, fmt(value, unit, state, short=True), delta=delta, help=help)


def legend() -> None:
    for state, sample, meaning in LEGEND:
        st.markdown(f'<span style="{STYLE[state]}">{sample}</span> · {meaning}', unsafe_allow_html=True)


def styled_table(df: pd.DataFrame, units: dict[str, str], not_yet: dict[str, pd.Series] | None = None,
                 not_applicable: dict[str, pd.Series] | None = None) -> str:
    """HTML table where each cell shows its value state (zero, missing, not yet, n/a)."""
    not_yet = not_yet or {}
    not_applicable = not_applicable or {}
    head = "".join(f"<th style='text-align:left;padding:4px 10px'>{c}</th>" for c in df.columns)
    body = []
    for i, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if c in units:
                st_ = classify(v, applicable=not bool(not_applicable.get(c, pd.Series(False, index=df.index)).get(i, False)),
                               available=not bool(not_yet.get(c, pd.Series(False, index=df.index)).get(i, False)))
                txt = f'<span style="{STYLE[st_]}">{fmt(v, units[c], st_)}</span>'
            else:
                txt = str(v)
            cells.append(f"<td style='padding:4px 10px;border-top:1px solid #E6E2EC'>{txt}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table style='border-collapse:collapse;font-size:14px'><tr>{head}</tr>{''.join(body)}</table>"
