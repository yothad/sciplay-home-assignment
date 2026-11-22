"""LTV pieces for the dashboard (Part 3): scores for a date, player panel, model check."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from sciplay.config import REPO_ROOT, get_settings
from sciplay.ltv import config as C
from sciplay.ltv import score as S

MODEL_ROOT = REPO_ROOT / "models" / "ltv"
SOURCE_LABEL = {"model_d3": "Day-3 LTV model", "update_rule": "Update rule: not from the LTV model",
                "cold_start": "Too new to forecast"}


@st.cache_data(show_spinner=False)
def _scores(db: str, mtime: float, score_date: str) -> pd.DataFrame:
    return S.read(score_date, Path(db))


def scores(score_date) -> pd.DataFrame:
    """Stored LTV scores for the date (empty if none were written for it)."""
    db = get_settings().store_db_path
    if not db.exists():
        return pd.DataFrame(columns=S.COLUMNS)
    return _scores(str(db), db.stat().st_mtime, pd.Timestamp(score_date).date().isoformat())


def active_dir() -> Path | None:
    f = MODEL_ROOT / "active.json"
    if not f.exists():
        return None
    return MODEL_ROOT / json.loads(f.read_text())["version"]


def not_scored_note(score_date) -> str:
    return (f"No LTV scores stored for {pd.Timestamp(score_date):%d %b}. Day-3 forecasts exist from 9 Oct "
            "(the first inference install reaching day 3). Run `python -m sciplay.ltv.score --date YYYY-MM-DD`.")


def money(v) -> str:
    return "n/a" if v is None or pd.isna(v) else f"${v:,.2f}"


def player_panel(row: pd.Series) -> None:
    """Value, source, calculation and reasons for one player."""
    src = row["source"]
    st.markdown(f"#### Lifetime value · {SOURCE_LABEL.get(src, src)}")
    if src == "cold_start":
        st.info(f"Too new to forecast: fewer than {C.K} days of data. First forecast on day {C.K}.")
        return
    c = st.columns(4)
    if src == "model_d3":
        c[0].metric("Predicted LTV365", money(row["predicted_ltv_365"]),
                    help="30-day forecast × 2.49 (assumed fade after day 30, not validated)")
        c[1].metric("Range", f"{money(row['ltv_365_low'])} – {money(row['ltv_365_high'])}",
                    help="Bootstrap: 50 refits on resampled training players; forecast × (25th or 75th percentile ÷ median)")
        c[2].metric("Confidence", row["confidence"],
                    help="High = paid in the first 3 days (the forecast rests on real spending); Medium = active non-payer")
        if row["age_days"] < C.HORIZON:
            gap = row["gap_to_forecast"]
            c[3].metric("Ahead of forecast" if gap >= 0 else "Behind forecast", money(abs(gap)),
                        help=f"Revenue to date vs revenue expected by day {int(row['age_days'])} "
                             f"({money(row['expected_by_today'])}), from the typical timing of first-month spending")
        else:
            c[3].metric("30-day result", f"{money(row['ltv_to_date'])} vs {money(row['predicted_ltv_30'])}",
                        help="The 30-day window is complete")
        st.markdown(f"**Calculation:** 30-day forecast **{money(row['predicted_ltv_30'])}** "
                    f"(spent in days 0–2 + model forecast for days 3–29) × **{row['multiplier']:.2f}** = "
                    f"**{money(row['predicted_ltv_365'])}** LTV365. *The × {row['multiplier']:.2f} assumes each later "
                    f"30-day block is worth {C.R} × the one before; r = 0.5–0.7 gives × 2.00–3.29. Not validated.*")
        st.caption(f"Forecast made on {row['feature_date']} (day 3) from the first 3 days only; carried forward.")
    else:
        c[0].metric("Estimated LTV365", money(row["predicted_ltv_365"]), help="Update rule, not the LTV model")
        c[1].metric("Revenue to date", money(row["ltv_to_date"]))
        c[2].metric("Still to come", money(row["predicted_ltv_365"] - row["ltv_to_date"]))
        c[3].metric("Confidence", row["confidence"], help="High = at least 80% of the value already spent")
        st.warning("**Not from the LTV model.** This player installed before 7 Oct, so is older than the model's "
                   "3-day window. **LTV365 = revenue to date + last 30 days' revenue × (0.6 + 0.6² + …) over the "
                   "30-day blocks left until day 365**; nothing is added if the player has not been seen for 30+ days "
                   "or spent nothing in the last 30 days.")
    reasons = [r for r in [row.get("reason_1"), row.get("reason_2"), row.get("reason_3")] if isinstance(r, str) and r]
    if reasons:
        st.markdown("**Why**" + (" (strongest signals; +$ = how much lower the forecast would be without that "
                                 "signal; signals overlap)" if src == "model_d3" else ""))
        for r in reasons:
            st.markdown(f"- {r}")


def model_check() -> None:
    """Test-set results of the shipped LTV model (graded once), selection summary and monitoring plan."""
    d = active_dir()
    st.markdown("#### LTV model check")
    if d is None or not (d / "meta.json").exists():
        st.info("No trained LTV model yet: run `python -m sciplay.ltv.train select` then `finalize`.")
        return
    meta = json.loads((d / "meta.json").read_text())
    st.caption(f"Model in use: **{meta['model']}** · version `{meta['version']}` · {len(meta['features'])} features from the "
               f"first {meta['k']} days · trained on {meta['train_players']} players installed 9 May – 31 Jul · "
               f"chosen by the rule set in advance (lowest deviance on training folds) · data through {meta['data_end']}")
    res = pd.read_csv(d / "test_results.csv")
    tbl = pd.DataFrame({
        "approach": res["approach"],
        "error per player": res.apply(lambda r: f"${r.MAE:.2f} (${r.MAE_low:.2f}–{r.MAE_high:.2f})", axis=1),
        "error, payers only": res["MAE_payers"].map(lambda v: f"${v:.1f}"),
        "predicted ÷ actual": res.apply(lambda r: f"{r.pred_over_actual:.2f} ({r.ratio_low:.2f}–{r.ratio_high:.2f})", axis=1),
        "dollar recall": res["dollar_recall"].map("{:.0%}".format),
        "payers found": res.apply(lambda r: f"{round(r.payer_recall * 6)} of 6", axis=1),
    })
    st.markdown("**Test set** (218 players installed 1 Aug – 6 Oct, 6 payers; 30-day revenue; graded once)")
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.caption("Ranges: test players redrawn 1,000 times (model fixed), 5th–95th percentile. Dollar recall = share of "
               "actual revenue from players predicted at $1 or more. With 6 payers, results are directional: all error "
               "ranges overlap.")
    c = st.columns(2)
    with c[0]:
        st.markdown("**Value bands** (predicted 30-day revenue)")
        st.dataframe(pd.read_csv(d / "value_bands.csv"), hide_index=True, width="stretch")
    with c[1]:
        st.markdown("**By install month**")
        st.dataframe(pd.read_csv(d / "test_by_month.csv").round(2), hide_index=True, width="stretch")
        st.markdown("**By confidence**")
        st.dataframe(pd.read_csv(d / "confidence_check.csv").round(2), hide_index=True, width="stretch")
    sel = MODEL_ROOT / "selection" / "best_rounds.json"
    if sel.exists():
        best = pd.read_json(sel)
        best = best[best["picked"]][["model", "n_features", "deviance", "MAE_30d", "pred_over_actual_30d"]]
        st.markdown("**Model selection on training folds** (May → June, May–June → July; test set not used)")
        st.dataframe(best.rename(columns={"n_features": "features", "deviance": "fold deviance",
                                          "MAE_30d": "fold error", "pred_over_actual_30d": "predicted ÷ actual"}).round(3),
                     hide_index=True, width="stretch")
    st.markdown("**Monitoring after deployment** (thresholds are proposals)")
    st.dataframe(pd.DataFrame([
        ("Calibration", "Matured 30-day actual ÷ forecast by cohort, source, confidence; weekly", "outside 0.8–1.25 two weeks running"),
        ("Drift", "Top features (PSI), share paying by day 3, source mix, average forecast", "PSI > 0.2"),
        ("Coverage", "Share of eligible players scored; share too new", "< 99% scored"),
        ("Freshness", "Latest data date; model age", "health gate; model older than ~2 months"),
    ], columns=["watch", "how", "alert"]), hide_index=True, width="stretch")
