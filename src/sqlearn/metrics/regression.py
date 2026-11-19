"""Regression metrics, each one aggregate query.

The metrics are rmse, mae, r2, mse, max_error, median_absolute_error,
mape, explained_variance, msle, rmsle, pinball_loss, the deviances
tweedie_deviance, poisson_deviance and gamma_deviance, and the D2 scores
d2_tweedie, d2_pinball and d2_absolute_error.
"""

import math
import warnings
from dataclasses import dataclass, replace
from numbers import Real
from typing import SupportsFloat

import duckdb
from duckdb import ColumnExpression, Expression

from sqlearn._errors import PACKAGE_FILES, SqlearnError, SqlearnWarning
from sqlearn._expr import const
from sqlearn.metrics.accuracy import _STAGE, Metric, _refuse_settings

__all__ = [
    "LogError",
    "PinballLoss",
    "TweedieDeviance",
    "d2_absolute_error",
    "d2_pinball",
    "d2_tweedie",
    "explained_variance",
    "gamma_deviance",
    "mae",
    "mape",
    "max_error",
    "median_absolute_error",
    "mse",
    "msle",
    "pinball_loss",
    "poisson_deviance",
    "r2",
    "rmse",
    "rmsle",
    "tweedie_deviance",
]


def _fn(name: str, *args: Expression) -> Expression:
    return duckdb.FunctionExpression(name, *args)


def _one_or_zero(condition: Expression) -> Expression:
    # The score of a case with nothing to compare against (a constant
    # target, or a baseline that loses nothing): 1 when the condition holds,
    # else 0, as scikit-learn's force_finite has it.
    return duckdb.CaseExpression(condition, const(1.0)).otherwise(const(0.0))


def _error(y: Expression, p: Expression) -> Expression:
    return y.cast("DOUBLE") - p.cast("DOUBLE")


def _rmse(y: Expression, p: Expression) -> Expression:
    return _fn("sqrt", _mse(y, p))


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
    constant = _one_or_zero(residual == const(0.0))
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
    constant = _one_or_zero(numerator == const(0.0))
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


def _only_setting(
    metric: "_OneSetting", settings: dict[str, object], only: str
) -> None:
    # The refusals shared by the metrics with one setting: a fixed metric
    # takes none, and no other name is one.
    if not metric.settable:
        _refuse_settings(metric.name, settings)
    unknown = [k for k in settings if k != only]
    if unknown:
        msg = (
            f"{metric.name} has no setting {unknown[0]}=. Why: its only "
            f"setting is {only}. Fix: use {only}=, or "
            f"sq.metrics.{metric.name} as it is."
        )
        raise SqlearnError(msg)


def _named(metric: "_OneSetting", setting: str, default: float) -> str:
    # The name, with the setting when it is set to other than its default.
    value = getattr(metric, setting)
    if metric.settable and value != default:
        return f"{metric.name}({setting}={value!r})"
    return metric.name


_PLACE = f"{_STAGE}place"
_ROWS = f"{_STAGE}rows"
_QUANTILE = f"{_STAGE}quantile"
"""The D2 pinball stages' columns: each row's place in the sorted target and
the row count, then the target's alpha-quantile."""
_MEAN = f"{_STAGE}mean"
"""The D2 Tweedie stage's column: the target's mean."""


def _d2_finish(name: str, value: SupportsFloat, total: int) -> float:
    # A D2 score compares the model with a constant taken from the target,
    # which one row cannot tell from the model: NaN with a warning, as
    # scikit-learn has it.
    if total < 2:
        text = (
            f"{name} of {total} row is NaN. Why: a D2 score compares the "
            "model with a constant guess taken from the target, and one row "
            "leaves nothing to compare; scikit-learn returns NaN too. Fix: "
            "score two rows or more (in a search, folds that each hold two "
            "rows or more)."
        )
        warnings.warn(text, SqlearnWarning, skip_file_prefixes=PACKAGE_FILES)
        return math.nan
    return float(value)


