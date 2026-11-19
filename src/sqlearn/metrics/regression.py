"""Regression metrics, each one aggregate query.

The metrics are rmse, mae, r2, mse, max_error, median_absolute_error,
mape, explained_variance, msle, rmsle, and the deviances tweedie_deviance,
poisson_deviance and gamma_deviance.
"""

import math
from dataclasses import dataclass, replace
from numbers import Real

import duckdb
from duckdb import Expression

from sqlearn._errors import SqlearnError
from sqlearn._expr import const
from sqlearn.metrics.accuracy import Metric

__all__ = [
    "LogError",
    "TweedieDeviance",
    "explained_variance",
    "gamma_deviance",
    "mae",
    "mape",
    "max_error",
    "median_absolute_error",
    "mse",
    "msle",
    "poisson_deviance",
    "r2",
    "rmse",
    "rmsle",
    "tweedie_deviance",
]


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _error(y: Expression, p: Expression) -> Expression:
    return y.cast("DOUBLE") - p.cast("DOUBLE")


def _rmse(y: Expression, p: Expression) -> Expression:
    error = _error(y, p)
    return _fn("sqrt", _fn("favg", error * error))


def _mae(y: Expression, p: Expression) -> Expression:
    return _fn("favg", _fn("abs", _error(y, p)))


def _mse(y: Expression, p: Expression) -> Expression:
    error = _error(y, p)
    return _fn("favg", error * error)


def _max_error(y: Expression, p: Expression) -> Expression:
    return _fn("max", _fn("abs", _error(y, p)))


def _median_absolute_error(y: Expression, p: Expression) -> Expression:
    return _fn("median", _fn("abs", _error(y, p)))


# numpy's ``finfo(float).eps``: scikit-learn divides by at least this, so a
# zero target gives a huge number rather than an error.
_EPSILON = 2.220446049250313e-16


def _mape(y: Expression, p: Expression) -> Expression:
    denominator = _fn("greatest", _fn("abs", y.cast("DOUBLE")), const(_EPSILON))
    return _fn("favg", _fn("abs", _error(y, p)) / denominator)


def _r2(y: Expression, p: Expression) -> Expression:
    # One minus the residual over the total sum of squares.
    #
    # The residual sum is compensated (``fsum``, ADR 0033). The total sum is
    # DuckDB's population variance (a running update about the mean, not
    # compensated) times the count; a sum of squares minus a squared sum would
    # cancel for a target far from zero. A constant target scores 1 when
    # predicted exactly and 0 otherwise, as scikit-learn's r2_score has it.
    error = _error(y, p)
    residual = _fn("fsum", error * error)
    total = _fn("var_pop", y.cast("DOUBLE")) * _fn("count", y)
    constant = duckdb.CaseExpression(residual == const(0.0), const(1.0)).otherwise(
        const(0.0)
    )
    return duckdb.CaseExpression(total == const(0.0), constant).otherwise(
        const(1.0) - residual / total
    )


def _ev(y: Expression, p: Expression) -> Expression:
    # One minus the error's variance over the target's variance, both
    # DuckDB's population variance (as ``_r2`` explains for the target; the
    # error's is the same kind of running update about its mean, so an offset
    # in the errors costs no digits). A constant target (minimum equals
    # maximum, exact where a variance can be one rounding off) scores 1 when
    # the error's variance is 0 and 0 otherwise, as scikit-learn's
    # explained_variance_score has it.
    target = y.cast("DOUBLE")
    numerator = _fn("var_pop", _error(y, p))
    denominator = _fn("var_pop", target)
    constant = duckdb.CaseExpression(numerator == const(0.0), const(1.0)).otherwise(
        const(0.0)
    )
    return duckdb.CaseExpression(
        _fn("min", target) == _fn("max", target), constant
    ).otherwise(const(1.0) - numerator / denominator)


