"""Column registry: role, as-of availability, null meaning and usage for every column.

The registry is the contract between the audit and the pipeline:
- `use` decides whether a column may enter the model, the lists, or neither;
- `as_of` says when its value is known relative to the row date D;
- `null_meaning` says how a null must be read (zero, unknown, not applicable).

Rules are ordered and name-based, then corrected by evidence from the data
(columns with no information; date fields later than D; milestone flags that are
set before the player reached that age).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from sciplay.data.loader import parse_date_like

# ------------------------------------------------------------------ vocabularies
# role: what the column is
ID, TIMESTAMP, DIMENSION, MEASURE, SNAPSHOT, LABEL_LIKE, METADATA = (
    "identifier", "timestamp", "dimension", "daily measure", "snapshot (rolling/lifetime)",
    "label-like", "metadata",
)
# as_of: when the value is known relative to the row date D
STATIC = "static (set at install)"
END_OF_D = "end of day D"
START_OF_D = "start of day D (excludes D)"
AS_OF_D = "as of D (window end to verify)"
BACKFILLED = "back-filled after D"
FUTURE = "future (after D)"
PROCESSING = "processing time"
UNCLEAR = "unclear: window may extend past D"
# use: what the pipeline does with it
U_KEY = "key"
U_FILTER = "eligibility filter"
U_FEATURE = "feature"
U_SEGMENT = "segment / reporting"
U_DERIVE = "derive feature (e.g. days since)"
U_META = "freshness checks only"
X_LEAK = "exclude: leakage"
X_TARGET = "exclude: not a valid target"
X_UNVERIFIED = "exclude until verified"
X_NOINFO = "exclude: no information"
X_REDUNDANT = "exclude: redundant"

NULL_ZERO = "zero: no event that day"
NULL_NA = "not applicable: no event yet"
NULL_UNKNOWN = "unknown"
NULL_NONE = "n/a"

SNAPSHOT_PATTERN = r"LIFETIME|^LT_|^LAST_\d+W|_EWMA|_14D|^AVG_|^MAX_|CONSECUTIVE|^PLATFORM_AGNOSTIC_LAST_\d+|DAYS_SINCE"


@dataclass(frozen=True)
class Rule:
    name: str
    test: callable
    role: str
    as_of: str
    use: str
    null_meaning: str
    note: str = ""


def _m(pattern: str):
    rx = re.compile(pattern)
    return lambda col, grp: bool(rx.search(col))


def _g(*groups: str):
    return lambda col, grp: grp in groups


def _and(*tests):
    return lambda col, grp: all(t(col, grp) for t in tests)


RULES: list[Rule] = [
    Rule("keys", _g("Keys & identifiers"), ID, STATIC, U_KEY, NULL_NONE),
    Rule("row date", _m(r"^DATE$"), TIMESTAMP, END_OF_D, U_KEY, NULL_NONE, "Row date D"),
    Rule("pipeline metadata", _g("Pipeline metadata"), METADATA, PROCESSING, U_META, NULL_NONE,
         "Rows are rewritten until 91 days after D (Q3)"),
    Rule("compliance", _g("Compliance flags"), DIMENSION, AS_OF_D, U_FILTER, NULL_UNKNOWN,
         "Exclude cheaters and legal settlements from lists; never set in the sample (Q6)"),
    Rule("future fields", _m(r"^NEXT_|DAYS_UNTIL|^CHURNERS"), LABEL_LIKE, FUTURE, X_LEAK, NULL_NONE,
         "Describes what happens after D"),
    Rule("spend windows", _m(r"^D(30|365)_SPEND$"), LABEL_LIKE, AS_OF_D, X_TARGET, NULL_NA,
         "Lifetime-to-date spend, not a fixed-window outcome (Q1)"),
    Rule("milestone flags", _m(r"^D\d+(_RETURNER|_CONVERTER)?$|^SPENDER_\d+$|^D30_PAYER_BIN$"),
         LABEL_LIKE, BACKFILLED, X_LEAK, NULL_NONE,
         "Forward-looking label: D<n>_RETURNER = played exactly n days after D (Q3, Q5)"),
    Rule("first-N-days windows", _m(r"^D\d+_(ACTIVE|PURCHASE|SPINS)_DAYS$"), SNAPSHOT, UNCLEAR,
         X_UNVERIFIED, NULL_NONE, "Rebuild from daily rows instead"),
    Rule("install dates", _m(r"^(FIRST_)?INSTALL_DATE$"), TIMESTAMP, STATIC, U_DERIVE, NULL_NONE,
         "Age = D - install date"),
    Rule("accounting date", _m(r"^ACCOUNTING_DATE$"), TIMESTAMP, END_OF_D, X_REDUNDANT, NULL_NONE,
         "Month of D"),
    Rule("daily event times", _m(r"^(FIRST|LAST)_DAILY_EVENT$"), TIMESTAMP, END_OF_D, U_DERIVE, NULL_NA,
         "First and last event time of day D"),
    Rule("event dates", _g("Dates & timestamps"), TIMESTAMP, AS_OF_D, U_DERIVE, NULL_NA,
         "Turn into days since the event"),
    Rule("acquisition & geography", _g("Acquisition", "Geography"), DIMENSION, STATIC,
         U_FEATURE + " + " + U_SEGMENT, NULL_UNKNOWN),
    Rule("segments", _g("Segments & bins"), DIMENSION, AS_OF_D, U_SEGMENT, NULL_UNKNOWN,
         "Bucketed from other fields; use the source measures in models"),
    Rule("device dims", _and(_g("Device, app & performance"), _m(r"DEVICE|VERSION|^UPGRADED_FLAG$")),
         DIMENSION, END_OF_D, U_FEATURE + " + " + U_SEGMENT, NULL_UNKNOWN),
    Rule("lifetime revenue", _m(r"^LIFETIME_REVENUE$"), SNAPSHOT, START_OF_D, U_FEATURE, NULL_NA,
         "Today's REVENUE lands in tomorrow's value (Q2)"),
    Rule("snapshots", _m(SNAPSHOT_PATTERN), SNAPSHOT, AS_OF_D, U_FEATURE, NULL_NA),
    Rule("friction", _g("Errors & friction"), MEASURE, END_OF_D, U_FEATURE, NULL_ZERO,
         "Signal for the friction list"),
    Rule("daily measures", lambda c, g: True, MEASURE, END_OF_D, U_FEATURE, NULL_ZERO),
]


def _first_rule(col: str, group: str) -> Rule:
    for rule in RULES:
        if rule.test(col, group):
            return rule
    raise AssertionError("catch-all rule missing")


# ------------------------------------------------------------------ evidence


def milestone_backfill_evidence(df: pd.DataFrame) -> pd.DataFrame:
    """For D<n> columns: rows where the value is positive before the player is n days old."""
    out = []
    for col in df.columns:
        m = re.match(r"^D(\d+)(_|$)", col)
        if not m:
            continue
        n = int(m.group(1))
        values = pd.to_numeric(df[col], errors="coerce")
        young = df["DAYS_SINCE_INSTALL"] < n
        out.append({
            "column": col,
            "age_days": n,
            "rows_younger_than_age": int(young.sum()),
            "positive_before_age": int((young & (values > 0)).sum()),
        })
    return pd.DataFrame(out)


def returner_label_evidence(df: pd.DataFrame, horizons=(1, 3, 7, 14, 21, 30, 60, 90)) -> pd.DataFrame:
    """Test D<n>_RETURNER against 'the player has a row exactly n days after D'.

    Only rows whose D + n is inside the data are tested.
    """
    active = set(zip(df["PLAYER_ID"], df["DATE"]))
    end = df["DATE"].max()
    out = []
    for n in horizons:
        col = f"D{n}_RETURNER"
        if col not in df.columns:
            continue
        target = df["DATE"] + pd.Timedelta(days=n)
        testable = target <= end
        played = pd.Series([(p, d) in active for p, d in zip(df["PLAYER_ID"], target)], index=df.index)
        flag = pd.to_numeric(df[col], errors="coerce") > 0
        out.append({"column": col, "days_after_D": n, "rows_tested": int(testable.sum()),
                    "match_share": float((flag == played)[testable].mean())})
    return pd.DataFrame(out)


def future_date_evidence(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Share of filled values later than the row date, for date-like columns."""
    shares = {}
    for col in columns:
        d = parse_date_like(df[col])
        filled = d.notna().sum()
        shares[col] = float((d > df["DATE"]).sum() / filled) if filled else np.nan
    return pd.Series(shares, name="share_after_D")


