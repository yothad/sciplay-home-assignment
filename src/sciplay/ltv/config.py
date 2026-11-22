"""Every LTV choice in one place. Values marked "assumption" are not estimated from the data."""

from __future__ import annotations

K = 3                      # feature window: days 0..K-1 after install (feature date = install + K - 1)
HORIZON = 30               # label: gross revenue on days 0..HORIZON-1 after install

# Split by install date; every player belongs to exactly one set.
TRAIN = ("2026-05-01", "2026-07-31")
TEST = ("2026-08-01", "2026-10-06")
# Inference = installed after TEST and at least K days of data by the data end.
# Younger players are cold start (new-player average).

# Day-365 extension: each later 30-day block is worth R x the block before (assumption).
R = 0.6
BLOCKS = 12
SENSITIVITY_R = (0.5, 0.7)


def multiplier(r: float = R, blocks: int = BLOCKS) -> float:
    """1 + r + r^2 + ... + r^(blocks-1)."""
    return float(sum(r ** i for i in range(blocks)))


CHURN_DAYS = 30            # A12: no row for 30+ days = churned (update rule sets the remainder to $0)

# Uncertainty: bootstrap ensemble of the final model.
N_BOOTSTRAP = 50
PERCENTILES = (25, 75)     # interquartile range
CONFIDENCE_HIGH = 0.5      # relative width = IQR / max(forecast, $1)
CONFIDENCE_LOW = 1.5
CONFIDENCE_FLOOR = 1.0     # dollars

SEED = 42

# Feature selection + tuning on forward folds inside the training period.
FOLDS = [
    (("2026-05-01", "2026-05-31"), ("2026-06-01", "2026-06-30")),
    (("2026-05-01", "2026-06-30"), ("2026-07-01", "2026-07-31")),
]
SELECTION_SIZES = (None, 50, 20, 10)   # None = all candidates
GRID = {
    "num_leaves": [4, 8],
    "min_child_samples": [20, 40],
    "tweedie_variance_power": [1.2, 1.5],
}
BASE_PARAMS = dict(
    objective="tweedie", learning_rate=0.05, n_estimators=400, colsample_bytree=0.8,
    reg_lambda=1.0, deterministic=True, force_row_wise=True, n_jobs=1, verbose=-1,
    random_state=SEED,
)
EARLY_STOPPING = 50
TIE_SHARE = 0.05           # used when no bootstrap range is available

# Feature building.
MIN_NONZERO_PLAYERS = 3    # drop a feature non-zero for fewer training players
CORR_MAX = 0.95
MIN_CATEGORY_PLAYERS = 20  # rarer category levels become "Other"