@dataclass(frozen=True)
class TweedieDeviance(Metric):
    """The mean Tweedie deviance, as scikit-learn's ``mean_tweedie_deviance``.

    Power 0 is the squared error, 1 the Poisson deviance, 2 the gamma
    deviance. The rows refused follow scikit-learn: for a power below 0 a
    prediction at or below 0; for 0 none; for 1 up to 2 a negative target or
    a prediction at or below 0; for 2 and above a target or a prediction at
    or below 0. Each row is scikit-learn's formula, a difference of terms
    that grow with the values: on a target far from 0 those terms cancel,
    and the deviance keeps only 4 or 5 significant digits where the mean
    is a million times the spread, as scikit-learn's does (a relative error
    of 2e-5 to 8e-5 in both, at powers 1 to 3). Power 0 is a difference of
    the two values and keeps its digits.

    With ``d2`` it is the D2 Tweedie score instead (``d2_tweedie``), as
    scikit-learn's ``d2_tweedie_score``: one minus the model's deviance over
    the deviance of the target's mean, refusing the same rows. Higher is
    better. One row has no score: NaN, with a warning. A departure from
    scikit-learn 1.9.1, which raises ``ZeroDivisionError`` there (ADR 0054):
    a constant target (its minimum equals its maximum) scores 1 when every
    prediction equals it and 0 otherwise, as ``r2`` does. Below power 0 the
    target's mean may be negative, and is scored as scikit-learn scores it;
    at a power whose ``1 - power`` is not whole that mean's power is
    undefined and the score is NaN, as scikit-learn's is (a search then
    ranks that setting last).

    Attributes
    ----------
    power : float, default 0.0
        The power: at most 0 or at least 1.
    d2 : bool, default False
        Whether this is the D2 score rather than the mean deviance; not a
        setting.
    settable : bool, default True
        Whether the power can be set by a call.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.tweedie_deviance(power=1.5)
    tweedie_deviance(power=1.5)
    >>> sq.metrics.d2_tweedie(power=2)
    d2_tweedie(power=2.0)
    >>> import duckdb
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (1, 1.5), (2, 2), (3, 2), (4, 5)) t(y, prediction)"
    ... )
    >>> sq.metrics.d2_tweedie.compute(rel, "y")
    0.55
    >>> sq.metrics.poisson_deviance.greater_is_better
    False
    """

    power: float = 0.0
    d2: bool = False
    settable: bool = True

    def __post_init__(self) -> None:
        """Refuse a power out of range; set the aggregate, which reads it.

        Raises
        ------
        SqlearnError
            If the power is not a finite number at most 0 or at least 1.
        """
        power: object = self.power  # as given, which may not be a float
        if (
            isinstance(power, bool)
            or not isinstance(power, Real)
            or not math.isfinite(float(power))
            or 0 < float(power) < 1
        ):
            msg = (
                f"{self.name} was given power={power!r}. Why: it takes a "
                "finite number at most 0 or at least 1, as scikit-learn's "
                f"{self._reference}. Fix: use such a power, for example "
                "power=1.5."
            )
            raise SqlearnError(msg)
        object.__setattr__(self, "power", float(power))
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
        _only_setting(self, settings, "power")
        return replace(self, **settings)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Return the name, with the power when it is set."""
        return _named(self, "power", 0.0)

    @property
    def _reference(self) -> str:
        """Return the name of scikit-learn's function for this metric."""
        return "d2_tweedie_score" if self.d2 else "mean_tweedie_deviance"

    def _predict_stages(
        self, y: Expression, p: Expression
    ) -> list[dict[str, Expression]]:
        # The D2 baseline: the target's compensated mean (favg, ADR 0033) on
        # every row, a window over the whole relation.
        if not self.d2:
            return []
        return [{_MEAN: _fn("favg", y.cast("DOUBLE")).over()}]

    def _finish(self, value: SupportsFloat, total: int) -> float:
        if self.d2:
            return _d2_finish(self.name, value, total)
        return super()._finish(value, total)

    def _expression(
        self, y: Expression, p: Expression, *mean: Expression
    ) -> Expression:
        # scikit-learn's per-row deviance, then the compensated mean (favg,
        # ADR 0033), or for D2 one minus the model's compensated sum over
        # the mean's.
        target, mu = y.cast("DOUBLE"), p.cast("DOUBLE")
        if not self.d2:
            return _fn("favg", self._row(target, mu))
        (baseline,) = mean
        model = _fn("fsum", self._row(target, mu))
        # The mean as scikit-learn takes it: unguarded below power 0, where
        # a mean at or below 0 still has a deviance; from power 1 a mean at
        # or below 0 means a refused row or a constant target of 0.
        guess = _fn("fsum", self._row(target, baseline, guard=self.power >= 1.0))
        # A constant target (minimum equals maximum, ADR 0054) scores 1 when
        # every prediction equals it and 0 otherwise: its mean can be one
        # rounding off, and a deviance of an exact prediction need not round
        # to 0 (power -1).
        exact = _one_or_zero(_fn("bool_and", target == mu))
        return duckdb.CaseExpression(
            _fn("min", target) == _fn("max", target), exact
        ).otherwise(const(1.0) - model / guess)

    def _row(
        self, target: Expression, mu: Expression, *, guard: bool = True
    ) -> Expression:
        # One row's deviance. A pow or ln is guarded so that a row outside
        # the range gives a number and the refusal comes after the
        # aggregate.
        power = self.power
        if power == 0.0:
            error = target - mu
            return error * error
        mu = _positive(mu) if guard else mu
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
        return row

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
            f"and scikit-learn's {self._reference} refuses such values too."
        )
        rows = [(mu <= zero, "a prediction at or below 0", why)]
        if power >= 2.0:
            rows.insert(0, (target <= zero, "a target at or below 0", why))
        elif power >= 1.0:
            rows.insert(0, (target < zero, "a negative target", why))
        return rows


