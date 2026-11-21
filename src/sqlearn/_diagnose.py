"""Feedback when a run fails: find the step, say what went wrong and the fix.

Nothing here runs on the normal path. The pipeline calls `diagnose` from its
``except`` blocks only (ADR 0019).
"""

import platform
import re
from collections.abc import Callable, Sequence
from types import TracebackType

import duckdb

from sqlearn._compose import stage_name
from sqlearn._config import connection, get_config
from sqlearn._errors import InternalError, SqlearnError, StepError
from sqlearn._expr import quote
from sqlearn._memory import _megabytes, duckdb_limit
from sqlearn._step import Learned, Step, apply_rows

__all__ = ["applying_out_of_memory", "diagnose", "exploring_out_of_memory"]

_MISSING_COLUMN = re.compile(r'column "([^"]+)" not found', re.IGNORECASE)
_REPORT = "https://github.com/glaucis/sqlearn/issues"
_PARQUET = re.compile(r"read_parquet\(\s*(\[[^\]]*\]|'(?:[^']|'')*')")
_QUOTED = re.compile(r"'((?:[^']|'')*)'")
_ROW_GROUP_ROWS = 20_000
"""The largest row group suggested: what the Gram benchmark wrote at 200
columns (docs/benchmarks/gram-streaming.md)."""


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


def _sorts(
    sql: str | None, steps: Sequence[tuple[str, Step]], known: list[int]
) -> bool:
    """Say whether a step in `known` sorts for an exact median or quantile.

    An exact quantile is learned in a stage of its own, named after the
    step's learn stage with ``_quantile`` (`stage_name`), so the failed
    statement holds that name exactly when one of those steps sorts.
    """
    if sql is None:
        return False
    return any(
        quote(stage_name(p, steps[p - 1][0], learn=True) + "_quantile") in sql
        for p in known
    )


def _row_groups(
    sql: str | None, columns: Sequence[str] | None = None
) -> tuple[str, str, int] | None:
    """Say a Parquet file's row groups are too wide for the threads and limit.

    DuckDB reads a Parquet file one row group at a time on each thread,
    holding every column it reads (issue #68). Returns the why, the fix and
    the threads when the failed statement reads Parquet files whose largest row group,
    uncompressed, times the threads is over half the ``memory_limit``; else
    None, as when the files' metadata cannot be read. With `columns`, the
    names the failed statement reads, a row group weighs those columns only.
    """
    if sql is None:
        return None
    files = [
        p.replace("''", "'")
        for found in _PARQUET.findall(sql)
        for p in _QUOTED.findall(found)
    ]
    if not files:
        return None
    con = connection()
    listed = ", ".join("'" + f.replace("'", "''") + "'" for f in files)
    within = ""
    if columns is not None:
        names = ", ".join("'" + c.replace("'", "''") + "'" for c in columns)
        within = f"WHERE path_in_schema IN ({names or 'NULL'}) "
    try:
        widest, rows = con.execute(
            "SELECT max(size), arg_max(rows, size) FROM (SELECT "
            "sum(total_uncompressed_size) AS size, any_value(row_group_num_rows) "
            f"AS rows FROM parquet_metadata([{listed}]) {within}"
            "GROUP BY file_name, row_group_id)"
        ).fetchall()[0]
        threads = int(con.execute("SELECT current_setting('threads')").fetchall()[0][0])
        limit = duckdb_limit(con)
    except duckdb.Error:
        return None
    if widest is None or widest * threads * 2 <= limit:
        return None
    # Rows a group so that each thread's group fits in a quarter of the limit.
    fit = int(rows * limit / (4 * widest * threads)) // 1000 * 1000
    suggest = max(1000, min(_ROW_GROUP_ROWS, fit))
    each = "one thread reads" if threads == 1 else f"each of {threads} threads reads"
    read = ""
    if columns is not None:
        plural = "column" if len(columns) == 1 else "columns"
        read = f" of the {len(columns)} {plural} it reads"
    why = (
        "DuckDB reads a Parquet file one row group at a time on each thread, "
        "holding every column it reads, and the file's largest row group is "
        f"{_megabytes(widest)} uncompressed{read} ({rows:,} rows): {each} one "
        f"within a memory_limit of {_megabytes(limit)}."
    )
    fix = (
        "write the file with smaller row groups, such as COPY (FROM "
        "'data.parquet') TO 'smaller.parquet' (FORMAT parquet, "
        f"ROW_GROUP_SIZE {suggest})"
    )
    return why, fix, threads


def _memory_fixes(wide: tuple[str, str, int] | None) -> list[str]:
    """Return the fixes for memory, threads and row groups, for the connection.

    Fewer threads is left out when DuckDB runs on one already.
    """
    if get_config().connection is None:
        fixes = [
            "give DuckDB more memory with sq.set_config(memory=...), whose half "
            "is the memory_limit of sqlearn's own connection",
            "run it on fewer threads by passing a connection with "
            "SET threads = 1 to sq.set_config(connection=...)",
        ]
    else:
        fixes = [
            "give DuckDB more memory with SET memory_limit = '...' on the "
            "connection passed to sq.set_config(connection=...)",
            "run it on fewer threads with SET threads = 1 on that connection",
        ]
    if wide is not None:
        if wide[2] == 1:
            del fixes[1]
        fixes.append(wide[1])
    return fixes


def _joined(fixes: Sequence[str]) -> str:
    return f"{', '.join(fixes[:-1])}, or {fixes[-1]}"


