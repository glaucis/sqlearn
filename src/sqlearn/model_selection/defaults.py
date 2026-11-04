"""Default search spaces for known models from other libraries (ADR 0022).

The table grows one model at a time; each entry is tested against the model
it is for.
"""

import itertools
from typing import Any

__all__ = ["DEFAULT_SPACES", "default_space", "hint"]

DEFAULT_SPACES: dict[tuple[str, str], dict[str, list[Any]]] = {
    ("sklearn", "LogisticRegression"): {
        # numpy.logspace(-3, 2, 7), to five significant figures.
        "C": [0.001, 0.0068129, 0.046416, 0.31623, 2.1544, 14.678, 100.0],
    },
}
"""Settings to search per ``(top-level package, class name)`` of a model."""


def default_space(estimator: object) -> dict[str, list[Any]] | None:
    """Return the default space for a model, or None when there is none.

    Parameters
    ----------
    estimator : object
        The model.

    Returns
    -------
    dict or None
        Its settings to search, each to a list of values.

    Examples
    --------
    >>> from sklearn.linear_model import LogisticRegression
    >>> from sqlearn.model_selection.defaults import default_space
    >>> default_space(LogisticRegression())["C"][0]
    0.001
    """
    cls = type(estimator)
    package = cls.__module__.split(".")[0]
    return DEFAULT_SPACES.get((package, cls.__name__))


def _log_spaced(values: list[Any]) -> bool:
    """Say whether numbers grow by one factor (to the rounding of the table)."""
    if len(values) < 3 or not all(
        isinstance(v, (int, float)) and v > 0 for v in values
    ):
        return False
    ratios = [float(b) / float(a) for a, b in itertools.pairwise(values)]
    return ratios[0] != 1 and all(abs(r / ratios[0] - 1) < 1e-3 for r in ratios)


def hint(model: str, space: dict[str, list[Any]]) -> str:
    """Describe a space in a line: each setting's span, scale and count.

    Parameters
    ----------
    model : str
        The model's name.
    space : dict
        Its settings, each to a list of values.

    Returns
    -------
    str
        ``<model>: C in [0.001, 100], log scale, 7 values``.

    Examples
    --------
    >>> from sqlearn.model_selection.defaults import hint
    >>> hint("M", {"k": [1, 2]})
    'M: k in [1, 2], 2 values'
    """
    parts = []
    for name, values in space.items():
        scale = ", log scale" if _log_spaced(values) else ""
        parts.append(
            f"{name} in [{min(values):g}, {max(values):g}]{scale}, {len(values)} values"
        )
    return f"{model}: {'; '.join(parts)}"
