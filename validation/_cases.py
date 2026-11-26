"""What every runner shares: the datasets, the error measures, the JSON.

A case (ADR 0025) compares one implementation's answer with the canonical
value: the exact mathematical answer, a `Fraction` where it is rational and
`mpmath` at 50 digits otherwise, never another library's (ADR 0016). Its
error is measured three ways: absolute and relative against the exact value,
and in ULPs against the double nearest it.
"""

import itertools
import json
import math
import platform
import struct
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path

import duckdb
import mpmath
import numpy as np
import pandas as pd

import sqlearn

SEED = 0
"""Every dataset comes from this seed: generated, never downloaded."""

DIGITS = 50
"""The precision, in decimal digits, of every canonical value from mpmath."""

ANOMALY_FACTOR = 4
"""A reference more than this many times sqlearn's bound from the canonical
value is an anomaly: it misses what its own algorithm (a sum, a sort, a
square root, all of which can be done within a few ULPs) should reach."""

RULES = {
    "pass": (
        "sqlearn: within its bound (ULPs from the canonical value; 0 "
        "mismatches for encoders). A reference: within ANOMALY_FACTOR times "
        "sqlearn's bound, or refusing an input that has no answer."
    ),
    "fail": "sqlearn only: outside its bound, or a mismatch with scikit-learn.",
    "anomaly": (
        f"a reference library more than {ANOMALY_FACTOR} times sqlearn's bound "
        "from the canonical value: it misses the precision its own algorithm "
        "should reach. Reported upstream, never a reason to loosen a bound."
    ),
    "recorded": (
        "a measurement with no bound to pass (approx_quantile, approximate by "
        "name): its error against the canonical value is kept as a known number."
    ),
    "skipped": (
        "the reference cannot run on this input (no rows, or a value it does "
        "not take), or the input has no canonical value; the note says which. "
        "Kept so the table shows every combination."
    ),
}
"""What each result means; written at the top of every results file."""

NUMBER_DATASETS = (
    "small",
    "medium",
    "large",
    "null",
    "nan",
    "empty",
    "single",
    "reserved",
)
SIZES = {"small": 4, "medium": 1_000, "large": 100_000}
WORDS = ("kyiv", "lima", "nuuk", "oslo", "rome")
RESERVED_WORDS = ("from", "group", "order", "where")


@dataclass(frozen=True)
class Dataset:
    """One column of generated values, NULL as None and NaN as `math.nan`."""

    name: str
    column: str
    values: tuple[float | str | None, ...]
    note: str


def _gaps(rng: np.random.Generator, values: list, gap: float | None) -> list:
    """Replace about a tenth of the values with `gap` (None for NULL)."""
    holes = rng.random(len(values)) < 0.1
    return [gap if hole else v for v, hole in zip(values, holes, strict=True)]


def numbers() -> list[Dataset]:
    """Return the numeric datasets: normal values around 1,000, seed 0.

    The values sit far from zero, so a mean or a variance computed carelessly
    loses digits to cancellation and shows it.
    """
    rng = np.random.default_rng(SEED)

    def draw(n: int) -> list[float]:
        return [float(v) for v in rng.normal(1_000.0, 100.0, n)]

    out = [
        Dataset(name, "x", tuple(draw(n)), f"{n:,} values, normal(1000, 100)")
        for name, n in SIZES.items()
    ]
    out += [
        Dataset("null", "x", tuple(_gaps(rng, draw(1_000), None)), "a tenth NULL"),
        Dataset("nan", "x", tuple(_gaps(rng, draw(1_000), math.nan)), "a tenth NaN"),
        Dataset("empty", "x", (), "no rows"),
        Dataset("single", "x", tuple(draw(1)), "one row"),
        Dataset("reserved", "select", tuple(draw(1_000)), 'column named "select"'),
    ]
    return out


