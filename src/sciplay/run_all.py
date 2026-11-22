"""One command: prepare data -> load (or train) the LTV model -> score LTV -> daily lists -> [delivery] -> [app].

    uv run python -m sciplay.run_all              # everything except delivery; prints how to start the app
    uv run python -m sciplay.run_all --app        # ... and starts the dashboard
    uv run python -m sciplay.run_all --deliver    # ... and replays the hourly delivery (resets the delivery tables)
    uv run python -m sciplay.run_all --retrain    # train the LTV model again instead of loading the shipped one

Every step prints one line; the run stops at the first failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import warnings

import pandas as pd

from sciplay.config import REPO_ROOT, get_settings


def _step(name: str, fn):
    t = time.time()
    try:
        msg = fn()
    except Exception as exc:  # noqa: BLE001 -- report and stop
        print(f"FAILED  {name}: {exc}")
        sys.exit(1)
    print(f"ok      {name} ({time.time() - t:.0f}s){': ' + msg if msg else ''}")


def prepare() -> str:
    from sciplay.pipeline import refresh as R
    raw = get_settings().raw_data_path
    if not raw.exists():
        raise FileNotFoundError(f"put the sample CSV at {raw} (or set RAW_DATA_PATH in .env)")
    res = R.refresh(ltv=False)
    if res.status == "published":
        return f"data through {res.data_end}"
    if res.exit_code == 2:                               # nothing newer than what is published
        return f"already prepared, data through {res.previous_data_end}"
    raise RuntimeError(res.message)


def model(retrain: bool) -> str:
    from sciplay.ltv import train as T
    active = get_settings().model_dir / "ltv" / "active.json"
    if active.exists() and not retrain:
        return f"loaded {pd.read_json(active, typ='series')['version']}"
    T.run_selection()
    path = T.finalize()
    return f"trained {path.name}"


def score_dates() -> pd.DatetimeIndex:
    from sciplay.ltv import config as LC
    from sciplay.ltv import train as T
    first = pd.Timestamp(LC.TEST[1]) + pd.Timedelta(days=LC.K)        # first inference player's day 3
    return pd.date_range(first, T.load_data().data_end, freq="D")


def score() -> str:
    from sciplay.ltv import score as S
    from sciplay.ltv import train as T
    data, dates = T.load_data(), score_dates()
    for d in dates:
        S.score(d, data)
    return f"{len(dates)} dates, {dates[0].date()} to {dates[-1].date()}"


def lists() -> str:
    from sciplay.lists import run as LR
    from sciplay.ltv import train as T
    data, dates = T.load_data(), score_dates()
    last = None
    for d in dates:
        last = LR.run(d, data)
    return f"{len(dates)} dates; {dates[-1].date()}: {last['list_sizes']}"


def deliver() -> str:
    from sciplay.delivery import simulate
    log, acts = simulate.main()
    sent = sum(len(r.get("sent", [])) for r in log)
    return f"{len(log)} hourly runs, {sent} messages, {len(acts)} simulated actions -> data/store/outbox/"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prepare data, load or train the model, score, build lists, start the app.")
    ap.add_argument("--retrain", action="store_true", help="train the LTV model instead of loading the shipped one")
    ap.add_argument("--deliver", action="store_true", help="replay hourly delivery 3-5 Nov (resets delivery tables)")
    ap.add_argument("--app", action="store_true", help="start the dashboard at the end")
    a = ap.parse_args(argv)
    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)   # pandas noise, not a problem
    t = time.time()
    _step("prepare data", prepare)
    _step("LTV model", lambda: model(a.retrain))
    _step("score LTV", score)
    _step("daily lists", lists)
    if a.deliver:
        _step("delivery (hourly replay)", deliver)
    print(f"done in {time.time() - t:.0f}s")
    app = [sys.executable, "-m", "streamlit", "run", str(REPO_ROOT / "app" / "Overview.py")]
    if a.app:
        return subprocess.call(app, cwd=REPO_ROOT)
    print("start the dashboard: uv run streamlit run app/Overview.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
