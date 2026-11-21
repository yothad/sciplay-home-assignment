"""The four value states look different (brief, Part 2)."""

import math

from sciplay.viz.formatting import State, classify, fmt


def test_states_are_classified():
    assert classify(0) == State.ZERO
    assert classify(math.nan) == State.MISSING
    assert classify(None) == State.MISSING
    assert classify(5, available=False) == State.NOT_YET
    assert classify(5, applicable=False) == State.NA
    assert classify(3) == State.VALUE


def test_states_render_differently():
    shown = {fmt(0, "money"), fmt(math.nan), fmt(1, state=State.NOT_YET), fmt(1, state=State.NA)}
    assert shown == {"$0.00", "— missing", "not yet available", "n/a"}


def test_units():
    assert fmt(1234.5, "money") == "$1,234.50"
    assert fmt(0.123, "pct") == "12.3%"
    assert fmt(42) == "42"