def labels() -> list[Dataset]:
    """Return the text datasets for the encoders, seed 0.

    "nan" holds no NaN: a text column cannot. It is kept so the table lists
    it, and the runners record it as skipped.
    """
    rng = np.random.default_rng(SEED)

    def draw(n: int, words: tuple[str, ...] = WORDS) -> list[str]:
        return [str(w) for w in rng.choice(words, n)]

    out = [
        Dataset(name, "city", tuple(draw(n)), f"{n:,} values of {len(WORDS)} words")
        for name, n in SIZES.items()
    ]
    out += [
        Dataset("null", "city", tuple(_gaps(rng, draw(1_000), None)), "a tenth NULL"),
        Dataset("nan", "city", (), "text holds no NaN"),
        Dataset("empty", "city", (), "no rows"),
        Dataset("single", "city", tuple(draw(1)), "one row"),
        Dataset(
            "reserved",
            "select",
            tuple(draw(1_000, RESERVED_WORDS)),
            'column "select", values reserved words',
        ),
    ]
    return out


def is_missing(v: object) -> bool:
    """Tell whether a value is NULL (None) or NaN, as sqlearn's steps do."""
    return v is None or (isinstance(v, float) and math.isnan(v))


def present(values: tuple) -> list:
    """Return the values that are neither NULL nor NaN."""
    return [v for v in values if not is_missing(v)]


def as_nan(values: tuple) -> np.ndarray:
    """Return the values as a float array, NULL and NaN both NaN (numpy's way)."""
    return np.array([math.nan if v is None else v for v in values], dtype=float)


def table(
    con: duckdb.DuckDBPyConnection,
    name: str,
    columns: dict[str, tuple],
    kinds: str | dict[str, str],
) -> duckdb.DuckDBPyRelation:
    """Create a table on `con` of DuckDB type(s) `kinds`, NULL and NaN kept apart.

    Rows go in through a pandas frame, which turns NaN into NULL, so a
    marker column puts the NaN back.
    """
    frame = {}
    selects = []
    for i, (col, values) in enumerate(columns.items()):
        kind = kinds if isinstance(kinds, str) else kinds[col]
        nan = [isinstance(v, float) and math.isnan(v) for v in values]
        frame[f"v{i}"] = pd.Series(
            [None if is_missing(v) else v for v in values], dtype=object
        )
        frame[f"n{i}"] = pd.Series(nan, dtype=bool)
        quoted = '"' + col.replace('"', '""') + '"'
        selects.append(
            f"CASE WHEN n{i} THEN 'NaN'::DOUBLE ELSE v{i}::{kind} END AS {quoted}"
            if kind == "DOUBLE"
            else f"v{i}::{kind} AS {quoted}"
        )
    data = pd.DataFrame(frame)
    con.register("_frame", data)
    con.execute(
        f"CREATE OR REPLACE TABLE {name} AS SELECT {', '.join(selects)} FROM _frame"
    )
    con.unregister("_frame")
    return con.table(name)


def exact_mean(values: list[float]) -> Fraction:
    """Return the exact mean: every double is a rational number."""
    return sum((Fraction(v) for v in values), Fraction(0)) / len(values)


