"""LightGBM fitting, the simple-rule benchmark and evaluation metrics."""

from __future__ import annotations

import itertools

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_tweedie_deviance

from sciplay.ltv import config as C

EPS = 1e-6
EVAL_POWER = 1.5   # one fixed Tweedie power for comparing settings


def grid() -> list[dict]:
    keys = list(C.GRID)
    return [dict(zip(keys, v)) for v in itertools.product(*(C.GRID[k] for k in keys))]


def deviance(y, pred, power: float = EVAL_POWER) -> float:
    return float(mean_tweedie_deviance(np.asarray(y, float), np.clip(np.asarray(pred, float), EPS, None), power=power))


class ZeroModel:
    """Stands in when a (bootstrap) training sample has no revenue at all: predicts $0."""
    best_iteration_ = 0
    n_estimators = 0

    def predict(self, X):
        return np.zeros(len(X))


def fit(X: pd.DataFrame, y: pd.Series, setting: dict, n_estimators: int | None = None,
        X_val: pd.DataFrame | None = None, y_val: pd.Series | None = None, seed: int = C.SEED):
    """Fit one LightGBM. With a validation set, stop early; otherwise use `n_estimators`."""
    if float(np.asarray(y).sum()) == 0.0:
        return ZeroModel()
    params = {**C.BASE_PARAMS, **setting, "random_state": seed}
    if n_estimators is not None:
        params["n_estimators"] = n_estimators
    mono = [1 if c == "revenue_first_k" else 0 for c in X.columns]
    model = lgb.LGBMRegressor(**params, monotone_constraints=mono)
    if X_val is not None:
        model.fit(X, y, eval_set=[(X_val, y_val)], eval_metric="tweedie",
                  callbacks=[lgb.early_stopping(C.EARLY_STOPPING, verbose=False)])
    else:
        model.fit(X, y)
    return model


def best_iteration(model: lgb.LGBMRegressor) -> int:
    return int(model.best_iteration_ or model.n_estimators)


# ------------------------------------------------------------------ benchmark

def fit_rule(revenue_first_k: pd.Series, y30: pd.Series) -> dict:
    """Simple rule: early payers -> early spend x multiplier; everyone else -> average 30-day revenue."""
    paid = revenue_first_k > 0
    return {"multiplier": float(y30[paid].sum() / revenue_first_k[paid].sum()),
            "non_payer": float(y30[~paid].mean())}


def predict_rule(rule: dict, revenue_first_k: pd.Series) -> pd.Series:
    return pd.Series(np.where(revenue_first_k > 0, revenue_first_k * rule["multiplier"], rule["non_payer"]),
                     index=revenue_first_k.index)


# ------------------------------------------------------------------ metrics

def metrics(y: pd.Series, pred: pd.Series, flag_at: float = 1.0) -> dict:
    """Dollar metrics on 30-day revenue. `flag_at`: predicted dollars from which a player counts as flagged."""
    y, pred = y.astype(float), pred.astype(float)
    err = (y - pred).abs()
    payers = y > 0
    flagged = pred >= flag_at
    under = (y - pred).clip(lower=0)
    return {
        "MAE": err.mean(),
        "MAE_payers": err[payers].mean(),
        "pred_over_actual": pred.sum() / y.sum(),
        "dollar_recall": y[flagged].sum() / y.sum(),
        "payer_recall": (flagged & payers).sum() / payers.sum(),
        "underprediction_share": under.sum() / y.sum(),
        "flagged_players": int(flagged.sum()),
        "deviance": deviance(y, pred),
    }


def bootstrap_range(y: pd.Series, pred: pd.Series, stat: str = "MAE", n: int = 1000, seed: int = C.SEED,
                    q=(5, 95)) -> tuple[float, float]:
    """Range of a metric when the test players are redrawn with replacement (model fixed)."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(y))
    vals = []
    yv, pv = y.to_numpy(float), pred.to_numpy(float)
    for _ in range(n):
        s = rng.choice(idx, size=len(idx), replace=True)
        ys, ps = pd.Series(yv[s]), pd.Series(pv[s])
        if stat == "MAE":
            vals.append((ys - ps).abs().mean())
        elif stat == "pred_over_actual":
            vals.append(ps.sum() / ys.sum() if ys.sum() > 0 else np.nan)
    return tuple(np.nanpercentile(vals, q))


def value_bands(y: pd.Series, pred: pd.Series, edges=(0, 1, 20, np.inf)) -> pd.DataFrame:
    labels_ = [f"${a:g}–{b:g}" if np.isfinite(b) else f"${a:g}+" for a, b in zip(edges[:-1], edges[1:])]
    band = pd.cut(pred, edges, right=False, labels=labels_)
    t = pd.DataFrame({"y": y, "pred": pred, "band": band}).groupby("band", observed=False).agg(
        players=("y", "size"), payers=("y", lambda s: int((s > 0).sum())),
        predicted_total=("pred", "sum"), actual_total=("y", "sum"))
    t["actual_per_player"] = t["actual_total"] / t["players"].replace(0, np.nan)
    return t.round(2)
