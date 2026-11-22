"""Score every player as of a date and store the result in SQLite (`ltv_scores`).

Run:  python -m sciplay.ltv.score --date 2026-11-04
      python -m sciplay.ltv.score --from 2026-10-09 --to 2026-11-04
Call: from sciplay.ltv.score import score; score("2026-11-04")

Who gets what, on score date D:
- model_d3     installed after the test period (from 7 Oct) and at least 3 days old: the day-3 model forecast,
               carried forward with "ahead / behind forecast" against expected revenue by day d.
- update_rule  installed before 7 Oct: NOT from the LTV model. Revenue to date + last 30 days' revenue x the
               remaining decay steps (same r), nothing more if not seen for 30+ days.
- cold_start   fewer than 3 days of data: no forecast (n/a).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sciplay.config import get_settings
from sciplay.data.asof import snapshot_as_of
from sciplay.ltv import config as C
from sciplay.ltv import learners as L
from sciplay.ltv import train as T

TABLE = "ltv_scores"
COLUMNS = ["score_date", "player_id", "model_version", "feature_date", "install_date", "age_days", "source",
           "eligibility_status", "ltv_to_date", "predicted_ltv_30", "multiplier", "predicted_ltv_365",
           "ltv_365_low", "ltv_365_high", "confidence", "expected_by_today", "gap_to_forecast",
           "days_since_last_seen", "reason_1", "reason_2", "reason_3", "created_at"]


# ------------------------------------------------------------------ model artefacts

def load_active(root: Path | None = None) -> tuple[dict, dict]:
    root = root or get_settings().model_dir / "ltv"
    version = json.loads((root / "active.json").read_text())["version"]
    meta = json.loads((root / version / "meta.json").read_text())
    return meta, joblib.load(root / version / "model.joblib")


# ------------------------------------------------------------------ reasons

AGG_WORDS = {"sum": "first 3 days", "per_day": "per day played", "max": "best day", "last": "on day 3",
             "change": "change over 3 days", "mean": "average", "share": "share of days", "any": "any"}
NAMED = {"revenue_first_k": "Spent in the first 3 days", "active_days": "Days played (of 3)",
         "played_day1": "Came back on day 2", "share_days_played": "Share of days played",
         "never_paid": "No purchase yet", "first_purchase_day": "Day of first purchase",
         "revenue_per_session": "Revenue per session", "store_conversion": "Store conversion",
         "last_active_day": "Last day played"}


def feature_label(name: str) -> str:
    if name in NAMED:
        return NAMED[name]
    if "=" in name:
        col, lvl = name.split("=", 1)
        return f"{col.replace('_', ' ').title()}: {lvl}"
    base, _, agg = name.partition("__")
    return f"{base.replace('_', ' ').capitalize()}, {AGG_WORDS.get(agg, agg)}"


def _fmt_value(v) -> str:
    if pd.isna(v):
        return "n/a"
    v = float(v)
    if abs(v) >= 1e9:
        return f"{v / 1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e4:
        return f"{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def dollar_effects(shap_log: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Dollar effect of each feature: how much lower (or higher) the forecast would be without that feature's
    contribution, all else equal. The model works on a log scale, so contributions multiply:
    forecast = average x exp(sum of SHAP); removing feature i divides the forecast by exp(SHAP_i).
    """
    return pred[:, None] * (1.0 - np.exp(-shap_log))


def top_reasons(effects: pd.Series, weights: pd.Series, values: pd.Series, typical: pd.Series | None = None,
                coverage: float = 0.7, max_n: int = 3, min_share: float = 0.10, min_dollars: float = 0.05,
                average: float | None = None) -> list[str]:
    """Features with the largest |SHAP| until they cover `coverage` of the player's total |SHAP|; at most `max_n`.

    Each reason reads: "<feature>: <this player's value> vs typical <median training player> (+/-$ effect)".
    """
    w = weights.abs().sort_values(ascending=False)
    total = w.sum()
    if total < 1e-9 or effects.abs().max() < min_dollars:
        avg = f" (average new player: ${average:.2f} still to come)" if average is not None else ""
        return [f"No strong value signals in the first 3 days: little or no play, spend or progress{avg}"]
    out, covered = [], 0.0
    for f in w.index:
        if len(out) == max_n or covered >= coverage or w[f] / total < min_share:
            break
        sign = "+" if effects[f] >= 0 else "−"
        typ = f" vs typical {_fmt_value(typical[f])}" if typical is not None and f in typical else ""
        out.append(f"{feature_label(f)}: {_fmt_value(values[f])}{typ} ({sign}${abs(effects[f]):.2f})")
        covered += w[f] / total
    return out


