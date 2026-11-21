"""Four value states, shown differently everywhere (brief, Part 2).

ZERO      measured, and it was 0                     -> "0" / "$0"
MISSING   should exist but does not                  -> "— missing"
NOT_YET   cannot be known yet (too young, not built)  -> "not yet available"
NA        does not apply to this player or metric     -> "n/a"
"""

from __future__ import annotations

import math
from enum import Enum


class State(str, Enum):
    VALUE = "value"
    ZERO = "zero"
    MISSING = "missing"
    NOT_YET = "not yet available"
    NA = "not applicable"


STYLE = {  # text colour and decoration for HTML
    State.VALUE: "color:#1A1423",
    State.ZERO: "color:#1A1423",
    State.MISSING: "color:#8A8496",
    State.NOT_YET: "color:#6B3FA0;font-style:italic",
    State.NA: "color:#8A8496;font-style:italic",
}

LEGEND = [
    (State.ZERO, "0", "Measured, and it was zero"),
    (State.MISSING, "— missing", "Should exist but is not in the data"),
    (State.NOT_YET, "not yet available", "Cannot be known yet (too young, or built in a later part)"),
    (State.NA, "n/a", "Does not apply"),
]


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def classify(value, applicable: bool = True, available: bool = True) -> State:
    """Decide the state of a value. `applicable` and `available` come from the caller's logic."""
    if not applicable:
        return State.NA
    if not available:
        return State.NOT_YET
    if _is_blank(value):
        return State.MISSING
    if isinstance(value, str):
        return State.VALUE
    if value == 0:
        return State.ZERO
    return State.VALUE


def fmt(value, unit: str = "count", state: State | None = None, decimals: int | None = None,
        short: bool = False) -> str:
    """Format a value for display; non-values get their state's label."""
    state = state or classify(value)
    if state == State.MISSING:
        return "— missing"
    if state == State.NOT_YET:
        return "not yet" if short else "not yet available"
    if state == State.NA:
        return "n/a"
    if isinstance(value, str):
        return value
    if unit == "money":
        d = 2 if decimals is None else decimals
        return f"${value:,.{d}f}"
    if unit == "pct":
        d = 1 if decimals is None else decimals
        return f"{value * 100:.{d}f}%"
    d = 0 if decimals is None else decimals
    return f"{value:,.{d}f}"


def html(value, unit: str = "count", state: State | None = None, decimals: int | None = None) -> str:
    state = state or classify(value)
    return f'<span style="{STYLE[state]}">{fmt(value, unit, state, decimals)}</span>'