def exact_median(values: list[float]) -> Fraction:
    """Return the exact middle value, or the exact mean of the two middles."""
    ordered = sorted(Fraction(v) for v in values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def exact_variance(values: list[float]) -> Fraction:
    """Return the exact population variance: mean of squares less square of mean."""
    n = len(values)
    squares = sum((Fraction(v) ** 2 for v in values), Fraction(0)) / n
    return squares - exact_mean(values) ** 2


def exact_stddev_pop(values: list[float]) -> mpmath.mpf:
    """Return the population standard deviation at 50 digits (an irrational root)."""
    variance = exact_variance(values)
    with mpmath.workdps(DIGITS):
        return mpmath.sqrt(mpmath.mpf(variance.numerator) / variance.denominator)


def _ordered(x: float) -> int:
    """Map a double to an integer that counts doubles in order (-0.0 is 0)."""
    bits = struct.unpack("<q", struct.pack("<d", x))[0]
    return bits if bits >= 0 else -(2**63) - bits


def ulps(a: float, b: float) -> int | float:
    """Return how many doubles lie between `a` and `b`; inf if one is NaN."""
    if math.isnan(a) or math.isnan(b):
        return 0 if math.isnan(a) and math.isnan(b) else math.inf
    return abs(_ordered(a) - _ordered(b))


def nearest(exact: Fraction | mpmath.mpf) -> float:
    """Return the double nearest the exact value (correctly rounded)."""
    return float(exact)


def _mpf(exact: Fraction | mpmath.mpf) -> mpmath.mpf:
    if isinstance(exact, Fraction):
        return mpmath.mpf(exact.numerator) / exact.denominator
    return exact


def judge(reference: str, distance: float, bound: float) -> str:
    """Return the result of a case: only sqlearn can fail (ADR 0016)."""
    if reference == "sqlearn":
        return "pass" if distance <= bound else "fail"
    return "anomaly" if distance > ANOMALY_FACTOR * bound else "pass"


def _head(**fields: object) -> dict:
    keys = ("step", "formula", "dataset", "rows", "type", "reference")
    out = {k: fields[k] for k in keys}
    out["bound_ulps"] = fields["bound"]
    out["note"] = fields.get("note", "")
    return out


def case(
    *,
    step: str,
    formula: str,
    dataset: str,
    rows: int,
    type: str,
    reference: str,
    value: float,
    exact: Fraction | mpmath.mpf,
    bound: int,
    note: str = "",
) -> dict:
    """Measure `value` against the exact answer and judge it."""
    with mpmath.workdps(DIGITS):
        target = _mpf(exact)
        if math.isnan(value):
            abs_error = rel_error = math.inf
        else:
            difference = abs(mpmath.mpf(value) - target)
            abs_error = float(difference)
            rel_error = (
                float(difference / abs(target))
                if target != 0
                else (0.0 if difference == 0 else math.inf)
            )
    distance = ulps(value, nearest(exact))
    out = _head(**locals())
    out |= {
        "value": value,
        "canonical": nearest(exact),
        "abs_error": abs_error,
        "rel_error": rel_error,
        "ulps": distance,
        "result": judge(reference, distance, bound),
    }
    return out


def skipped(
    *,
    step: str,
    formula: str,
    dataset: str,
    rows: int,
    type: str,
    reference: str,
    note: str,
    bound: int,
    exact: object = None,
    result: str = "skipped",
) -> dict:
    """Record a combination with nothing to measure, and why."""
    out = _head(**locals())
    out |= {
        "value": None,
        "canonical": None if exact is None else nearest(exact),  # type: ignore[arg-type]
        "abs_error": None,
        "rel_error": None,
        "ulps": None,
        "result": result,
    }
    return out


def recorded(
    *,
    step: str,
    formula: str,
    dataset: str,
    rows: int,
    type: str,
    reference: str,
    value: float,
    exact: Fraction | mpmath.mpf,
    note: str = "",
) -> dict:
    """Measure `value` against the exact answer and record it, judging nothing.

    For an answer approximate by name: it has no bound, so its result is
    "recorded" and its bound None.
    """
    out = case(
        step=step,
        formula=formula,
        dataset=dataset,
        rows=rows,
        type=type,
        reference=reference,
        value=value,
        exact=exact,
        bound=0,
        note=note,
    )
    out["bound_ulps"] = None
    out["result"] = "recorded"
    return out


def exact_case(
    *,
    step: str,
    formula: str,
    dataset: str,
    rows: int,
    type: str,
    mismatches: int,
    cells: int,
    compared_with: str,
    note: str = "",
) -> dict:
    """Record sqlearn compared value by value with a reference that must agree.

    Encoders and labels have no rounding: the bound is 0, ``ulps`` holds the
    number of values that differ, and any difference fails.
    """
    out = _head(
        step=step,
        formula=formula,
        dataset=dataset,
        rows=rows,
        type=type,
        reference="sqlearn",
        bound=0,
        note=note,
    )
    out |= {
        "compared_with": compared_with,
        "value": None,
        "canonical": None,
        "abs_error": float(mismatches),
        "rel_error": mismatches / cells if cells else 0.0,
        "ulps": mismatches,
        "result": "pass" if mismatches == 0 else "fail",
    }
    return out


_tables = itertools.count()
_connection: list[duckdb.DuckDBPyConnection] = []


def sqlearn_table(
    columns: dict[str, tuple], kinds: str | dict[str, str]
) -> duckdb.DuckDBPyRelation:
    """Return a new table on sqlearn's connection, under a name never used before.

    Every table gets its own name so the learning store, which knows a
    relation by its query and row count, never mistakes one dataset for
    another of the same size.
    """
    if not _connection:
        _connection.append(duckdb.connect())
        sqlearn.set_config(connection=_connection[0])
    return table(_connection[0], f"data_{next(_tables)}", columns, kinds)


def duckdb_alone(function: str, values: list[float], *, threads: int | None) -> float:
    """Run DuckDB's own aggregate on the values, on a fresh connection.

    Fed the non-missing values only, as sqlearn's steps learn from them, so
    the comparison is like for like. `threads` = 1 shows drift from parallel
    summation; None leaves DuckDB's default.
    """
    con = duckdb.connect()
    if threads is not None:
        con.execute(f"SET threads = {threads}")
    rel = table(con, "data", {"x": tuple(values)}, "DOUBLE")
    return rel.aggregate(f"{function}(x)").fetchall()[0][0]


def first_line(exc: BaseException) -> str:
    """Return an exception's type and the first line of its message."""
    return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"


def measure_all(
    *,
    step: str,
    formula: str,
    data: Dataset,
    type: str,
    exact: Fraction | mpmath.mpf | None,
    bound: int,
    answers: dict[str, Callable[[], float | None]],
    notes: dict[str, str] | None = None,
) -> list[dict]:
    """Compute each reference's answer and measure it against `exact`.

    `exact` None means the input has no answer (no values): sqlearn must
    refuse it with its own error to pass, and every reference is skipped
    with what it did instead.
    """
    out = []
    head = {
        "step": step,
        "formula": formula,
        "dataset": data.name,
        "rows": len(data.values),
        "type": type,
        "bound": bound,
    }
    for reference, answer in answers.items():
        note = (notes or {}).get(reference, "")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = answer()
            if raw is None:
                out.append(
                    skipped(
                        reference=reference,
                        result="fail" if reference == "sqlearn" else "skipped",
                        note="returned NULL",
                        **head,
                    )
                )
                continue
            value = float(raw)
        except Exception as exc:  # noqa: BLE001  (each library's own refusal is recorded)
            if reference == "sqlearn":
                refused = exact is None and isinstance(exc, sqlearn.errors.SqlearnError)
                out.append(
                    skipped(
                        reference=reference,
                        result="pass" if refused else "fail",
                        note=("refused, as specified: " if refused else "")
                        + first_line(exc),
                        **head,
                    )
                )
            else:
                out.append(skipped(reference=reference, note=first_line(exc), **head))
            continue
        if exact is None:
            if reference == "sqlearn":
                out.append(
                    skipped(
                        reference=reference,
                        result="fail",
                        note=f"no answer exists, yet sqlearn returned {value!r}",
                        **head,
                    )
                )
            else:
                out.append(
                    skipped(
                        reference=reference,
                        note="no canonical value (the input has no answer); "
                        f"returned {value!r}",
                        **head,
                    )
                )
            continue
        out.append(
            case(reference=reference, value=value, exact=exact, note=note, **head)
        )
    return out


def _finite(data: object) -> object:
    """Write non-finite numbers as strings, so the JSON stays valid."""
    if isinstance(data, float) and not math.isfinite(data):
        return "NaN" if math.isnan(data) else ("Infinity" if data > 0 else "-Infinity")
    if isinstance(data, dict):
        return {str(k): _finite(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_finite(v) for v in data]
    return data


def to_json(data: object) -> str:
    """Return the JSON text: sorted keys, indent 2, a trailing newline."""
    return json.dumps(_finite(data), sort_keys=True, indent=2, allow_nan=False) + "\n"


def write_json(path: Path, data: object) -> None:
    """Write `data` as JSON to `path`; the same data gives the same bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(data), encoding="utf-8")


def environment() -> dict:
    """Return the versions the results were measured with.

    sqlearn's version comes from git (hatch-vcs) and changes with every
    commit, so only its release part is kept (``0.1``, not ``0.1.dev5+g…``):
    the file changes when a release or a library changes, not each commit.
    The OS release and numpy's BLAS are kept because an OS update can change
    the BLAS (Accelerate ships with macOS) and with it the last digits of
    numpy's linear algebra.
    """
    release = version("sqlearn").split(".dev")[0].split("+")[0]
    blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
    return {
        "sqlearn": ".".join(release.split(".")[:2]),
        "duckdb": duckdb.__version__,
        "numpy": version("numpy"),
        "scikit-learn": version("scikit-learn"),
        "pandas": version("pandas"),
        "mpmath": version("mpmath"),
        "python": ".".join(str(v) for v in sys.version_info[:3]),
        "os": platform.system(),
        "os_release": platform.mac_ver()[0] or platform.release(),
        "machine": platform.machine(),
        "blas": blas,
    }
