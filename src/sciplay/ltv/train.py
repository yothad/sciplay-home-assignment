"""Train the LTV model in two stages.

1. select:   feature selection + tuning for every candidate model on training folds only.
             Prints the fold comparison; the winner rule (lowest fold deviance; a tie goes to the simpler model)
             is applied in stage 2, so the test set is never used to choose.
2. finalize: fit the chosen model on all training players, bootstrap it, grade every approach once on test, save.

Run: python -m sciplay.ltv.train select
     python -m sciplay.ltv.train finalize [--model glm|lightgbm]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sciplay.config import REPO_ROOT, get_settings
from sciplay.ltv import checks, labels, split
from sciplay.ltv import config as C
from sciplay.ltv import features as F
from sciplay.ltv import learners as L
from sciplay.ltv import model as M
from sciplay.ltv import select as S


@dataclass
class Data:
    pday: pd.DataFrame
    installs: pd.Series
    sets: pd.Series
    lab: pd.DataFrame
    X_raw: pd.DataFrame
    spec: F.FeatureSpec
    data_end: pd.Timestamp


def load_data(processed_dir: Path | None = None, registry_path: Path | None = None) -> Data:
    processed_dir = processed_dir or get_settings().processed_dir
    pday = pd.read_parquet(Path(processed_dir) / "player_day.parquet")
    pday["DATE"] = pd.to_datetime(pday["DATE"])
    registry = pd.read_csv(registry_path or REPO_ROOT / "docs" / "column_registry.csv")
    installs = split.install_dates(pday)
    data_end = pday["DATE"].max()
    sets = split.assign_sets(installs, data_end)
    lab = labels.label_frame(pday, installs, data_end)
    spec = F.build_spec(registry, pday)
    X_raw = F.build_features(pday, installs, spec)
    return Data(pday, installs, sets, lab, X_raw, spec, data_end)


def leakage_checks(d: Data) -> dict:
    rev_cols = [c for c in d.spec.count + d.spec.state + d.spec.average if "REVENUE" in c]
    fut = checks.future_revenue_check(d.pday, d.installs, rev_cols)
    out = {"truncation_ok": bool(checks.truncation_check(d.pday, d.installs, d.spec)),
           "future_revenue_rows_ahead": int(fut["rows_ahead"].sum()),
           "i3_i7_match": checks.install_window_consistency(d.pday, d.installs).set_index("column")["match_share"].round(4).to_dict()}
    if not out["truncation_ok"] or out["future_revenue_rows_ahead"] > 0:
        raise RuntimeError(f"leakage check failed: {out}")
    return out


def matrix(d: Data, encoder: F.CategoryEncoder, ids, columns=None) -> pd.DataFrame:
    X = encoder.transform(d.X_raw.loc[ids].drop(columns="feature_date"))
    return X if columns is None else X.reindex(columns=columns)


SIMPLER_FIRST = ["glm", "lightgbm"]   # tie-break order: the simpler model wins a tie


def _train_matrix(d: Data):
    train_ids = d.sets.index[d.sets == "train"]
    encoder = F.CategoryEncoder(d.spec.categorical).fit(d.X_raw.loc[train_ids])
    Xtr_all = matrix(d, encoder, train_ids)
    candidates, dropped = F.prefilter(Xtr_all, priority=["revenue_first_k", "active_days"])
    return train_ids, encoder, Xtr_all[candidates], dropped


def run_selection(out_root: Path | None = None) -> Path:
    d = load_data()
    leak = leakage_checks(d)
    train_ids, encoder, Xtr, dropped = _train_matrix(d)
    y = d.lab.loc[train_ids, "target_remainder"]
    y30 = d.lab.loc[train_ids, "revenue_first_30d"]
    first_k = d.lab.loc[train_ids, "revenue_first_k"]
    out = (out_root or get_settings().model_dir / "ltv") / "selection"
    out.mkdir(parents=True, exist_ok=True)
    logs, bests, imps = [], [], []
    for key, learner in L.LEARNERS.items():
        log, best, importances = S.run_rounds(learner, Xtr, y, y30, first_k, d.installs)
        best["picked"] = False
        best.loc[best["round"] == S.pick_round(best)["round"], "picked"] = True
        best["key"] = key
        logs.append(log); bests.append(best)
        imps.append(pd.concat({r: v for r, v in importances.items()}, names=["round", "feature"]).assign(model=learner.name))
    pd.concat(logs).to_csv(out / "selection_log.csv", index=False)
    pd.concat(bests).to_json(out / "best_rounds.json", orient="records", indent=2, default_handler=str)
    pd.concat(imps).to_csv(out / "shap_importance.csv")
    dropped.to_csv(out / "prefilter_dropped.csv", index=False)
    (out / "meta.json").write_text(json.dumps({"n_candidates": Xtr.shape[1], "train_players": len(train_ids),
                                               "leakage_checks": leak, "folds": C.FOLDS}, indent=2, default=str))
    return out


def pick_winner(best: pd.DataFrame) -> str:
    """Lowest fold deviance among each model's picked round; within TIE_SHARE, the simpler model wins."""
    picked = best[best["picked"]].set_index("key")
    ok = picked[picked["deviance"] <= picked["deviance"].min() * (1 + C.TIE_SHARE)]
    return next(k for k in SIMPLER_FIRST if k in ok.index)



