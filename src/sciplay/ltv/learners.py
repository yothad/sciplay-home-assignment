"""The two candidate models behind one interface, so selection, SHAP and scoring are shared."""

from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd
import shap
from sklearn.linear_model import TweedieRegressor

from sciplay.ltv import config as C
from sciplay.ltv import model as M


class LightGBMLearner:
    name = "LightGBM"
    key = "lightgbm"

    def grid(self) -> list[dict]:
        return M.grid()

    def fit(self, X, y, setting, X_val=None, y_val=None, n_estimators=None, seed=C.SEED):
        return M.fit(X, y, setting, n_estimators=n_estimators, X_val=X_val, y_val=y_val, seed=seed)

    def size(self, model) -> int:
        return M.best_iteration(model)

    def shap_values(self, model, X: pd.DataFrame) -> np.ndarray:
        """Contributions in the model's raw (log) space."""
        if isinstance(model, M.ZeroModel):
            return np.zeros(X.shape)
        return shap.TreeExplainer(model).shap_values(X)


class GLMModel:
    """Median imputation + log1p + standardisation, then a log-link Tweedie GLM with an L2 penalty."""

    def __init__(self, power: float, alpha: float):
        self.power, self.alpha = power, alpha

    def _base(self, X: pd.DataFrame) -> pd.DataFrame:
        Z = X.fillna(self.median_).astype(float)
        Z[self.log_cols_] = np.log1p(Z[self.log_cols_].clip(lower=0))
        return Z

    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return (self._base(X) - self.mean_) / self.std_

    def fit(self, X: pd.DataFrame, y):
        self.columns_ = list(X.columns)
        self.median_ = X.median().fillna(0)
        self.log_cols_ = [c for c in X.columns if X[c].max() > 10 and X[c].min() >= 0]
        Z0 = self._base(X)
        self.mean_, self.std_ = Z0.mean(), Z0.std().replace(0, 1).fillna(1)
        self.glm_ = TweedieRegressor(power=self.power, alpha=self.alpha, link="log", max_iter=3000)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.glm_.fit(self._transform(X), np.asarray(y, float))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.glm_.predict(self._transform(X[self.columns_]))

    def contributions(self, X: pd.DataFrame) -> np.ndarray:
        """Linear SHAP in log space: coefficient x (standardised value - training mean of 0)."""
        return self._transform(X[self.columns_]).to_numpy() * self.glm_.coef_


class GLMLearner:
    name = "Tweedie GLM"
    key = "glm"

    def grid(self) -> list[dict]:
        return [{"tweedie_variance_power": p, "alpha": a}
                for p, a in itertools.product([1.2, 1.5], [0.01, 0.1, 1.0, 10.0])]

    def fit(self, X, y, setting, X_val=None, y_val=None, n_estimators=None, seed=C.SEED):
        if float(np.asarray(y).sum()) == 0.0:
            return M.ZeroModel()
        return GLMModel(setting["tweedie_variance_power"], setting["alpha"]).fit(X, y)

    def size(self, model) -> int:
        return 0

    def shap_values(self, model, X: pd.DataFrame) -> np.ndarray:
        if isinstance(model, M.ZeroModel):
            return np.zeros(X.shape)
        return model.contributions(X)


LEARNERS = {"lightgbm": LightGBMLearner(), "glm": GLMLearner()}
