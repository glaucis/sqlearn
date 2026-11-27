"""Validate sq.transform: every output against numpy and Python's own methods.

``transform`` learns nothing, so its cases are its outputs on the numeric and
text datasets. ``log``, ``log1p`` and ``sqrt`` are compared with numpy's
``np.log``, ``np.log1p`` and ``np.sqrt`` on the present values (the datasets
are normal around 1,000, so all are inside the domains): the worst distance
in ULPs is the case, and it must stay within the bound (ADR 0016). A NULL
must stay NULL and a NaN stay NaN, counted as an exact case. ``clip`` is
compared with ``np.clip`` (both bounds, lower only, upper only), value by
value, exactly; ``lower`` and ``upper`` with ``str.lower`` and ``str.upper``,
exactly, on words written in mixed case.
"""

import math
from fractions import Fraction

import numpy as np

import sqlearn as sq
from validation import _cases

# Set from the first measurement (ADR 0016): the smallest power of two at or
# above the worst ULP error sqlearn showed, at least 1. Loosening a bound
# needs a written reason here, never a quiet edit. First measured: log and
# sqrt 0 ULPs (the same C library function as numpy's), so the floor of 1;
# log1p 2 ULPs (the Kahan correction ln(u) * (x / (u - 1)) is rounded three
# times where numpy's is a single library call), so the bound is 2.
BOUNDS = {"log": 1, "log1p": 2, "sqrt": 1}

NUMPY = {"log": np.log, "log1p": np.log1p, "sqrt": np.sqrt}

CLIPS = (
    ("both", {"lower": 950.0, "upper": 1050.0}, (950.0, 1050.0)),
    ("lower", {"lower": 1000.0}, (1000.0, None)),
    ("upper", {"upper": 1000.0}, (None, 1000.0)),
)
"""The clips measured: a name, sqlearn's bounds, numpy's."""

STR_METHODS = {"lower": str.lower, "upper": str.upper}


def _run(step: sq.Step, data: _cases.Dataset, kind: str) -> list:
    """Return the one-step pipeline's output column for the dataset."""
    rel = _cases.sqlearn_table({data.column: data.values}, kind)
    return [row[0] for row in sq.Pipeline([step]).learn(rel).apply(rel).fetchall()]


def _kept_missing(values: tuple, got: list) -> int:
    """Count the places a NULL did not stay NULL or a NaN did not stay NaN."""
    misses = 0
    for v, g in zip(values, got, strict=True):
        if v is None:
            misses += g is not None
        elif _cases.is_missing(v):
            misses += not (isinstance(g, float) and math.isnan(g))
    return misses


def _function_cases(data: _cases.Dataset, method: str) -> list[dict]:
    """Return log's, log1p's or sqrt's cases on a dataset."""
    head = {
        "step": f"transform.{method}",
        "dataset": data.name,
        "rows": len(data.values),
        "type": "DOUBLE",
    }
    present = _cases.present(data.values)
    if not present:
        return [
            _cases.skipped(
                reference="sqlearn",
                formula=f"{method}(x) against numpy",
                note="no values to transform",
                bound=BOUNDS[method],
                **head,
            )
        ]
    got = _run(sq.transform(data.column, method=method), data, "DOUBLE")
    ours = [
        g for v, g in zip(data.values, got, strict=True) if not _cases.is_missing(v)
    ]
    theirs = NUMPY[method](np.array(present, dtype=float)).tolist()
    worst = max(range(len(ours)), key=lambda i: _cases.ulps(ours[i], theirs[i]))
    return [
        _cases.case(
            reference="sqlearn",
            formula=f"{method}(x), the worst value of the column",
            value=ours[worst],
            exact=Fraction(theirs[worst]),
            bound=BOUNDS[method],
            note=f"{data.note}; compared with numpy's value, the worst of {len(ours)}",
            **head,
        ),
        _cases.exact_case(
            formula=f"{method}: NULL stays NULL, NaN stays NaN",
            mismatches=_kept_missing(data.values, got),
            cells=len(data.values),
            compared_with=f"numpy np.{method}",
            note=data.note,
            **head,
        ),
    ]


def _clip_cases(data: _cases.Dataset) -> list[dict]:
    """Return clip's cases on a dataset: every output against ``np.clip``."""
    out = []
    for name, ours_bounds, (low, high) in CLIPS:
        got = _run(sq.transform.clip(data.column, **ours_bounds), data, "DOUBLE")
        expected = np.clip(_cases.as_nan(data.values), low, high).tolist()
        mismatches = 0
        for v, g, e in zip(data.values, got, expected, strict=True):
            if v is None:
                mismatches += g is not None
            elif _cases.is_missing(v):
                mismatches += not (isinstance(g, float) and math.isnan(g))
            else:
                mismatches += g != e
        out.append(
            _cases.exact_case(
                step="transform.clip",
                formula=f"clip, {name} bound(s) {ours_bounds}",
                dataset=data.name,
                rows=len(data.values),
                type="DOUBLE",
                mismatches=mismatches,
                cells=len(data.values),
                compared_with="numpy np.clip",
                note=f"{data.note}; every output, missing kept",
            )
        )
    return out


def _mixed(values: tuple) -> tuple:
    """Return the words in mixed case: capitalised, then upper, alternately."""
    return tuple(
        None if v is None else (v.capitalize() if i % 2 == 0 else v.upper())
        for i, v in enumerate(values)
    )


def _text_cases(data: _cases.Dataset, method: str) -> list[dict]:
    """Return lower's or upper's cases on a text dataset."""
    mixed = _cases.Dataset(data.name, data.column, _mixed(data.values), data.note)
    got = _run(sq.transform(data.column, method=method), mixed, "VARCHAR")
    expected = [None if v is None else STR_METHODS[method](v) for v in mixed.values]
    return [
        _cases.exact_case(
            step=f"transform.{method}",
            formula=f"{method}(x) of words in mixed case",
            dataset=data.name,
            rows=len(data.values),
            type="VARCHAR",
            mismatches=sum(g != e for g, e in zip(got, expected, strict=True)),
            cells=len(data.values),
            compared_with=f"Python str.{method}",
            note=f"{data.note}; every output, NULL kept",
        )
    ]


def cases() -> list[dict]:
    """Return sq.transform's cases: the functions, clip, and the case changes."""
    out = []
    for data in _cases.numbers():
        for method in NUMPY:
            out += _function_cases(data, method)
        out += _clip_cases(data)
    for data in _cases.labels():
        for method in STR_METHODS:
            out += _text_cases(data, method)
    return out