# ------------------------------------------------------------------ registry


def build_registry(df: pd.DataFrame, profile: pd.DataFrame) -> pd.DataFrame:
    """One row per column with group, role, as-of, null meaning, use and the evidence."""
    prof = profile.set_index("column")
    date_cols = [c for c in df.columns if prof.loc[c, "field_group"] == "Dates & timestamps" and c != "DATE"]
    future = future_date_evidence(df, date_cols)
    backfill = milestone_backfill_evidence(df).set_index("column")

    rows = []
    for col in df.columns:
        group = prof.loc[col, "field_group"]
        rule = _first_rule(col, group)
        role, as_of, use, null_meaning, note = rule.role, rule.as_of, rule.use, rule.null_meaning, rule.note
        evidence = ""

        if col in future.index and future[col] > 0:
            as_of, use = FUTURE, X_LEAK
            evidence = f"{future[col]:.0%} of filled values are after D"
        if col in backfill.index and backfill.loc[col, "positive_before_age"] > 0:
            b = backfill.loc[col]
            evidence = f"positive on {b.positive_before_age} rows before day {b.age_days}"
        no_info = bool(prof.loc[col, "is_all_null"] or prof.loc[col, "is_constant"])
        if no_info and use not in (U_KEY, U_FILTER):
            use = X_NOINFO
            note = "All null" if prof.loc[col, "is_all_null"] else "Single value"

        rows.append({
            "column": col,
            "field_group": group,
            "role": role,
            "as_of": as_of,
            "null_meaning": null_meaning,
            "use": use,
            "model_feature": use.startswith(U_FEATURE),
            "null_share": float(prof.loc[col, "null_share"]),
            "n_unique": int(prof.loc[col, "n_unique"]),
            "rule": rule.name,
            "evidence": evidence,
            "note": note,
        })
    return pd.DataFrame(rows)


