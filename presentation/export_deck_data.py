"""Export the numbers and chart series used in the results deck to presentation/deck_data.json."""

import json
from pathlib import Path

import pandas as pd

from sciplay.audit import checks as audit
from sciplay.config import get_settings
from sciplay.data.loader import load_raw


def main() -> None:
    df = load_raw(get_settings().raw_data_path)
    end = df["DATE"].max()
    players = audit.player_summary(df)

    # weekly average daily active players by install cohort
    act = audit.active_players_by_cohort(df)
    act["week"] = act["DATE"].dt.to_period("W-SUN").dt.start_time
    weekly = (act.groupby(["week", "install_cohort"])["players"].sum()
              / act.groupby("week")["DATE"].nunique()).unstack(fill_value=0).round(1)

    rpp = audit.rows_per_player_distribution(players)
    matrix = audit.cohort_activity_matrix(df, end)
    heat = matrix.pivot(index="install_cohort", columns="age_bucket", values="active_share")[audit.AGE_LABELS]
    lag = audit.late_updates(df)
    d365 = audit.check_d365_label(df)
    offset = audit.check_revenue_offset(df)
    prof = audit.column_profile(df)

    data = {
        "kpis": {
            "rows": len(df), "columns": df.shape[1], "players": int(df["PLAYER_ID"].nunique()),
            "first_date": str(df["DATE"].min().date()), "last_date": str(end.date()),
            "days": int(df["DATE"].nunique()), "max_age": int(df["DAYS_SINCE_INSTALL"].max()),
            "payers": int(players["ever_payer"].sum()),
            "one_row_players": int(players["rows"].eq(1).sum()),
            "median_rows": float(players["rows"].median()),
            "dead_columns": int((prof["is_all_null"] | prof["is_constant"]).sum()),
            "all_null": int(prof["is_all_null"].sum()), "constant": int(prof["is_constant"].sum()),
            "multi_platform_player_days": int(df.duplicated(["DATE", "PLAYER_ID"]).sum()),
        },
        "weekly_active": {
            "weeks": [w.strftime("%d %b") for w in weekly.index],
            "series": {c: weekly[c].tolist() for c in weekly.columns},
        },
        "rows_per_player": {"labels": rpp["rows_per_player"].astype(str).tolist(), "players": rpp["players"].astype(int).tolist()},
        "heatmap": {"cohorts": heat.index.tolist(), "buckets": audit.AGE_LABELS,
                    "values": [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in heat.values]},
        "update_lag": {"months": lag["data_month"].tolist(), "median_lag": lag["median_lag"].astype(float).tolist()},
        "d365": d365, "offset": offset,
    }
    out = Path(__file__).with_name("deck_data.json")
    out.write_text(json.dumps(data, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
