"""Each kind of step, then a step choosing its columns by type: nothing skipped.

Every kind of step a pipeline plans (static, dynamic, dynamic keeping its
inputs, whole-row, learning from the target) is followed by a step choosing
its columns by type, alone or with a static step between them in the same
run. Each learns, applies, trains and predicts, and the step choosing by type
works on every column of its type that reaches it, as the steps before it
applied give them.
"""

import numpy as np
import pandas as pd
import pytest

import sqlearn as sq
from sqlearn._selectors import _is_numeric, is_text

FIRST = {
    "static": lambda: sq.scale.standard("age"),
    "dynamic": lambda: sq.encode.onehot("city"),
    "keeping": lambda: sq.impute.indicator("age", "city"),
    "normalize": lambda: sq.scale.normalize("income", "score"),
    "polynomial": lambda: sq.features.polynomial("age", "income"),
    "target": lambda: sq.encode.target("plan"),
}

BY_TYPE = {
    "ordinal": (sq.encode.ordinal, is_text),
    "lower": (sq.transform.lower, is_text),
    "robust": (sq.scale.robust, _is_numeric),
}

BETWEEN = {
    "alone": [],
    "after a static step": [lambda: sq.scale.minmax("score")],
}


class _Echo:
    """A model of anything: it remembers what it was given, predicts zeros."""

    def fit(self, x, y):
        """Remember the shape of what was handed over."""
        self.shape_ = x.shape
        return self

    def predict(self, x):
        """Predict 0 for every row."""
        return np.zeros(len(x))


def _frame():
    """Return numbers with a gap, two texts (one with a gap), a 0/1 target."""
    return pd.DataFrame(
        {
            "age": [30.0, np.nan, 50.0, 40.0, 20.0, 35.0] * 4,
            "income": [1.0, 2.0, 3.0, 4.0, 10.0, 6.0] * 4,
            "score": [5.0, 1.0, 2.0, 8.0, 3.0, 4.0] * 4,
            "city": ["Oslo", None, "Rome", "oslo", "Lima", "Rome"] * 4,
            "plan": ["a", "b", "c", "a", "b", "a"] * 4,
            "y": [0, 1, 0, 1, 1, 0] * 4,
        }
    )


@pytest.mark.parametrize("between", BETWEEN)
@pytest.mark.parametrize("by_type", BY_TYPE)
@pytest.mark.parametrize("first", FIRST)
def test_a_step_by_type_after_each_kind_of_step(first, by_type, between):
    """Learn, apply and train agree, and the step by type skips no column."""
    frame = _frame()
    make, kind = BY_TYPE[by_type]
    before = [FIRST[first](), *(step() for step in BETWEEN[between])]
    steps = [*before, make()]
    pipe = sq.Pipeline(steps).learn(frame, target="y")
    applied = pipe.apply(frame)
    assert applied.columns == pipe.columns_out_
    assert len(applied.fetchall()) == len(frame)
    reaching = sq.Pipeline(before).learn(frame, target="y").apply(frame)
    chosen = [
        c for c, t in zip(reaching.columns, reaching.types, strict=True) if kind(t)
    ]
    assert pipe._entries is not None
    assert pipe._entries[-1].columns == chosen
    # A model is handed numbers only: any text left is encoded first.
    encode = [] if by_type == "ordinal" else [sq.encode.ordinal()]
    model = sq.Pipeline([*steps, *encode, _Echo()]).train(frame, target="y")
    assert model["model"].shape_ == (len(frame), len(pipe.columns_out_))
    assert len(model.predict(frame, out="numpy")["prediction"]) == len(frame)
