"""Feature selection + tuning on forward folds inside the training period (the test set is not used).

Model-agnostic: the same rounds, folds and scoring for every learner in `learners.LEARNERS`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sciplay.ltv import config as C
from sciplay.ltv import model as M


def fold_ids(installs: pd.Series, train_ids: pd.Index):
    inst = installs.reindex(train_ids)
    out = []
    for (fa, fb), (va, vb) in C.FOLDS:
        out.append((inst.index[inst.between(pd.Timestamp(fa), pd.Timestamp(fb))],
                    inst.index[inst.between(pd.Timestamp(va), pd.Timestamp(vb))]))
    return out


def evaluate_setting(learner, X, y, y30, first_k, folds, setting):
    """Fit on each fold, pool validation predictions. Metrics on the remainder and on the 30-day forecast."""
    preds, models, sizes = [], [], []
    for fit_ids, val_ids in folds:
        m = learner.fit(X.loc[fit_ids], y.loc[fit_ids], setting, X_val=X.loc[val_ids], y_val=y.loc[val_ids])
        preds.append(pd.Series(m.predict(X.loc[val_ids]), index=val_ids))
        models.append(m)
        sizes.append(learner.size(m))
    p = pd.concat(preds)
    m30 = M.metrics(y30.loc[p.index], first_k.loc[p.index] + p)
    res = {"deviance": M.deviance(y.loc[p.index], p), "MAE_30d": m30["MAE"],
           "pred_over_actual_30d": m30["pred_over_actual"], "dollar_recall_30d": m30["dollar_recall"],
           "payer_recall_30d": m30["payer_recall"]}
    return res, models, sizes


def importance(learner, models, X, folds) -> pd.DataFrame:
    """Mean |SHAP| per feature on each fold's validation players."""
    cols = {}
    for i, (m, (_, val_ids)) in enumerate(zip(models, folds)):
        cols[f"fold{i + 1}"] = np.abs(learner.shap_values(m, X.loc[val_ids])).mean(axis=0)
    imp = pd.DataFrame(cols, index=X.columns)
    imp["mean_abs_shap"] = imp.mean(axis=1)
    imp["used_in_all_folds"] = (imp[[c for c in imp if c.startswith("fold")]] > 1e-9).all(axis=1)
    return imp.sort_values("mean_abs_shap", ascending=False)


def run_rounds(learner, X, y, y30, first_k, installs, always=("revenue_first_k",)):
    """All rounds for one learner. Returns the full log, the best row per round, and importances."""
    folds = fold_ids(installs, X.index)
    features = list(X.columns)
    log, best_rows, importances = [], [], {}
    for rnd, size in enumerate(C.SELECTION_SIZES, start=1):
        if size is not None:
            prev = importances[rnd - 1]
            ranked = prev[prev["used_in_all_folds"]].index.tolist()
            keep = [f for f in always if f in features] + [f for f in ranked if f not in always]
            features = keep[:size]
        best = None
        for setting in learner.grid():
            res, models, sizes = evaluate_setting(learner, X[features], y, y30, first_k, folds, setting)
            row = {"model": learner.name, "round": rnd, "n_features": len(features), "setting": setting,
                   **res, "n_estimators": int(np.mean(sizes)) if sizes else 0}
            log.append(row)
            if best is None or res["deviance"] < best[0]["deviance"]:
                best = (row, models)
        importances[rnd] = importance(learner, best[1], X[features], folds)
        best_rows.append({**best[0], "features": list(features)})
    return pd.DataFrame(log), pd.DataFrame(best_rows), importances


def pick_round(best_rows: pd.DataFrame) -> pd.Series:
    """Lowest deviance; within TIE_SHARE of it, the round with fewer features wins."""
    ok = best_rows[best_rows["deviance"] <= best_rows["deviance"].min() * (1 + C.TIE_SHARE)]
    return ok.sort_values(["n_features", "deviance"]).iloc[0]
