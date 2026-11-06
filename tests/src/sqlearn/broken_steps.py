"""Deliberately broken steps, each failing in one way (see test__diagnose)."""

import duckdb
from duckdb.sqltypes import INTEGER

import sqlearn as sq


class DeclaredStaticNeedsValues(sq.Step):
    """Declared static, yet apply() loops over a learned list."""

    static = True

    def learn(self, x):
        """Learn the distinct values."""
        return {"cities": sq.distinct_values(x)}

    def apply(self, x, learned):
        """Write one column per learned city."""
        return {
            f"city_{c}": (x == sq.fn.const(c)).cast(INTEGER) for c in learned.cities
        }


class BadSql(sq.Step):
    """Applies a function DuckDB does not have."""

    def apply(self, x, learned):
        """Call a function that does not exist."""
        return duckdb.FunctionExpression("no_such_function", x)


class MissingColumn(sq.Step):
    """Applies an expression over a column the data does not have."""

    def apply(self, x, learned):
        """Read a column that is not there."""
        return duckdb.ColumnExpression("no_such_column")


class RaisesInApply(sq.Step):
    """Raises a plain Python error in apply()."""

    def apply(self, x, learned):
        """Fail."""
        msg = "cannot do this"
        raise ValueError(msg)


class FailsWhileRunning(sq.Step):
    """Builds SQL that binds but fails when it runs (a bad cast)."""

    def learn(self, x):
        """Cast text to integers, which fails on the first non-number."""
        return {"total": sq.avg(x.cast(INTEGER))}


class FakeBuiltin(sq.Step):
    """Stands in for a built-in step: its module is a sqlearn module."""

    def apply(self, x, learned):
        """Fail as a built-in step would on a bug."""
        msg = "boom"
        raise RuntimeError(msg)


FakeBuiltin.__module__ = "sqlearn.preprocessing.fake"
