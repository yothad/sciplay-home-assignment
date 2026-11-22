"""Signals for every eligible player as of a score date (only rows dated on or before it)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sciplay.lists import config as L
from sciplay.ltv import config as LC
from sciplay.ltv.score import update_rule_remainder

PURCHASE_FAIL_COLS = ["FAILED_PURCHASE", "PURCHASE_FAILURES", "STORES_VERIFY_PURCHASE_FAILURE"]


def is_drop(recent, baseline, share: float) -> pd.Series:
    """Decline vs baseline: recent <= (1 - share) x baseline, only where the baseline is above zero (inclusive)."""
    recent, baseline = pd.Series(recent, dtype=float), pd.Series(baseline, dtype=float)
    return (baseline > 0) & (recent <= (1 - share) * baseline + 1e-9)


def is_overdue(days_since, usual_gap, factor: float, min_days: float = 0, max_days: float = np.inf) -> pd.Series:
    """Longer than `factor` x the usual gap (strictly), and between `min_days` and `max_days`; needs a usual gap."""
    days_since, usual_gap = pd.Series(days_since, dtype=float), pd.Series(usual_gap, dtype=float)
    return (usual_gap.notna() & (days_since > factor * usual_gap) & (days_since >= min_days)
            & (days_since <= max_days))


def _usual_gap(days_by_player: pd.Series, ids, min_days: int = 2) -> pd.Series:
    """Median gap in days between consecutive dates, for players with at least `min_days` dates."""
    out = pd.Series(np.nan, index=ids)
    for pid, days in days_by_player.items():
        if pid in out.index and len(days) >= min_days:
            out[pid] = float(np.median(np.diff(days).astype("timedelta64[D]").astype(float)))
    return out


def _window(rows, D, start_days, end_days):
    """Rows with D - start_days < DATE <= D - end_days."""
    return rows[(rows["DATE"] > D - pd.Timedelta(days=start_days)) & (rows["DATE"] <= D - pd.Timedelta(days=end_days))]


def _sum(df, col, ids):
    if col not in df:
        return pd.Series(0.0, index=ids)
    return df[col].astype(float).fillna(0).groupby(df["PLAYER_ID"]).sum().reindex(ids).fillna(0.0)


def peer_activity(pday: pd.DataFrame, installs: pd.Series, D: pd.Timestamp, window: int = L.RECENT_DAYS,
                  max_age: int = L.YOUNG_DAYS) -> pd.Series:
    """Median days played in the `window` days ending at each age, over players who had reached that age by D."""
    d = (pday["DATE"] - pday["PLAYER_ID"].map(installs)).dt.days
    rows = pday.assign(day=d)[d >= 0]
    out = {}
    for age in range(L.MIN_AGE_DAYS - 1, max_age + 1):
        reached = installs.index[installs + pd.Timedelta(days=age) <= D]
        if len(reached) < 20:
            continue
        lo = age - window + 1
        w = rows[(rows["day"] >= lo) & (rows["day"] <= age) & rows["PLAYER_ID"].isin(reached)]
        cnt = w.groupby("PLAYER_ID")["day"].nunique().reindex(reached).fillna(0)
        out[age] = float(cnt.median())
    return pd.Series(out, name="peer_days")


def compute(pday: pd.DataFrame, installs: pd.Series, D, ltv: pd.DataFrame, cfg=L) -> pd.DataFrame:
    """One row per player known by D with eligibility, signal values, triggers and the opportunity gap."""
    D = pd.Timestamp(D).normalize()
    rows = pday[pday["DATE"] <= D]
    inst = installs[installs <= D]
    ids = inst.index
    out = pd.DataFrame(index=ids)
    out.index.name = "player_id"
    out["age_days"] = (D - inst).dt.days
    last = rows.groupby("PLAYER_ID")["DATE"].max().reindex(ids)
    out["days_since_last_seen"] = (D - last).dt.days
    lt = ltv.set_index("player_id").reindex(ids)
    out["source"] = lt["source"]
    out["predicted_ltv_365"] = lt["predicted_ltv_365"]
    out["ltv_to_date"] = lt["ltv_to_date"].fillna(0.0)
    out["eligibility_status"] = lt["eligibility_status"].fillna("eligible")
    why = np.select([out["eligibility_status"] != "eligible", out["age_days"] < cfg.MIN_AGE_DAYS,
                     out["days_since_last_seen"] > cfg.MAX_DAYS_UNSEEN],
                    ["excluded flag", f"under {cfg.MIN_AGE_DAYS} days old", "not seen in 30 days (churned)"], "")
    out["ineligible_reason"] = why
    out["eligible"] = why == ""

    recent = _window(rows, D, cfg.RECENT_DAYS, 0)
    prior = _window(rows, D, cfg.RECENT_DAYS + cfg.PRIOR_DAYS, cfg.RECENT_DAYS)
    weeks_prior = cfg.PRIOR_DAYS / 7

    # ---- friction (recent window vs own baseline)
    f_trig = pd.Series("", index=ids)
    events = pd.Series(0.0, index=ids)
    def _load_fail(df):
        return sum((_sum(df, a, ids) - _sum(df, b, ids)).clip(lower=0) for a, b in cfg.LOAD_PAIRS)
    for col, label in [("CRASHES", "crashes"), ("ERROR_UNHANDLED", "unhandled errors"),
                       ("purchase_failures", "failed purchases"), ("ZENDESK_TICKETS", "support tickets"),
                       ("load_failures", "load failures")]:
        if col == "purchase_failures":
            r = sum(_sum(recent, c, ids) for c in PURCHASE_FAIL_COLS)
            p = sum(_sum(prior, c, ids) for c in PURCHASE_FAIL_COLS)
        elif col == "load_failures":
            r, p = _load_fail(recent), _load_fail(prior)
        else:
            r, p = _sum(recent, col, ids), _sum(prior, col, ids)
        out[f"recent_{label.replace(' ', '_')}"] = r
        hit = (r >= cfg.FRICTION_MIN[col]) & (r > p / weeks_prior)
        events += r.where(hit, 0)
        f_trig = f_trig.where(~hit, f_trig + "|" + label + ":" + r.astype(int).astype(str))
    starts, done = _sum(recent, "PURCHASE_STARTS", ids), _sum(recent, "PURCHASE_COMPLETED", ids)
    inc = (starts >= cfg.INCOMPLETE_ATTEMPTS_MIN) & (done == 0)
    out["recent_incomplete_attempts"] = starts.where(done == 0, 0)
    events += starts.where(inc, 0)
    f_trig = f_trig.where(~inc, f_trig + "|incomplete purchase attempts:" + starts.astype(int).astype(str))
    out["recent_cancellations"] = _sum(recent, "PURCHASE_CANCELS", ids)
    out["friction_triggers"] = f_trig.str.strip("|")
    out["friction_events"] = events

    # ---- revenue
    rev = rows.assign(R=rows["REVENUE"].fillna(0.0))
    last28 = _sum(_window(rev, D, cfg.SPEND_DAYS, 0), "R", ids)
    prev28 = _sum(_window(rev, D, 2 * cfg.SPEND_DAYS, cfg.SPEND_DAYS), "R", ids)
    out["spend_last_28d"], out["spend_prev_28d"] = last28, prev28
    paid_days = rev[rev["R"] > 0].groupby("PLAYER_ID")["DATE"].apply(lambda s: sorted(s.unique()))
    usual_gap = _usual_gap(paid_days, ids, 2)
    since_purchase = pd.Series({pid: (D - days[-1]).days for pid, days in paid_days.items()}, dtype=float).reindex(ids)
    out["usual_purchase_gap"], out["days_since_purchase"] = usual_gap, since_purchase
    payer = out["ltv_to_date"] > 0
    elig_ltv = out.loc[out["eligible"], "predicted_ltv_365"].dropna()
    top_cut = elig_ltv.quantile(1 - cfg.VALUABLE_TOP_SHARE) if len(elig_ltv) else np.inf
    valuable_np = (~payer) & (out["predicted_ltv_365"] >= top_cut) & (out["predicted_ltv_365"] > 0)
    out["valuable"] = np.select([payer, valuable_np], ["payer", "high predicted value"], "")

    drop = is_drop(last28, prev28, cfg.SPEND_DROP)
    overdue = is_overdue(since_purchase, usual_gap, cfg.OVERDUE_FACTOR)
    expected = lt["expected_by_today"]
    behind_amt = (expected - out["ltv_to_date"]).where(out["source"] == "model_d3")
    behind = (behind_amt >= cfg.BEHIND_MIN_DOLLARS) & (out["ltv_to_date"] <= (1 - cfg.BEHIND_SHARE) * expected)
    out["behind_forecast_dollars"] = behind_amt
    out["spend_drop_share"] = (1 - last28 / prev28).where(prev28 > 0)

    # ---- engagement (own pace; young players vs peers of the same age)
    r_days = recent.groupby("PLAYER_ID")["DATE"].nunique().reindex(ids).fillna(0)
    p_days = prior.groupby("PLAYER_ID")["DATE"].nunique().reindex(ids).fillna(0)
    r_sess, p_sess = _sum(recent, "SESSIONS", ids), _sum(prior, "SESSIONS", ids)
    pace_days, pace_sess = p_days / weeks_prior, p_sess / weeks_prior
    out["days_played_7d"], out["baseline_days_per_week"] = r_days, pace_days
    out["sessions_7d"], out["baseline_sessions_per_week"] = r_sess, pace_sess
    old = out["age_days"] >= cfg.YOUNG_DAYS
    days_drop = old & (pace_days >= cfg.MIN_PRIOR_DAYS_PER_WEEK) & is_drop(r_days, pace_days, 1 - cfg.ACTIVITY_DROP)
    sess_drop = old & (pace_sess >= cfg.MIN_PRIOR_SESSIONS_PER_WEEK) & is_drop(r_sess, pace_sess, 1 - cfg.ACTIVITY_DROP)
    peers = peer_activity(pday, installs, D)
    peer_med = out["age_days"].map(peers)
    out["peer_days_7d"] = peer_med
    young_drop = (~old) & peer_med.notna() & (peer_med >= 1) & is_drop(r_days, peer_med, 1 - cfg.ACTIVITY_DROP)
    # Return signal: not seen for longer than usual (days since last login or spin vs the usual gap between days played)
    play_days = rows.groupby("PLAYER_ID")["DATE"].apply(lambda s: sorted(s.unique()))
    out["usual_play_gap"] = _usual_gap(play_days, ids, cfg.MIN_PLAY_DAYS_FOR_GAP)
    overdue_return = is_overdue(out["days_since_last_seen"], out["usual_play_gap"], cfg.RETURN_FACTOR,
                                cfg.RETURN_MIN_DAYS, cfg.RETURN_MAX_DAYS)
    out["eng_overdue_return"] = overdue_return
    eng = days_drop | sess_drop | young_drop | overdue_return
    base_days = pace_days.where(old, peer_med)
    out["activity_drop_share"] = (1 - r_days / base_days).where(base_days > 0).clip(lower=0)
    out["eng_days_drop"], out["eng_sessions_drop"], out["eng_young_vs_peers"] = days_drop, sess_drop, young_drop

    out["rev_spend_drop"], out["rev_overdue"], out["rev_behind_forecast"] = drop, overdue, behind
    out["rev_valuable_losing_activity"] = valuable_np & eng
    out["any_friction"] = out["friction_triggers"] != ""
    out["any_revenue"] = (payer & (drop | overdue)) | behind | out["rev_valuable_losing_activity"]
    out["any_engagement"] = eng

    # ---- opportunity gap: expected value at the player's baseline - revised value now (never below 0)
    older = out["source"] == "update_rule"
    rem_prev = [update_rule_remainder(v * 30 / cfg.SPEND_DAYS, a) for v, a in zip(prev28, out["age_days"])]
    rem_now = [update_rule_remainder(v * 30 / cfg.SPEND_DAYS, a) for v, a in zip(last28, out["age_days"])]
    gap_old = (pd.Series(rem_prev, index=ids) - pd.Series(rem_now, index=ids)).clip(lower=0)
    gap_new = (behind_amt.clip(lower=0) * LC.multiplier()).fillna(0)
    out["opportunity_gap"] = np.where(older, gap_old, gap_new)
    return out