# ------------------------------------------------------------------ scoring

def remainder_share(curve: pd.Series, day: int, k: int = C.K) -> float:
    """Share of post-window 30-day revenue typically earned by the end of `day` (0 at day k-1, 1 at day 29)."""
    day = int(min(max(day, k - 1), C.HORIZON - 1))
    c0 = curve.iloc[k - 1]
    return float((curve.iloc[day] - c0) / (1 - c0)) if c0 < 1 else 1.0


def update_rule_remainder(last30: float, age: int, r: float = C.R) -> float:
    """last 30 days' revenue x (r + r^2 + ...) over the 30-day blocks left until day 365 (last block pro-rated)."""
    left = max(0, 365 - (age + 1)) / 30
    full, frac = int(left), left - int(left)
    steps = sum(r ** j for j in range(1, full + 1)) + frac * r ** (full + 1)
    return last30 * steps


def score(score_date, data: T.Data | None = None, store: bool = True, db_path: Path | None = None) -> pd.DataFrame:
    D = pd.Timestamp(score_date).normalize()
    d = data or T.load_data()
    meta, art = load_active()
    mult = float(art["multiplier"])
    curve = art["revenue_curve"]
    learner = L.LEARNERS[art["learner"]]

    pday = d.pday[d.pday["DATE"] <= D]
    installs = d.installs[d.installs <= D]
    out = pd.DataFrame(index=installs.index)
    out.index.name = "player_id"
    out["install_date"] = installs
    out["age_days"] = (D - installs).dt.days
    rev = pday.assign(R=pday["REVENUE"].fillna(0.0))
    # Revenue to date as defined in Part 1 (start-of-day LIFETIME_REVENUE + that day's REVENUE, last row on or before D)
    snap = snapshot_as_of(pday, D).set_index("PLAYER_ID")
    out["ltv_to_date"] = snap["revenue_to_date"].reindex(out.index).fillna(0.0)
    last_seen = pday.groupby("PLAYER_ID")["DATE"].max().reindex(out.index)
    out["days_since_last_seen"] = (D - last_seen).dt.days
    last30 = rev[rev["DATE"] > D - pd.Timedelta(days=30)].groupby("PLAYER_ID")["R"].sum().reindex(out.index).fillna(0.0)

    flags = [c for c in ["IS_CHEATER", "IS_CHEATER_DETECTED", "CHEATS_DETECTED", "IS_LEGAL_SETTLEMENT"] if c in pday]
    excluded = pd.Series(False, index=out.index)
    for c in flags:
        v = pday[c].astype("string").str.lower().isin(["true", "1", "1.0", "yes"])
        excluded |= v.groupby(pday["PLAYER_ID"]).any().reindex(out.index).fillna(False)
    out["eligibility_status"] = np.where(excluded, "excluded: cheater or legal settlement", "eligible")

    young = out["age_days"] < C.K - 1
    model_players = (~young) & (out["install_date"] > pd.Timestamp(C.TEST[1]))
    rule_players = (~young) & ~model_players
    out["source"] = np.select([young, model_players], ["cold_start", f"model_d{C.K}"], "update_rule")
    out["feature_date"] = pd.NaT
    for c in ["predicted_ltv_30", "predicted_ltv_365", "ltv_365_low", "ltv_365_high", "expected_by_today",
              "gap_to_forecast"]:
        out[c] = np.nan
    out["multiplier"] = mult
    out["confidence"] = "n/a"
    out[["reason_1", "reason_2", "reason_3"]] = None

    # --- model players: features from days 0..K-1 only
    ids = out.index[model_players]
    if len(ids):
        X = art["encoder"].transform(d.X_raw.loc[ids].drop(columns="feature_date")).reindex(columns=art["features"])
        first_k = d.lab.loc[ids, "revenue_first_k"].to_numpy()
        rem = art["model"].predict(X)
        boot = np.vstack([m.predict(X) for m in art["boot"]])
        lo, hi = T.scaled_range(rem, boot)
        ltv30 = first_k + rem
        out.loc[ids, "feature_date"] = installs.loc[ids] + pd.Timedelta(days=C.K - 1)
        out.loc[ids, "predicted_ltv_30"] = ltv30
        out.loc[ids, "predicted_ltv_365"] = ltv30 * mult
        out.loc[ids, "ltv_365_low"] = (first_k + lo) * mult
        out.loc[ids, "ltv_365_high"] = (first_k + hi) * mult
        out.loc[ids, "confidence"] = np.where(first_k > 0, "High", "Medium")
        share = out.loc[ids, "age_days"].map(lambda a: remainder_share(curve, a))
        expected = first_k + rem * share.to_numpy()
        out.loc[ids, "expected_by_today"] = expected
        out.loc[ids, "gap_to_forecast"] = out.loc[ids, "ltv_to_date"].to_numpy() - expected
        # reasons: features ranked by |SHAP| (log scale); each shown with its dollar effect and the typical value
        tr = d.sets.index[d.sets == "train"]
        Xtr = art["encoder"].transform(d.X_raw.loc[tr].drop(columns="feature_date")).reindex(columns=art["features"])
        typical = Xtr.median()
        average = float(art["model"].predict(Xtr).mean())
        sv = learner.shap_values(art["model"], X)
        eff = pd.DataFrame(dollar_effects(sv, rem), index=ids, columns=X.columns)
        svd = pd.DataFrame(sv, index=ids, columns=X.columns)
        for pid in ids:
            rs = top_reasons(eff.loc[pid], svd.loc[pid], X.loc[pid], typical, average=average)
            out.loc[pid, ["reason_1", "reason_2", "reason_3"]] = (rs + [None, None, None])[:3]

    # --- update rule players (not from the LTV model)
    ids = out.index[rule_players]
    if len(ids):
        churned = out.loc[ids, "days_since_last_seen"] >= C.CHURN_DAYS
        remainder = pd.Series([update_rule_remainder(l30, a) for l30, a in
                               zip(last30.loc[ids], out.loc[ids, "age_days"])], index=ids).where(~churned, 0.0)
        out.loc[ids, "predicted_ltv_365"] = out.loc[ids, "ltv_to_date"] + remainder
        observed = out.loc[ids, "ltv_to_date"] / out.loc[ids, "predicted_ltv_365"].replace(0, np.nan)
        out.loc[ids, "confidence"] = np.where(observed.fillna(1) >= 0.8, "High", "Medium")
        for pid in ids:
            if churned[pid]:
                out.loc[pid, "reason_1"] = (f"Not from the LTV model: not seen for {int(out.loc[pid, 'days_since_last_seen'])} "
                                            "days, so no further revenue is projected")
            else:
                out.loc[pid, "reason_1"] = (f"Not from the LTV model: revenue to date ${out.loc[pid, 'ltv_to_date']:,.2f} "
                                            f"+ projected ${remainder[pid]:,.2f} (last 30 days ${last30[pid]:,.2f}, "
                                            f"fading by r = {C.R} a month)")

    out.loc[young, "reason_1"] = f"Too new to forecast: first forecast on day {C.K}"
    out["score_date"] = D.date().isoformat()
    out["model_version"] = meta["version"]
    out["created_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    out = out.reset_index()
    for c in ["feature_date", "install_date"]:
        out[c] = pd.to_datetime(out[c]).dt.date.astype("string")
    out = out[COLUMNS]
    if store:
        write(out, db_path)
    return out


def write(df: pd.DataFrame, db_path: Path | None = None) -> None:
    """Insert or replace by (score_date, player_id, model_version): reruns never duplicate."""
    db = Path(db_path or get_settings().store_db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as con:
        con.execute("PRAGMA journal_mode=TRUNCATE")   # no journal-file deletes (works on synced/mounted folders)
        cols = ", ".join(f'"{c}"' for c in COLUMNS)
        con.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} ({cols}, PRIMARY KEY (score_date, player_id, model_version))")
        con.executemany(f"INSERT OR REPLACE INTO {TABLE} ({cols}) VALUES ({', '.join('?' * len(COLUMNS))})",
                        df.astype(object).where(df.notna(), None).itertuples(index=False, name=None))


def read(score_date=None, db_path: Path | None = None) -> pd.DataFrame:
    db = Path(db_path or get_settings().store_db_path)
    if not db.exists():
        return pd.DataFrame(columns=COLUMNS)
    with sqlite3.connect(db) as con:
        q = f"SELECT * FROM {TABLE}" + (" WHERE score_date = ?" if score_date is not None else "")
        args = (pd.Timestamp(score_date).date().isoformat(),) if score_date is not None else ()
        try:
            return pd.read_sql_query(q, con, params=args)
        except Exception:
            return pd.DataFrame(columns=COLUMNS)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    a = ap.parse_args()
    data = T.load_data()
    dates = [a.date] if a.date else pd.date_range(a.start, a.end, freq="D")
    for dt in dates:
        res = score(dt, data)
        print(pd.Timestamp(dt).date(), res["source"].value_counts().to_dict(),
              f"LTV365 total ${res['predicted_ltv_365'].sum():,.0f}")
