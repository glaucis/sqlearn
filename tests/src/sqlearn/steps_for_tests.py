"""Small steps shared by the tests of several modules."""

from dataclasses import dataclass

from duckdb.sqltypes import INTEGER

import sqlearn as sq
from sqlearn._selectors import Selector


class MyScale(sq.Step):
    """Centre and scale numeric columns (undeclared: classified as static)."""

    def __init__(self, cols=sq.cols.numeric(), keep=False, suffix=None):  # noqa: B008
        """Set the settings."""
        self.cols, self.keep, self.suffix = cols, keep, suffix

    def learn(self, x):
        """Learn what the step needs."""
        return {"mean": sq.agg.mean(x), "scale": sq.agg.std(x)}

    def apply(self, x, learned):
        """Apply what was learned."""
        return (x - learned.mean) / learned.scale


class MyEncoder(sq.Step):
    """One-hot encode text columns (undeclared: classified as dynamic)."""

    def __init__(self, cols=("city",), keep=False, suffix=None):
        """Set the settings."""
        self.cols, self.keep, self.suffix = cols, keep, suffix

    def learn(self, x):
        """Learn what the step needs."""
        return {"cities": sq.agg.distinct(x)}

    def apply(self, x, learned):
        """Apply what was learned."""
        return {c: (x == sq.fn.const(c)).cast(INTEGER) for c in learned.cities}


@dataclass(frozen=True, repr=False)
class Prefix(Selector):
    """Choose the columns whose name starts with a prefix (``x_*``)."""

    prefix: str

    def _matches(self, name, dtype):
        return name.startswith(self.prefix)

    def _may(self, dtype):
        return True

    def _must(self, dtype):
        return False


def static_step(cols, keep=False, suffix=None, changes_rows=False):
    """Return a step declared static, working on `cols`."""
    kind = type("Static", (sq.Step,), {"static": True, "changes_rows": changes_rows})
    return kind(cols=cols, keep=keep, suffix=suffix)


def dynamic_step(cols, creates=INTEGER, keep=False):
    """Return a step declared dynamic that creates columns of type `creates`."""
    kind = type("Dynamic", (sq.Step,), {"static": False, "creates": creates})
    return kind(cols=cols, keep=keep)


class GramCovariance(sq.Step):
    """Learn the covariance of its inputs from their Gram matrix (a Gram step)."""

    gram = True
    dynamic = True
    rowwise = True

    def __init__(self, cols=sq.cols.numeric()):  # noqa: B008
        """Set the settings."""
        self.cols, self.keep, self.suffix = cols, False, None

    def learn(self, x):
        """Learn the mean and count the core centres the rows with."""
        return {"mean": sq.agg.mean(x), "count": sq.agg.count(x)}

    def learned_from_gram(self, gram, learned):
        """Return the sample covariance of every input with every other."""
        columns = list(learned["count"])
        rows = learned["count"][columns[0]]
        return {
            "covariance": {
                c: (gram[j] / (rows - 1)).tolist() for j, c in enumerate(columns)
            }
        }

    def apply_row(self, xs, learned, values):
        """Write each input's covariance with the first input."""
        return {c: sq.fn.const(learned[c].covariance[0]) for c in xs}