@dataclass(frozen=True)
class PinballLoss(Metric):
    """The mean pinball loss, as scikit-learn's ``mean_pinball_loss``.

    A row costs ``alpha`` times how far the target is above the prediction,
    and ``1 - alpha`` times how far it is below. Alpha 0.5 is half the mean
    absolute error. No row is refused.

    With ``d2`` it is the D2 pinball score instead (``d2_pinball``, and
    ``d2_absolute_error`` at alpha 0.5), as scikit-learn's
    ``d2_pinball_score``: one minus the model's pinball loss over the loss of
    the target's alpha-quantile. The quantile is scikit-learn's: with ``n``
    rows sorted and ``k = n * alpha``, the mean of rows ``k`` and ``k + 1``
    when ``k`` is whole (to within scikit-learn's rounding), else row
    ``ceil(k)``, counted from 1 and kept within 1 to ``n``. Higher is better.
    One row has no score: NaN, with a warning. When the quantile loses
    nothing (a constant target, or alpha 0 or 1), it scores 1 when the model
    loses nothing too and 0 otherwise, as scikit-learn does; on a constant
    target that is the rule ADR 0054 gives ``d2_tweedie``.

    Attributes
    ----------
    alpha : float, default 0.5
        The quantile: from 0 to 1, both included.
    d2 : bool, default False
        Whether this is the D2 score rather than the mean loss; not a
        setting.
    settable : bool, default True
        Whether the alpha can be set by a call.

    Examples
    --------
    >>> import sqlearn as sq
    >>> sq.metrics.pinball_loss(alpha=0.9)
    pinball_loss(alpha=0.9)
    >>> sq.metrics.pinball_loss.greater_is_better
    False
    >>> sq.metrics.d2_pinball(alpha=0.9)
    d2_pinball(alpha=0.9)
    >>> import duckdb
    >>> rel = duckdb.sql(
    ...     "SELECT * FROM (VALUES (1, 1.5), (2, 2), (3, 2), (4, 5)) t(y, prediction)"
    ... )
    >>> sq.metrics.d2_absolute_error.compute(rel, "y")
    0.375
    """

    alpha: float = 0.5
    d2: bool = False
    settable: bool = True

    def __post_init__(self) -> None:
        """Refuse an alpha out of range; set the aggregate, which reads it.

        Raises
        ------
        SqlearnError
            If the alpha is not a number from 0 to 1.
        """
        alpha: object = self.alpha  # as given, which may not be a float
        if (
            isinstance(alpha, bool)
            or not isinstance(alpha, Real)
            or not 0.0 <= float(alpha) <= 1.0
        ):
            msg = (
                f"{self.name} was given alpha={alpha!r}. Why: it takes a "
                f"number from 0 to 1, as scikit-learn's {self._reference}. "
                "Fix: use such an alpha, for example alpha=0.9."
            )
            raise SqlearnError(msg)
        object.__setattr__(self, "alpha", float(alpha))
        object.__setattr__(self, "expression", self._expression)

    def __call__(self, **settings: object) -> "PinballLoss":
        """Return a copy with the given alpha.

        Parameters
        ----------
        **settings : object
            ``alpha``: a number from 0 to 1.

        Returns
        -------
        PinballLoss
            The configured copy.

        Raises
        ------
        SqlearnError
            If this metric has a fixed alpha, a setting is not ``alpha``, or
            the alpha is not a number from 0 to 1.

        Examples
        --------
        >>> import sqlearn as sq
        >>> sq.metrics.pinball_loss(alpha=0.1)
        pinball_loss(alpha=0.1)
        """
        _only_setting(self, settings, "alpha")
        return replace(self, **settings)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        """Return the name, with the alpha when it is set."""
        return _named(self, "alpha", 0.5)

    @property
    def _reference(self) -> str:
        """Return the name of scikit-learn's function for this metric."""
        return "d2_pinball_score" if self.d2 else "mean_pinball_loss"

    def _predict_stages(
        self, y: Expression, p: Expression
    ) -> list[dict[str, Expression]]:
        # The D2 baseline, the target's alpha-quantile as scikit-learn's
        # _weighted_percentile(y, ones, 100 * alpha, average=True) takes it,
        # on every row: first each row's place in the sorted target and the
        # row count, then the mean of the one or two rows it averages.
        if not self.d2:
            return []
        target = y.cast("DOUBLE")
        place = ColumnExpression(_PLACE)
        n = ColumnExpression(_ROWS).cast("DOUBLE")
        # Its arithmetic in doubles: k = 100 * alpha / 100 * n, its
        # percentile rank scaled back (for alpha 1/17, 100 * alpha / 100 is
        # one double below alpha). With unit weights the cumulative weights
        # are 1 to n, so its sorted search is the first row whose place is at
        # least k (at least the first row, at most the last), and it averages
        # that row with the next (at most the last) unless the row's place
        # passes k by more than the double epsilon.
        k = const(self.alpha * 100.0 / 100.0) * n
        row = _fn("least", _fn("greatest", _fn("ceil", k), const(1.0)), n)
        above = (row - k) > const(_EPSILON)
        plus_one = duckdb.CaseExpression(above, row).otherwise(
            _fn("least", row + const(1.0), n)
        )
        chosen = duckdb.CaseExpression((place == row) | (place == plus_one), target)
        return [
            {
                _PLACE: _fn("row_number").over(order_by=[target]),
                _ROWS: _fn("count_star").over(),
            },
            {_QUANTILE: _fn("avg", chosen).over()},
        ]

    def _finish(self, value: SupportsFloat, total: int) -> float:
        if self.d2:
            return _d2_finish(self.name, value, total)
        return super()._finish(value, total)

    def _expression(
        self, y: Expression, p: Expression, *quantile: Expression
    ) -> Expression:
        # alpha * max(y - p, 0) + (1 - alpha) * max(p - y, 0), compensated
        # mean (favg, ADR 0033), or for D2 one minus the model's compensated
        # sum over the quantile's.
        target, mu = y.cast("DOUBLE"), p.cast("DOUBLE")
        if not self.d2:
            return _fn("favg", self._row(target, mu))
        (baseline,) = quantile
        model = _fn("fsum", self._row(target, mu))
        guess = _fn("fsum", self._row(target, baseline))
        # When the quantile loses nothing, 1 if the model loses nothing too,
        # else 0, as scikit-learn's force_finite has it: a constant target
        # (minimum equals maximum, ADR 0054), or at alpha 0 or 1 any target,
        # since its quantile is then the least or the greatest value. The
        # mean of one or two equal values is exact, so a constant target's
        # quantile loses exactly 0 and the two tests agree there.
        exact = _one_or_zero(model == const(0.0))
        nothing = (_fn("min", target) == _fn("max", target)) | (guess == const(0.0))
        return duckdb.CaseExpression(nothing, exact).otherwise(
            const(1.0) - model / guess
        )

    def _row(self, target: Expression, mu: Expression) -> Expression:
        # One row's pinball loss.
        zero = const(0.0)
        over = _fn("greatest", target - mu, zero)
        under = _fn("greatest", mu - target, zero)
        return const(self.alpha) * over + const(1.0 - self.alpha) * under