def _log1p(x: Expression) -> Expression:
    # Kahan's log1p, which DuckDB lacks: ln(1 + x) loses every digit of a
    # small x, so scale ln(u) by x / (u - 1), where the rounding of u = 1 + x
    # cancels. NaN or -inf (not an error) at or below -1, where a metric
    # refuses the row after the aggregate.
    u = const(1.0) + x
    return duckdb.CaseExpression(u == const(1.0), x).otherwise(
        _fn("ln", u) * x / (u - const(1.0))
    )


def _log_error(y: Expression, p: Expression) -> Expression:
    return _log1p(y.cast("DOUBLE")) - _log1p(p.cast("DOUBLE"))


def _msle(y: Expression, p: Expression) -> Expression:
    error = _log_error(y, p)
    return _fn("favg", error * error)


def _rmsle(y: Expression, p: Expression) -> Expression:
    return _fn("sqrt", _msle(y, p))


@dataclass(frozen=True)
class LogError(Metric):
    """A metric on the logarithm of 1 plus each value (msle, rmsle).

    It refuses a target or a prediction at or below -1, where that
    logarithm is undefined, as scikit-learn does.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.rmsle.greater_is_better
    False
    """

    def _outside(
        self, y: Expression, p: Expression
    ) -> list[tuple[Expression, str, str]]:
        limit = const(-1.0)
        why = (
            "the logarithm of 1 plus a value is undefined at or below -1, "
            "and scikit-learn refuses such values too."
        )
        return [
            (y.cast("DOUBLE") <= limit, "a target at or below -1", why),
            (p.cast("DOUBLE") <= limit, "a prediction at or below -1", why),
        ]


def _unused(*_: Expression) -> Expression:
    # The aggregate of a metric that builds its own in __post_init__.
    raise NotImplementedError


def _positive(x: Expression) -> Expression:
    # x where it is above 0, else 1: a pow or ln of it cannot raise. A row
    # where it did not hold is refused after the aggregate.
    return duckdb.CaseExpression(x > const(0.0), x).otherwise(const(1.0))