def applying_out_of_memory(exc: BaseException, sql: str) -> SqlearnError:
    """Explain DuckDB running out of memory while sqlearn fetches an apply.

    Parameters
    ----------
    exc : BaseException
        DuckDB's out-of-memory error.
    sql : str
        The statement that failed.

    Returns
    -------
    SqlearnError
        The why and the fixes: more memory, fewer threads, and smaller row
        groups when it reads a Parquet file whose row groups are too wide.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._diagnose import applying_out_of_memory
    >>> err = applying_out_of_memory(duckdb.OutOfMemoryException("no"), "SELECT 1")
    >>> str(err).split(" Why:")[0]
    'DuckDB ran out of memory while applying the pipeline.'
    """
    wide = _row_groups(sql)
    fixes = _memory_fixes(wide)
    why = "DuckDB's memory_limit is too small for the data and its steps."
    if wide is not None:
        why = f"{why} {wide[0]}"
    msg = (
        f"DuckDB ran out of memory while applying the pipeline. Why: {why} "
        f"Fix: {_joined(fixes)}. DuckDB says: {_first_line(exc)}"
    )
    return SqlearnError(msg)


def exploring_out_of_memory(
    exc: BaseException,
    sql: str,
    function: str,
    *,
    sorts: bool = False,
    estimates: bool = False,
    columns: Sequence[str] | None = None,
) -> SqlearnError:
    """Explain DuckDB running out of memory while an exploration function reads.

    Parameters
    ----------
    exc : BaseException
        DuckDB's out-of-memory error.
    sql : str
        The statement that failed, or the one that reads the data.
    function : str
        The function's name, for the message.
    sorts : bool, default False
        Whether the function also sorts the rows (ranks them), which a
        smaller memory_limit cannot hold either and fewer columns do not
        shrink; the why then says so, and more memory and fewer threads
        lead the fixes.
    estimates : bool, default False
        Whether the function counts distinct values and quartiles exactly
        and could estimate them with ``exact=False`` (`profile`); the why
        then says the exact ones keep every value, and ``exact=False``
        leads the fixes, before more memory, fewer threads and fewer
        columns.
    columns : sequence of str, optional
        The columns the failed statement reads; a Parquet row group then
        weighs only those, and the why says how many. By default every
        column of the data.

    Returns
    -------
    SqlearnError
        The why and the fixes: fewer columns, more memory, fewer threads, and
        smaller row groups when the data is a Parquet file whose row groups
        are too wide.

    Examples
    --------
    >>> import duckdb
    >>> from sqlearn._diagnose import exploring_out_of_memory
    >>> err = exploring_out_of_memory(
    ...     duckdb.OutOfMemoryException("no"), "SELECT 1", "top"
    ... )
    >>> str(err).split(" Why:")[0]
    'DuckDB ran out of memory while `top` read the data.'
    """
    wide = _row_groups(sql, columns)
    fixes = ["pass fewer columns with cols=", *_memory_fixes(wide)]
    if sorts:
        # A sort is helped by memory or threads first; fewer columns does not
        # shrink it, so it comes after them (before the row groups' fix).
        fixes = _memory_fixes(wide)
        fixes.insert(len(fixes) - (wide is not None), "pass fewer columns with cols=")
    if estimates:
        # The exact counts and quartiles keep every value; exact=False keeps
        # a small state instead, so it leads, and the memory follows.
        fixes = [
            "pass exact=False to estimate the distinct counts and quartiles",
            *_memory_fixes(wide),
        ]
        fixes.insert(len(fixes) - (wide is not None), "pass fewer columns with cols=")
    why = "DuckDB's memory_limit is too small for the columns it reads at once"
    if sorts:
        why = f"{why}, or for the rows a rank sorts, which fewer columns do not shrink"
    if estimates:
        why = (
            f"{why}, or for the values an exact distinct count hashes and exact "
            "quartiles sort, which are every value of a column"
        )
    why = f"{why}."
    if wide is not None:
        why = f"{why} {wide[0]}"
    return SqlearnError(
        f"DuckDB ran out of memory while `{function}` read the data. Why: {why} "
        f"Fix: {_joined(fixes)}. DuckDB says: {_first_line(exc)}"
    )


def _out_of_memory(
    exc: BaseException,
    steps: Sequence[tuple[str, Step]],
    position: int | None,
    learning: Sequence[int],
    sql: str | None,
) -> SqlearnError:
    """Explain DuckDB running out of memory while learning (issue 27).

    DuckDB's text names no stage, so `position` is usually None; then the
    steps learning in the failed statement (`learning`, positions from 1) are
    named as the candidates, and "a step" is said only when none is known.
    The median is blamed, and ``approx=True`` offered, only when one of them
    sorts for an exact median or quantile. The memory and threads fixes are
    written for the connection: ``sq.set_config(memory=...)`` limits only
    sqlearn's own, so a passed connection is given ``SET`` statements.
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
    median = _sorts(sql, steps, known)
    if median:
        why = (
            "an exact median or quantile sorts its column, and DuckDB's "
            "memory_limit is too small for it (docs/benchmarks/median-reach.md)."
        )
    else:
        learns = "the steps learn" if len(named) > 1 else "the step learns"
        why = f"DuckDB's memory_limit is too small for what {learns}."
    wide = _row_groups(sql)
    fixes = _memory_fixes(wide)
    if median:
        fixes.append("pass approx=True to the median, which is close but not exact")
    if wide is not None:
        why = f"{why} {wide[0]}"
    msg = (
        f"DuckDB ran out of memory while learning {where}. Why: {why} "
        f"Fix: {_joined(fixes)}. DuckDB says: {_first_line(exc)}"
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
        The statement that failed, for the report of an internal error, and
        to tell whether an out-of-memory learn sorted for an exact median.
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
        return _out_of_memory(exc, steps, position, learning, sql)
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
