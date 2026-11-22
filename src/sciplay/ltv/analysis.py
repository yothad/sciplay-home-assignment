"""Analyses behind the Part 3 decisions (used by notebooks/02_ltv.ipynb and the deck)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sciplay.ltv import config as C
from sciplay.ltv.labels import day_index


def target_validation(raw: pd.DataFrame, installs: pd.Series, pday: pd.DataFrame) -> pd.DataFrame:
    """The brief's five tests of D365_SPEND as a label."""
    filled = raw["D365_SPEND"].notna()
    life = raw["LIFETIME_REVENUE"].fillna(0)
    payers = raw.loc[filled, "PLAYER_ID"].nunique()
    changing = int((raw[filled].groupby("PLAYER_ID")["D365_SPEND"].nunique() > 1).sum())
    days_of_data = int(day_index(pday, installs).max())
    end = pd.to_datetime(pday["DATE"]).max()
    mature = int(((end - installs).dt.days >= 365).sum())
    rows = [
        ("Availability", f"Filled on {filled.sum():,} of {len(raw):,} rows, only on rows of players who have paid "
                         f"({payers} players); never filled for a non-payer: {int(((life == 0) & filled).sum())} rows",
         "Payers only"),
        ("Population", f"{mature} of {installs.size} players reach day 365; the oldest has {days_of_data} days of data",
         "No mature outcome"),
        ("Stability", f"Changes between snapshots for {changing} of {payers} payers", "Not fixed"),
        ("Relationship to revenue", f"Equals LIFETIME_REVENUE on {np.isclose(raw.loc[filled, 'D365_SPEND'], life[filled]).mean():.0%}"
                                    " of filled rows", "Duplicate column"),
        ("Censoring", f"Every player is censored, at 0–{days_of_data} days of data", "Fully censored"),
    ]
    return pd.DataFrame(rows, columns=["test", "what we found", "verdict"])


def _revenue_by_day(pday, installs):
    d = day_index(pday, installs)
    return pd.DataFrame({"PLAYER_ID": pday["PLAYER_ID"], "day": d, "rev": pday["REVENUE"].fillna(0.0)})


def label_horizons(pday, installs, data_end, horizons=(30, 90, 365)) -> pd.DataFrame:
    """How many players have a complete label at each horizon, and how many of them paid."""
    r = _revenue_by_day(pday, installs)
    out = []
    for h in horizons:
        ok = installs[installs + pd.Timedelta(days=h - 1) <= pd.Timestamp(data_end)].index
        y = r[(r.day < h) & r.PLAYER_ID.isin(ok)].groupby("PLAYER_ID").rev.sum().reindex(ok).fillna(0)
        out.append({"horizon_days": h, "players_with_complete_label": len(ok), "payers": int((y > 0).sum()),
                    "last_install_with_label": installs[ok].max().date() if len(ok) else None})
    return pd.DataFrame(out)


def revenue_curve(pday, installs, ids, horizon: int = C.HORIZON) -> pd.Series:
    """Share of first-30-day revenue earned by the end of each day (pooled over `ids`)."""
    r = _revenue_by_day(pday, installs)
    r = r[r.PLAYER_ID.isin(ids) & (r.day >= 0) & (r.day < horizon)]
    by_day = r.groupby("day").rev.sum().reindex(range(horizon), fill_value=0.0)
    return (by_day.cumsum() / by_day.sum()).rename("share_of_30d_revenue")


def early_signal(pday, installs, ids, ks=(3, 7), horizon: int = C.HORIZON) -> pd.DataFrame:
    """What the first k days reveal about 30-day revenue."""
    r = _revenue_by_day(pday, installs)
    r = r[r.PLAYER_ID.isin(ids)]
    y = r[r.day < horizon].groupby("PLAYER_ID").rev.sum().reindex(ids).fillna(0)
    out = []
    for k in ks:
        e = r[r.day < k].groupby("PLAYER_ID").rev.sum().reindex(ids).fillna(0)
        out.append({"first_k_days": k, "players": len(ids), "paid_by_day_k": int((e > 0).sum()),
                    "paid_by_day_30": int((y > 0).sum()),
                    "day30_payers_already_paid": f"{int(((e > 0) & (y > 0)).sum())} of {int((y > 0).sum())}",
                    "share_of_30d_revenue_known": round(e.sum() / y.sum(), 2),
                    "avg_30d_revenue_if_paid_early": round(y[e > 0].mean(), 2),
                    "avg_30d_revenue_if_not": round(y[e == 0].mean(), 3)})
    return pd.DataFrame(out)