def usage_summary(registry: pd.DataFrame) -> pd.DataFrame:
    """Columns per field group by high-level usage."""
    def bucket(use: str) -> str:
        if use.startswith(U_FEATURE):
            return "Model feature"
        if use == U_DERIVE:
            return "Derive feature"
        if use in (U_SEGMENT,):
            return "Segment / reporting"
        if use in (U_KEY, U_FILTER, U_META):
            return "Key, filter, metadata"
        if use in (X_LEAK, X_TARGET, X_UNVERIFIED):
            return "Excluded: leakage / target"
        return "Excluded: no information"

    order = ["Model feature", "Derive feature", "Segment / reporting", "Key, filter, metadata",
             "Excluded: leakage / target", "Excluded: no information"]
    t = pd.crosstab(registry["field_group"], registry["use"].map(bucket)).reindex(columns=order, fill_value=0)
    t["Total"] = t.sum(axis=1)
    t = t.sort_values("Total", ascending=False)
    t.loc["Total"] = t.sum()
    return t


# ------------------------------------------------------------------ brief categories
# The assignment asks to separate: identifiers, dimensions, observed measures,
# derived features, targets, and fields that should be excluded.
IDENTIFIERS = "Identifiers"
DIMENSIONS = "Dimensions"
OBSERVED = "Observed measures"
DERIVED = "Derived features"
TARGETS = "Targets"
EXCLUDED = "Excluded"
CATEGORIES = [IDENTIFIERS, DIMENSIONS, OBSERVED, DERIVED, TARGETS, EXCLUDED]

# Columns we compute (not in the file) and the targets we model.
COMPUTED_COLUMNS = [
    # column, category, role, as_of, null_meaning, use, note
    ("revenue_to_date", DERIVED, SNAPSHOT, END_OF_D, NULL_NONE, U_FEATURE,
     "LIFETIME_REVENUE (start of D) + REVENUE (day D)"),
    ("age_days", DERIVED, SNAPSHOT, END_OF_D, NULL_NONE, U_FEATURE, "D - install date"),
    ("days_since_last_seen", DERIVED, SNAPSHOT, END_OF_D, NULL_NONE, U_FEATURE,
     "D - date of the player's last row on or before D"),
    ("active_on_score_date", DERIVED, SNAPSHOT, END_OF_D, NULL_NONE, U_FEATURE, "Has a row on D"),
    ("n_platforms", DERIVED, MEASURE, END_OF_D, NULL_NONE, U_FEATURE, "Platforms played on day D"),
    ("MAIN_PLATFORM_ID", DERIVED, DIMENSION, END_OF_D, NULL_NONE, U_FEATURE + " + " + U_SEGMENT,
     "Platform with the most sessions on day D"),
    ("install_cohort", DERIVED, DIMENSION, STATIC, NULL_NONE, U_SEGMENT, "Install month"),
    ("revenue_next_30d", TARGETS, LABEL_LIKE, FUTURE, NULL_ZERO, "training label",
     "Revenue from D+1 to D+30; no row = $0 (A1, A2). Only for D at least 30 days before the data end"),
    ("ltv365", TARGETS, LABEL_LIKE, FUTURE, NULL_NONE, "model output",
     "Revenue to date + predicted revenue up to day 365 after install"),
]


def brief_category(row: pd.Series) -> str:
    """Map a registry row onto the six categories the brief names."""
    use, role, col = row["use"], row["role"], row["column"]
    if use == U_KEY:
        return IDENTIFIERS
    if use.startswith("exclude") or use == U_META:
        return EXCLUDED
    if role == DIMENSION or col in ("INSTALL_DATE", "FIRST_INSTALL_DATE") or use == U_FILTER:
        return DIMENSIONS
    return OBSERVED


def with_categories(registry: pd.DataFrame) -> pd.DataFrame:
    """Add the brief's category to every file column and append derived features and targets."""
    reg = registry.copy()
    reg.insert(1, "category", reg.apply(brief_category, axis=1))
    reg.insert(2, "source", "file")
    extra = pd.DataFrame(
        [{"column": c, "category": cat, "source": "computed", "field_group": "Computed", "role": role,
          "as_of": as_of, "null_meaning": nm, "use": use, "model_feature": use.startswith(U_FEATURE),
          "null_share": np.nan, "n_unique": np.nan, "rule": "computed", "evidence": "", "note": note}
         for c, cat, role, as_of, nm, use, note in COMPUTED_COLUMNS]
    )
    return pd.concat([reg, extra], ignore_index=True)


def category_summary(registry_with_categories: pd.DataFrame) -> pd.DataFrame:
    """Column counts per brief category, with examples."""
    g = registry_with_categories.groupby("category")
    out = pd.DataFrame({
        "columns": g.size(),
        "examples": g["column"].apply(lambda s: ", ".join(s.head(5))),
    }).reindex(CATEGORIES)
    return out.reset_index()