@dataclass(frozen=True)
class TweedieDeviance(Metric):
    """The mean Tweedie deviance, as scikit-learn's ``mean_tweedie_deviance``.

    Power 0 is the squared error, 1 the Poisson deviance, 2 the gamma
    deviance. The rows refused follow scikit-learn: for a power below 0 a
    prediction at or below 0; for 0 none; for 1 up to 2 a negative target or
    a prediction at or below 0; for 2 and above a target or a prediction at
    or below 0.

    Attributes
    ----------
    power : float, default 0.0
        The power: at most 0 or at least 1.
    d2 : bool, default False
        Reserved for the D2 score; not a setting here.
    settable : bool, default True
        Whether the power can be set by a call.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.tweedie_deviance(power=1.5)
    tweedie_deviance(power=1.5)
    >>> sq.metrics.poisson_deviance.greater_is_better
    False
    """

    power: float = 0.0
    d2: bool = False
    settable: bool = True

    def __post_init__(self) -> None:
        """Set the aggregate, which reads this metric's power."""
        object.__setattr__(self, "expression", self._expression)

    def __call__(self, **settings: object) -> "TweedieDeviance":
        """Return a copy with the given power.

        Parameters
        ----------
        **settings : object
            ``power``: at most 0 or at least 1.

        Returns
        -------
        TweedieDeviance
            The configured copy.

        Raises
        ------
        SqlearnError
            If this deviance has a fixed power, a setting is not ``power``,
            or the power is not a finite number at most 0 or at least 1.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.tweedie_deviance(power=2)
        tweedie_deviance(power=2.0)
        """
        if not self.settable:
            super().__call__(**settings)  # always raises: no settings here
            raise AssertionError("unreachable")  # pragma: no cover
        unknown = [k for k in settings if k != "power"]
        if unknown:
            msg = (
                f"{self.name} has no setting {unknown[0]}=. Why: its only "
                "setting is power. Fix: use power=, or "
                f"sq.metrics.{self.name} as it is."
            )
            raise SqlearnError(msg)
        power = settings.get("power", self.power)
        if (
            isinstance(power, bool)
            or not isinstance(power, Real)
            or not math.isfinite(float(power))
            or 0 < float(power) < 1
        ):
            msg = (
                f"{self.name} was given power={power!r}. Why: it takes a "
                "finite number at most 0 or at least 1, as scikit-learn's "
                "mean_tweedie_deviance. Fix: use such a power, for example "
                "power=1.5."
            )
            raise SqlearnError(msg)
        return replace(self, power=float(power))

    def __repr__(self) -> str:
        """Return the name, with the power when it is set."""
        if self.settable and self.power != 0.0:
            return f"{self.name}(power={self.power!r})"
        return self.name

    def _expression(self, y: Expression, p: Expression) -> Expression:
        # scikit-learn's per-row deviance, then the compensated mean (favg,
        # ADR 0033). A pow or ln is guarded so that a row outside the range
        # gives a number and the refusal comes after the aggregate.
        power = self.power
        target, mu = y.cast("DOUBLE"), p.cast("DOUBLE")
        if power == 0.0:
            error = target - mu
            return _fn("favg", error * error)
        mu = _positive(mu)
        if power == 1.0:
            # xlogy(y, y / mu): 0 where y is 0.
            ratio = _fn("ln", _positive(target / mu))
            xlogy = duckdb.CaseExpression(target == const(0.0), const(0.0)).otherwise(
                target * ratio
            )
            row = const(2.0) * (xlogy - target + mu)
        elif power == 2.0:
            positive = _positive(target)
            row = const(2.0) * (_fn("ln", mu / positive) + positive / mu - const(1.0))
        else:
            row = self._general(target, mu, power)
        return _fn("favg", row)

    @staticmethod
    def _general(target: Expression, mu: Expression, power: float) -> Expression:
        # 2 * (max(y, 0)^(2-p) / ((1-p)(2-p)) - y mu^(1-p) / (1-p)
        #      + mu^(2-p) / (2-p))
        base = _positive(target) if power > 2.0 else _fn("greatest", target, const(0.0))
        first = _fn("pow", base, const(2.0 - power)) / const(
            (1.0 - power) * (2.0 - power)
        )
        second = target * _fn("pow", mu, const(1.0 - power)) / const(1.0 - power)
        third = _fn("pow", mu, const(2.0 - power)) / const(2.0 - power)
        return const(2.0) * (first - second + third)

    def _outside(
        self, y: Expression, p: Expression
    ) -> list[tuple[Expression, str, str]]:
        power = self.power
        if power == 0.0:
            return []
        target, mu = y.cast("DOUBLE"), p.cast("DOUBLE")
        zero = const(0.0)
        why = (
            f"the Tweedie deviance of power {power!r} is not defined there, "
            "and scikit-learn's mean_tweedie_deviance refuses such values too."
        )
        rows = [(mu <= zero, "a prediction at or below 0", why)]
        if power >= 2.0:
            rows.insert(0, (target <= zero, "a target at or below 0", why))
        elif power >= 1.0:
            rows.insert(0, (target < zero, "a negative target", why))
        return rows


rmse = Metric("rmse", _rmse, False)
mae = Metric("mae", _mae, False)
r2 = Metric("r2", _r2, True)
mse = Metric("mse", _mse, False)
max_error = Metric("max_error", _max_error, False)
median_absolute_error = Metric("median_absolute_error", _median_absolute_error, False)
mape = Metric("mape", _mape, False)
explained_variance = Metric("explained_variance", _ev, True)
msle = LogError("msle", _msle, False)
rmsle = LogError("rmsle", _rmsle, False)
tweedie_deviance = TweedieDeviance("tweedie_deviance", _unused, False)
poisson_deviance = TweedieDeviance(
    "poisson_deviance", _unused, False, power=1.0, settable=False
)
gamma_deviance = TweedieDeviance(
    "gamma_deviance", _unused, False, power=2.0, settable=False
)