_OneSetting = TweedieDeviance | PinballLoss
"""The metrics with one setting, as `_only_setting` and `_named` read them."""

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
pinball_loss = PinballLoss("pinball_loss", _unused, False)
d2_tweedie = TweedieDeviance("d2_tweedie", _unused, True, d2=True)
d2_pinball = PinballLoss("d2_pinball", _unused, True, d2=True)
d2_absolute_error = PinballLoss(
    "d2_absolute_error", _unused, True, d2=True, settable=False
)


_EXAMPLE = (
    "    >>> import duckdb\n"
    "    >>> import sqlearn as sq\n"
    "    >>> rel = duckdb.sql(\n"
    '    ...     "SELECT * FROM (VALUES (3, 2.5), (-0.5, 0), (2, 2), (7, 8)) "\n'
    '    ...     "t(y, prediction)"\n'
    "    ... )\n"
)


def _document(metric: Metric, summary: str, edge: str, value: str) -> None:
    # Give one plain metric its own docstring, so that its reference page
    # says what it scores rather than repeating the Metric class's.
    text = (
        f"{summary}\n\n{edge}\n\nExamples\n--------\n{_EXAMPLE}"
        f'    >>> sq.metrics.{metric.name}.compute(rel, "y")\n    {value}\n'
    )
    object.__setattr__(metric, "__doc__", text)


