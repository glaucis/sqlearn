"""Feedback when a run fails: find the step, say what went wrong and the fix.

Nothing here runs on the normal path. The pipeline calls `diagnose` from its
``except`` blocks only (ADR 0019).
"""

import platform
import re
from collections.abc import Callable, Sequence
from types import TracebackType

import duckdb

from sqlearn._errors import InternalError, SqlearnError, StepError
from sqlearn._step import Learned, Step, apply_rows

__all__ = ["diagnose"]

_MISSING_COLUMN = re.compile(r'column "([^"]+)" not found', re.IGNORECASE)
_REPORT = "https://github.com/glaucis/sqlearn/issues"


def _first_line(exc: BaseException) -> str:
    """Return the first line of an exception's message."""
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def _versions() -> str:
    """Return the versions a bug report needs."""
    from sqlearn import __version__

    return (
        f"sqlearn {__version__}, duckdb {duckdb.__version__}, "
        f"Python {platform.python_version()}"
    )


def _method(tb: TracebackType | None, step: Step) -> str:
    """Name the step's method (learn, apply, ...) the traceback went through."""
    found = "learn or apply"
    while tb is not None:
        code = tb.tb_frame.f_code.co_name
        if (
            code in {"learn", "apply", "apply_row", "derive"}
            and tb.tb_frame.f_locals.get("self") is step
        ):
            found = code
        tb = tb.tb_next
    return found


def _needs_values(step: Step) -> tuple[str, BaseException] | None:
    """Inspect a step with placeholders; return the learned name that fails it.

    Returns the last learned name `apply` read and the error it hit, or None
    when `apply` builds its SQL from placeholders (or fails for another
    reason).
    """
    x = duckdb.ColumnExpression("x")
    try:
        names = {name: f"v{i}" for i, name in enumerate(step.learn(x))}
        learned = Learned.placeholders("learn", names)
    except Exception:  # noqa: BLE001  (a step that cannot learn is not this case)
        return None
    try:
        if step.rowwise:
            apply_rows(step, {"x": x}, {"x": learned}, lambda _, n: x)
        else:
            step.apply(x, learned)
    except Exception as exc:  # noqa: BLE001  (any failure of apply is the signal)
        if learned.accessed:
            return learned.accessed[-1], exc
    return None


def _declared_static(
    name: str, position: int, step: Step, used: str, exc: BaseException
) -> str:
    verb = "loops over" if isinstance(exc, TypeError) else "uses"
    method = "apply_row" if step.rowwise else "apply"
    return (
        f"{name} (step {position}) is declared static, but its {method}() {verb} "
        f"learned.{used}, which is only known after learning. A step that "
        "needs learned values to write its SQL is dynamic.\n"
        "Fix: remove static=True (sqlearn will then detect it), or set "
        "dynamic=True."
    )


def _internal(
    name: str,
    position: int,
    step: Step,
    exc: BaseException,
    sql: str | None,
) -> InternalError:
    kind = type(step)
    shown = sql if sql is not None else "(not composed: the step failed first)"
    msg = (
        f"{name} (step {position}) is a built-in step ({kind.__module__}."
        f"{kind.__name__}) and it failed: {_first_line(exc)}\n"
        "This is sqlearn's bug, not a mistake in your pipeline. Please report "
        f"it at {_REPORT} with the SQL and versions below.\n"
        f"SQL:\n{shown}\n"
        f"Versions: {_versions()}"
    )
    return InternalError(msg)


def _user(
    exc: BaseException,
    name: str,
    position: int,
    step: Step,
    running: bool,
) -> StepError:
    if step.static is True:
        needy = _needs_values(step)
        if needy is not None:
            msg = _declared_static(name, position, step, *needy)
            return StepError(msg, step=name, position=position)
    if isinstance(exc, duckdb.Error):
        missing = _MISSING_COLUMN.search(str(exc))
        if missing is not None:
            msg = (
                f"{name} (step {position}) reads column {missing.group(1)!r}, "
                "which is not in the data reaching it. DuckDB says: "
                f"{_first_line(exc)}\n"
                "Fix: read only columns that reach the step, or add an "
                "earlier step that makes the column."
            )
        elif running:
            msg = (
                f"{name} (step {position}) fails while running: {exc}\n"
                "Fix: check that the step's learn and apply suit the values "
                "in the data."
            )
        else:
            msg = (
                f"{name} (step {position}) builds SQL that DuckDB refuses: "
                f"{exc}\n"
                "Fix: check that the step's learn and apply suit the columns "
                "it is given."
            )
    else:
        method = _method(exc.__traceback__, step)
        msg = (
            f"{name} (step {position}) failed in its {method}() with "
            f"{type(exc).__name__}: {exc}.\n"
            "Fix: correct the step's code; sqlearn calls it with SQL "
            "expressions, not numbers."
        )
    return StepError(msg, step=name, position=position)