def scaled_range(pred: np.ndarray, boot: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Range around the forecast: forecast x (bootstrap 25th or 75th percentile / bootstrap median).

    Keeps the bootstrap's relative spread and always contains the forecast (decision: option a).
    """
    q_lo, med, q_hi = np.percentile(boot, [C.PERCENTILES[0], 50, C.PERCENTILES[1]], axis=0)
    safe = np.where(med > 0, med, 1.0)
    lo = np.where(med > 0, pred * q_lo / safe, pred)
    hi = np.where(med > 0, pred * q_hi / safe, pred)
    return np.minimum(lo, pred), np.maximum(hi, pred)


def _final(learner, Xtr, y, row):
    feats = list(row["features"])
    model = learner.fit(Xtr[feats], y, row["setting"], n_estimators=int(row["n_estimators"]) or None)
    return model, feats


def finalize(model_key: str | None = None, out_root: Path | None = None) -> Path:
    root = out_root or get_settings().model_dir / "ltv"
    best = pd.read_json(root / "selection" / "best_rounds.json")
    winner = model_key or pick_winner(best)
    d = load_data()
    leak = leakage_checks(d)
    train_ids, encoder, Xtr, _ = _train_matrix(d)
    test_ids = d.sets.index[d.sets == "test"]
    score_ids = d.sets.index[d.sets.isin(["test", "inference"])]
    y = d.lab.loc[train_ids, "target_remainder"]
    picked = best[best["picked"]].set_index("key")

    # Final fit of every candidate (the winner ships; the others are graded as challengers).
    finals = {k: _final(L.LEARNERS[k], Xtr, y, picked.loc[k]) for k in picked.index}
    w_learner = L.LEARNERS[winner]
    w_model, w_feats = finals[winner]
    w_row = picked.loc[winner]

    # Bootstrap ensemble of the winner: same features, settings and size.
    rng = np.random.default_rng(C.SEED)
    Xscore = matrix(d, encoder, score_ids, w_feats)
    boot_models, boot = [], []
    for b in range(C.N_BOOTSTRAP):
        ids = train_ids[rng.choice(len(train_ids), size=len(train_ids), replace=True)]
        m = w_learner.fit(Xtr.loc[ids, w_feats].reset_index(drop=True), y.loc[ids].reset_index(drop=True),
                          w_row["setting"], n_estimators=int(w_row["n_estimators"]) or None, seed=C.SEED + b + 1)
        boot_models.append(m)
        boot.append(m.predict(Xscore))
    boot = np.vstack(boot)

    first_k = d.lab.loc[score_ids, "revenue_first_k"]
    preds = pd.DataFrame(index=score_ids)
    preds["set"] = d.sets.loc[score_ids]
    preds["revenue_first_k"] = first_k
    rem = w_model.predict(Xscore)
    preds["predicted_ltv_30"] = first_k + rem
    lo, hi = scaled_range(rem, boot)
    preds["ltv_30_low"] = first_k + lo
    preds["ltv_30_high"] = first_k + hi
    preds["confidence"] = np.where(first_k > 0, "High", "Medium")   # rule-based (decision): what the forecast rests on
    for k, (m, feats) in finals.items():
        preds[f"pred_{k}"] = first_k + m.predict(matrix(d, encoder, score_ids, feats))

    # Grade everything once on test.
    y30_tr = d.lab.loc[train_ids, "revenue_first_30d"]
    rule = M.fit_rule(d.lab.loc[train_ids, "revenue_first_k"], y30_tr)
    yte = d.lab.loc[test_ids, "revenue_first_30d"]
    te_first = d.lab.loc[test_ids, "revenue_first_k"]
    cands = {"Baseline: revenue so far": te_first,
             "Baseline: training average": pd.Series(y30_tr.mean(), test_ids),
             "Benchmark: simple rule": M.predict_rule(rule, te_first)}
    for k in picked.index:
        cands[L.LEARNERS[k].name + (" (shipped)" if k == winner else " (challenger)")] = preds.loc[test_ids, f"pred_{k}"]
    rows = []
    for name, p in cands.items():
        r = {"approach": name, **M.metrics(yte, p)}
        r["MAE_low"], r["MAE_high"] = M.bootstrap_range(yte, p, "MAE")
        r["ratio_low"], r["ratio_high"] = M.bootstrap_range(yte, p, "pred_over_actual")
        rows.append(r)
    results = pd.DataFrame(rows)
    preds.loc[test_ids, "actual_ltv_30"] = yte
    bands = M.value_bands(yte, preds.loc[test_ids, "predicted_ltv_30"])
    by_month = preds.loc[test_ids].assign(month=d.installs.loc[test_ids].dt.strftime("%b")).groupby("month", sort=False).agg(
        players=("actual_ltv_30", "size"), payers=("actual_ltv_30", lambda s: int((s > 0).sum())),
        predicted=("predicted_ltv_30", "sum"), actual=("actual_ltv_30", "sum"))
    conf = preds.loc[test_ids].assign(err=lambda t: (t.actual_ltv_30 - t.predicted_ltv_30).abs()).groupby("confidence").agg(
        players=("err", "size"), payers=("actual_ltv_30", lambda s: int((s > 0).sum())), MAE=("err", "mean"),
        predicted=("predicted_ltv_30", "sum"), actual=("actual_ltv_30", "sum"))

    curve = __import__("sciplay.ltv.analysis", fromlist=["revenue_curve"]).revenue_curve(d.pday, d.installs, train_ids)
    fingerprint = hashlib.sha256(",".join(map(str, sorted(train_ids))).encode()).hexdigest()[:8]
    spec_hash = hashlib.sha256(json.dumps({"model": winner, "features": w_feats, "setting": w_row["setting"],
                                           "n": int(w_row["n_estimators"]), "k": C.K, "r": C.R},
                                          sort_keys=True, default=str).encode()).hexdigest()[:8]
    version = f"ltv-d{C.K}-{winner}-{spec_hash}-{fingerprint}"
    out = root / version
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"learner": winner, "model": w_model, "boot": boot_models, "encoder": encoder, "features": w_feats,
                 "setting": w_row["setting"], "n_estimators": int(w_row["n_estimators"]), "rule": rule,
                 "cold_start_value": None, "revenue_curve": curve, "multiplier": C.multiplier(),
                 "challengers": {k: v for k, v in finals.items() if k != winner}}, out / "model.joblib")
    preds.to_parquet(out / "predictions_test_inference.parquet")
    results.to_csv(out / "test_results.csv", index=False)
    bands.to_csv(out / "value_bands.csv")
    by_month.to_csv(out / "test_by_month.csv")
    conf.to_csv(out / "confidence_check.csv")
    meta = {"version": version, "model": w_learner.name, "k": C.K, "multiplier": C.multiplier(), "r": C.R,
            "features": w_feats, "setting": w_row["setting"], "n_estimators": int(w_row["n_estimators"]),
            "selection_round": int(w_row["round"]), "fold_deviance": float(w_row["deviance"]),
            "chosen_by": "rule" if model_key is None else "override", "rule": rule,
            "train_players": len(train_ids), "train_fingerprint": fingerprint, "leakage_checks": leak,
            "data_end": str(d.data_end.date())}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    (root / "active.json").write_text(json.dumps({"version": version}, indent=2))
    return out

if __name__ == "__main__":
    import sys
    stage = sys.argv[1] if len(sys.argv) > 1 else "select"
    if stage == "select":
        path = run_selection()
        best = pd.read_json(path / "best_rounds.json")
        cols = ["model", "round", "n_features", "deviance", "MAE_30d", "pred_over_actual_30d",
                "dollar_recall_30d", "payer_recall_30d", "n_estimators", "picked"]
        print(best[cols].to_string(index=False))
        print("winner by the agreed rule:", pick_winner(best))
    elif stage == "finalize":
        key = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else None
        path = finalize(key)
        print(f"saved {path}")
        print(pd.read_csv(path / "test_results.csv").round(3).to_string(index=False))