_document(
    rmse,
    "The root mean squared error, as scikit-learn's ``root_mean_squared_error``. "
    "Lower is better.",
    "It is the square root of ``mse``, in the target's own units.",
    "0.6123724356957945",
)
_document(
    mae,
    "The mean absolute error, as scikit-learn's ``mean_absolute_error``. "
    "Lower is better.",
    "Each row counts by its distance, so one far row moves it less than it "
    "moves ``mse``.",
    "0.5",
)
_document(
    r2,
    "The coefficient of determination, as scikit-learn's ``r2_score``. Higher "
    "is better; 1 is perfect and 0 is no better than the target's mean.",
    "On a constant target it scores 1 when every prediction equals the target "
    "and 0 otherwise, as scikit-learn does.",
    "0.9486081370449679",
)
_document(
    mse,
    "The mean squared error, as scikit-learn's ``mean_squared_error``. Lower "
    "is better.",
    "The squares are summed with compensation, so a large column keeps its digits.",
    "0.375",
)
_document(
    max_error,
    "The largest absolute error, as scikit-learn's ``max_error``. Lower is better.",
    "It reads only the worst row.",
    "1.0",
)
_document(
    median_absolute_error,
    "The median absolute error, as scikit-learn's ``median_absolute_error``. "
    "Lower is better.",
    "It is not moved by a few far rows.",
    "0.5",
)
_document(
    mape,
    "The mean absolute percentage error, as scikit-learn's "
    "``mean_absolute_percentage_error``. Lower is better; it is a fraction, "
    "0.5 meaning 50%.",
    "A row's error is divided by the larger of the absolute target and the "
    "double epsilon (2.22e-16), as scikit-learn does, so a zero target gives a "
    "huge number (about 2.25e15 for an error of 0.5), not an error.",
    "0.3273809523809524",
)
_document(
    explained_variance,
    "The explained variance, as scikit-learn's ``explained_variance_score``. "
    "Higher is better; 1 is perfect. Unlike ``r2`` it ignores a constant "
    "offset in the errors.",
    "On a constant target it scores 1 when the errors have no variance and 0 "
    "otherwise. A target all 0.3 with predictions all 0.1 scores the exact 1 "
    "here, where scikit-learn's rounding of the mean leaves a variance that "
    "is tiny but not 0, so its score depends on the row count (0.75 on "
    "1,000 rows, 0 on 100, 1 on 10).",
    "0.9571734475374732",
)