def _out_of_memory(
    exc: BaseException,
    steps: Sequence[tuple[str, Step]],
    position: int | None,
    learning: Sequence[int],
) -> SqlearnError:
    """Explain DuckDB running out of memory while learning (issue 27).

    DuckDB's text names no stage, so `position` is usually None; then the
    steps learning in the failed statement (`learning`, positions from 1) are
    named as the candidates, and "a step" is said only when none is known.
    """
    candidates = [position] if position is not None else list(learning)
    known = [p for p in candidates if 1 <= p <= len(steps)]
    named = [f"{steps[p - 1][0]!r} (step {p})" for p in known]
    if not named:
        where = "a step"
    elif len(named) == 1:
        where = f"step {named[0]}"
    else:
        where = "one of the steps " + ", ".join(named)
    msg = (
        f"DuckDB ran out of memory while learning {where}. "
        "Why: an exact median or quantile sorts its column, and DuckDB's "
        "memory_limit is too small for it "
        "(docs/benchmarks/median-reach.md). "
        "Fix: give DuckDB more memory with sq.set_config(memory=...), run it "
        "on fewer threads (SET threads = 1 on the connection given to "
        "sq.set_config(connection=...)), or pass approx=True to the median, "
        f"which is close but not exact. DuckDB says: {_first_line(exc)}"
    )
    return SqlearnError(msg)


def diagnose(
    exc: BaseException,
    steps: Sequence[tuple[str, Step]],
    stage_of: Callable[[str], int | None],
    *,
    running: bool = False,
    sql: str | None = None,
    learning: Sequence[int] = (),
) -> SqlearnError:
    """Explain a failure: which step, what went wrong, why and the fix.

    Call this from an ``except`` block only. A failure while building the SQL
    is traced to its step by the caller (`stage_of` ignores the message); one
    while running is traced by the stage name in DuckDB's message. A user's
    step gets a `StepError`, with its declaration re-checked by inspection; a
    built-in step gets an `InternalError`, since its failure is sqlearn's bug.

    Parameters
    ----------
    exc : BaseException
        The failure.
    steps : sequence of (str, Step)
        The pipeline's named steps, in order.
    stage_of : callable
        Maps text (the error's message) to the position of the step it names,
        counting from 1, or None when it names none.
    running : bool, default False
        True when the failure came while running SQL, not while building it.
    sql : str, optional
        The statement that failed, for the report of an internal error.
    learning : sequence of int, optional
        The positions (from 1) of the steps learning in the failed statement.
        DuckDB's out-of-memory text names no stage, so those steps are the
        ones named for it: all of them, as the error cannot say which.

    Returns
    -------
    SqlearnError
        `exc` itself when it is already an sqlearn error; else a `StepError`
        for a user's step, an `InternalError` for a built-in one, or a plain
        `SqlearnError` when no step can be named.

    Examples
    --------
    >>> import duckdb
    >>> import sqlearn as sq
    >>> from sqlearn._diagnose import diagnose
    >>> err = diagnose(duckdb.Error("bad"), [("s", sq.Step())], lambda text: None)
    >>> str(err).splitlines()[0]
    'DuckDB failed, and no step could be named: bad'
    """
    if isinstance(exc, SqlearnError):
        return exc
    position = stage_of(str(exc))
    if isinstance(exc, duckdb.OutOfMemoryException):
        return _out_of_memory(exc, steps, position, learning)
    if position is None or not 1 <= position <= len(steps):
        msg = (
            f"{'DuckDB' if isinstance(exc, duckdb.Error) else type(exc).__name__} "
            f"failed, and no step could be named: {exc}"
        )
        return SqlearnError(msg)
    name, step = steps[position - 1]
    if type(step).__module__.startswith("sqlearn."):
        return _internal(name, position, step, exc, sql)
    return _user(exc, name, position, step, running)
