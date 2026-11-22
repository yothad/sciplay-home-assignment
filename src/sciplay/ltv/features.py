"""Features from each player's first K days, one row per player.

Only rows dated install .. install + K - 1 are read (the as-of rule for a forecast made on day K),
and only columns the registry allows as features, minus the exclusions below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sciplay.ltv import config as C
from sciplay.ltv.labels import day_index

# ------------------------------------------------------------------ column choice

CATEGORICAL_LOW = ["MAIN_PLATFORM_ID", "DEVICE_TYPE", "REGION", "SOURCE_TYPE_FIRST", "ATTRIBUTION_TYPE"]
CATEGORICAL_HIGH = ["COUNTRY", "SOURCE_FIRST", "OS_VERSION"]
CATEGORICAL = CATEGORICAL_LOW + CATEGORICAL_HIGH

# Columns the registry allows but the LTV features leave out, with the reason.
EXCLUDE = [
    (r"^LAST_\d+W_|_14D$|_14DAY$|_EWMA$|_NL$|_LAST_\d+_ENG|^PLATFORM_AGNOSTIC_LAST_|^AVG_LAST_\d+_PURCHASES$"
     r"|^ACTIVE_\d+D_PAYER_DAU$|^MAX_WEEKLY_SPEND$",
     "file's own rolling window: duplicates our sums, window end not documented"),
    (r"LIFETIME|^LT_|CONSECUTIVE", "lifetime / consecutive counter: duplicates our sums, may be rewritten"),
    (r"DAYS_SINCE|^LOGIN_DAYS_SINCE", "recency: rebuilt from our own rows"),
    (r"^I\d+_REVENUE$", "install-window revenue: forward-looking (I14/I30) or duplicate (I3/I7)"),
    (r"(APP|SERVER|TECH)_VERSION|^DEVICE_OS_VERSION$", "version: marks when a player installed"),
    (r"^DEVICE_HARDWARE$", "367 levels for 300 players"),
    (r"^SENIORITY$|^INSTALL_FLAG$|^REACTIVATED$|^UPGRADED_FLAG$", "constant or near constant in the first days"),
]

STATE = re.compile(r"LEVEL$|LEVEL_TRACK$|BANKROLL|SLIB|PLAYDAYS_LEFT")
AVERAGE = re.compile(r"^MEDIAN_|^AVG_|^MIN_|^MAX_|DEFAULT_BET|BET_DENOM|LATENCY|_LN$|FPS|LOAD_TIME|SPIN_LENGTH"
                     r"|^FIRST_LOAD$")


@dataclass
class FeatureSpec:
    count: list[str] = field(default_factory=list)      # type 1: sum, mean per active day, max
    state: list[str] = field(default_factory=list)      # type 2: last value (+ change for levels)
    average: list[str] = field(default_factory=list)    # type 3: mean over active days
    friction: list[str] = field(default_factory=list)   # type 4: sum + any
    flag: list[str] = field(default_factory=list)       # type 5: share of active days
    categorical: list[str] = field(default_factory=list)  # types 7-8: first row, encoded later
    excluded: dict[str, str] = field(default_factory=dict)

    def as_table(self) -> pd.DataFrame:
        rows = [(c, t) for t in ("count", "state", "average", "friction", "flag", "categorical")
                for c in getattr(self, t)]
        rows += [(c, "excluded: " + why) for c, why in self.excluded.items()]
        return pd.DataFrame(rows, columns=["column", "feature_type"])


def build_spec(registry: pd.DataFrame, pday: pd.DataFrame) -> FeatureSpec:
    """Type every allowed column."""
    reg = registry.set_index("column")
    allowed = reg.index[reg["model_feature"].astype(bool) & reg["category"].isin(["Observed measures", "Dimensions"])]
    spec = FeatureSpec()
    for col in allowed:
        if col not in pday.columns:
            continue
        if reg.loc[col, "field_group"] == "Device, app & performance" and col != "MAIN_PLATFORM_ID":
            spec.excluded[col] = ("device, app & performance: describes the phone and app, not the player's intent "
                                  "to spend; with 6 payers it learned noise (used in the Part 4 friction list instead)")
            continue
        if col in CATEGORICAL:
            spec.categorical.append(col)
            continue
        why = next((w for pat, w in EXCLUDE if re.search(pat, col)), None)
        if why:
            spec.excluded[col] = why
            continue
        s = pday[col]
        if not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s)):
            spec.excluded[col] = "not numeric"
            continue
        if reg.loc[col, "field_group"] == "Errors & friction":
            spec.friction.append(col)
        elif STATE.search(col):
            spec.state.append(col)
        elif AVERAGE.search(col):
            spec.average.append(col)
        elif set(pd.unique(s.dropna().astype(float))) <= {0.0, 1.0}:
            spec.flag.append(col)
        else:
            spec.count.append(col)
    spec.categorical += [c for c in ["MAIN_PLATFORM_ID"] if c in pday.columns and c not in spec.categorical]
    return spec


# ------------------------------------------------------------------ building

def window_rows(pday: pd.DataFrame, installs: pd.Series, k: int = C.K) -> pd.DataFrame:
    """Rows dated install .. install + k - 1 (the as-of rule), with the day index."""
    d = day_index(pday, installs)
    rows = pday.loc[(d >= 0) & (d < k)].copy()
    rows["day"] = d[rows.index]
    return rows.sort_values(["PLAYER_ID", "day"])


def build_features(pday: pd.DataFrame, installs: pd.Series, spec: FeatureSpec, k: int = C.K) -> pd.DataFrame:
    """One row per player: numeric features + raw categorical columns (encode with CategoryEncoder)."""
    rows = window_rows(pday, installs, k)
    g = rows.groupby("PLAYER_ID")
    active = g["day"].nunique()
    parts = {}

    if spec.count:
        x = rows[spec.count].astype(float).fillna(0.0)
        sums = x.groupby(rows["PLAYER_ID"]).sum()
        parts["sum"] = sums.add_suffix("__sum")
        parts["mean"] = sums.div(active, axis=0).add_suffix("__per_day")
        parts["max"] = x.groupby(rows["PLAYER_ID"]).max().add_suffix("__max")
    if spec.state:
        x = rows[spec.state].astype(float)
        parts["last"] = x.groupby(rows["PLAYER_ID"]).last().add_suffix("__last")
        lvl = [c for c in spec.state if c.endswith("LEVEL")]
        if lvl:
            first = x[lvl].groupby(rows["PLAYER_ID"]).first()
            parts["change"] = (parts["last"][[c + "__last" for c in lvl]].values - first).add_suffix("__change")
    if spec.average:
        parts["avg"] = rows[spec.average].astype(float).groupby(rows["PLAYER_ID"]).mean().add_suffix("__mean")
    if spec.friction:
        x = rows[spec.friction].astype(float).fillna(0.0)
        s = x.groupby(rows["PLAYER_ID"]).sum()
        parts["fr_sum"] = s.add_suffix("__sum")
        parts["fr_any"] = (s > 0).astype(float).add_suffix("__any")
    if spec.flag:
        x = rows[spec.flag].astype(float).fillna(0.0)
        parts["flag"] = x.groupby(rows["PLAYER_ID"]).mean().add_suffix("__share")

    # Type 6: built from our own rows.
    rev = rows["REVENUE"].fillna(0.0)
    paid_days = rows.loc[rev > 0]
    own = pd.DataFrame(index=active.index)
    own["revenue_first_k"] = rev.groupby(rows["PLAYER_ID"]).sum()
    own["active_days"] = active
    own["share_days_played"] = active / k
    own["played_day1"] = g["day"].apply(lambda s: float((s == 1).any()))
    own["last_active_day"] = g["day"].max()
    own["first_purchase_day"] = paid_days.groupby("PLAYER_ID")["day"].min()
    own["never_paid"] = own["first_purchase_day"].isna().astype(float)
    sessions = rows["SESSIONS"].astype(float).fillna(0).groupby(rows["PLAYER_ID"]).sum() if "SESSIONS" in rows else None
    if sessions is not None:
        own["revenue_per_session"] = own["revenue_first_k"] / sessions.replace(0, np.nan)
    for num, den, name in [("PURCHASE_COMPLETED", "STORES_IMPRESSION", "store_conversion"),
                           ("PURCHASE_FAILURES", "PURCHASE_STARTS", "purchase_failure_rate")]:
        if num in rows and den in rows:
            n = rows[num].astype(float).fillna(0).groupby(rows["PLAYER_ID"]).sum()
            dd = rows[den].astype(float).fillna(0).groupby(rows["PLAYER_ID"]).sum()
            own[name] = n / dd.replace(0, np.nan)

    cats = g[spec.categorical].first() if spec.categorical else pd.DataFrame(index=active.index)
    if "OS_VERSION" in cats:
        cats["OS_VERSION"] = cats["OS_VERSION"].astype("string").str.split(".").str[0]
    out = pd.concat([own] + list(parts.values()) + [cats], axis=1)
    out.index.name = "PLAYER_ID"
    out["feature_date"] = installs.reindex(out.index) + pd.Timedelta(days=k - 1)
    return out


# ------------------------------------------------------------------ encoding and pruning

@dataclass
class CategoryEncoder:
    """One-hot; levels held by fewer than MIN_CATEGORY_PLAYERS training players become "Other"."""
    columns: list[str]
    min_players: int = C.MIN_CATEGORY_PLAYERS
    levels_: dict[str, list[str]] = field(default_factory=dict)

    def fit(self, X: pd.DataFrame) -> "CategoryEncoder":
        for c in self.columns:
            vc = X[c].astype("string").fillna("unknown").value_counts()
            self.levels_[c] = sorted(vc[vc >= self.min_players].index.tolist())
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        out = X.drop(columns=self.columns)
        for c in self.columns:
            v = X[c].astype("string").fillna("unknown")
            v = v.where(v.isin(self.levels_[c]), "Other")
            for lvl in self.levels_[c] + ["Other"]:
                out[f"{c}={lvl}"] = (v == lvl).astype(float)
        return out


def prefilter(X: pd.DataFrame, min_nonzero: int = C.MIN_NONZERO_PLAYERS, corr_max: float = C.CORR_MAX,
              priority: list[str] | None = None) -> tuple[list[str], pd.DataFrame]:
    """Drop features non-zero for too few players, then one of each highly correlated pair.

    `priority` columns are kept first when two are correlated. Returns kept columns and a log.
    """
    log = []
    cols = [c for c in X.columns if X[c].notna().any()]
    nz = (X[cols].fillna(0) != 0).sum()
    keep = [c for c in cols if nz[c] >= min_nonzero and X[c].nunique(dropna=True) > 1]
    log += [(c, "non-zero for fewer than %d players or constant" % min_nonzero) for c in X.columns if c not in keep]
    order = [c for c in (priority or []) if c in keep] + [c for c in keep if c not in (priority or [])]
    corr = X[order].corr(method="spearman").abs()
    kept: list[str] = []
    for c in order:
        twin = next((k for k in kept if corr.loc[c, k] > corr_max), None)
        if twin is None:
            kept.append(c)
        else:
            log.append((c, f"correlated > {corr_max} with {twin}"))
    return kept, pd.DataFrame(log, columns=["feature", "dropped_because"])