def rule_benchmark(pday, installs, sets: pd.Series, k: int) -> tuple[pd.DataFrame, dict]:
    """Two baselines and the simple rule, fitted on train and scored on test (30-day revenue)."""
    r = _revenue_by_day(pday, installs)
    def table(ids):
        rr = r[r.PLAYER_ID.isin(ids)]
        t = pd.DataFrame(index=ids)
        t["early"] = rr[rr.day < k].groupby("PLAYER_ID").rev.sum().reindex(ids).fillna(0)
        t["y"] = rr[rr.day < C.HORIZON].groupby("PLAYER_ID").rev.sum().reindex(ids).fillna(0)
        return t
    tr, te = table(sets.index[sets == "train"]), table(sets.index[sets == "test"])
    paid = tr.early > 0
    mult = tr.y[paid].sum() / tr.early[paid].sum()
    np_rate = tr.y[~paid].mean()
    preds = {
        "Baseline: 30-day revenue = revenue so far": te.early,
        "Baseline: training average for everyone": pd.Series(tr.y.mean(), te.index),
        f"Rule: early spend x {mult:.2f}, else ${np_rate:.2f}": pd.Series(np.where(te.early > 0, te.early * mult, np_rate), te.index),
    }
    rows = []
    for name, p in preds.items():
        err = (te.y - p).abs()
        rows.append({"approach": name, "MAE_$": round(err.mean(), 2),
                     "predicted_/_actual_total": round(p.sum() / te.y.sum(), 2),
                     "MAE_payers_only_$": round(err[te.y > 0].mean(), 1)})
    info = {"k": k, "train_early_payers": int(paid.sum()), "multiplier": mult, "non_payer_rate": np_rate,
            "test_players": len(te), "test_payers": int((te.y > 0).sum()), "test_actual_total": te.y.sum()}
    return pd.DataFrame(rows), info


def monthly_ratios(pday, installs, data_end, exclude=(), months: int = 5) -> pd.DataFrame:
    """Revenue in month m+1 / month m, for cohorts old enough to have both months complete."""
    r = _revenue_by_day(pday, installs)
    r = r[~r.PLAYER_ID.isin(exclude) & (r.day >= 0)]
    r["m"] = r.day // 30
    t = r.groupby(["PLAYER_ID", "m"]).rev.sum().unstack(fill_value=0)
    out = []
    for m in range(months - 1):
        elig = installs[(installs + pd.Timedelta(days=30 * (m + 2) - 1)) <= pd.Timestamp(data_end)].index
        elig = elig.difference(pd.Index(exclude))
        tt = t.reindex(elig).fillna(0)
        a, b = tt.get(m, pd.Series(0, index=elig)).sum(), tt.get(m + 1, pd.Series(0, index=elig)).sum()
        out.append({"step": f"month {m + 1} → {m + 2}", "players": len(elig), "revenue_month_m": round(a, 0),
                    "revenue_month_m+1": round(b, 0), "ratio": round(b / a, 2) if a else np.nan})
    return pd.DataFrame(out)


def multiplier_table(rs=(0.5, 0.6, 0.7), example_30d: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame([{"r": r, "multiplier": round(C.multiplier(r), 2),
                          f"LTV365 for a ${example_30d:.0f} 30-day forecast": round(example_30d * C.multiplier(r), 2)}
                         for r in rs])


def update_rule_backtest(pday, installs, cutoffs=("2026-08-01", "2026-09-01", "2026-10-01"), r: float = C.R,
                         churn_days: int = C.CHURN_DAYS) -> pd.DataFrame:
    """Check the update rule's next-30-day projection (last 30 days x r; $0 if unseen 30+ days) at past dates.

    Players installed at least 30 days before the cutoff; actual = revenue in the 30 days after the cutoff.
    Compared with "next 30 days = last 30 days" and "next 30 days = $0".
    """
    rows = []
    rev = pday.assign(R=pday["REVENUE"].fillna(0.0), DATE=pd.to_datetime(pday["DATE"]))
    for c in map(pd.Timestamp, cutoffs):
        ids = installs.index[installs <= c - pd.Timedelta(days=30)]
        past = rev[(rev.DATE > c - pd.Timedelta(days=30)) & (rev.DATE <= c)].groupby("PLAYER_ID").R.sum().reindex(ids).fillna(0)
        fut = rev[(rev.DATE > c) & (rev.DATE <= c + pd.Timedelta(days=30))].groupby("PLAYER_ID").R.sum().reindex(ids).fillna(0)
        last = rev[rev.DATE <= c].groupby("PLAYER_ID").DATE.max().reindex(ids)
        churned = (c - last).dt.days >= churn_days
        for name, p in [("Update rule (last 30 days x r)", (past * r).where(~churned, 0.0)),
                        ("Last 30 days repeated", past), ("Zero", past * 0)]:
            rows.append({"cutoff": c.date(), "approach": name, "players": len(ids),
                         "payers_next_30d": int((fut > 0).sum()), "MAE_$": round((fut - p).abs().mean(), 2),
                         "predicted_$": round(p.sum(), 0), "actual_$": round(fut.sum(), 0),
                         "pred_over_actual": round(p.sum() / fut.sum(), 2) if fut.sum() else np.nan})
    return pd.DataFrame(rows)
