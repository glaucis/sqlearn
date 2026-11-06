"""Tests of the compositor: step pieces become one chain of SQL stages."""

import duckdb
import numpy as np
import pytest
from duckdb.sqltypes import DOUBLE, INTEGER, VARCHAR
from steps_for_tests import MyEncoder, MyScale

import sqlearn as sq
from sqlearn._compose import (
    SOURCE,
    Run,
    Stage,
    _learn_sql,
    _markers,
    build,
    copy_sql,
    describe,
    execute,
    number_rows,
    stage_name,
    step_stage,
)
from sqlearn._config import connection


class FillZero(sq.Step):
    """Replace missing values with 0 (learns nothing)."""

    def apply(self, x, learned):
        """Fill the gaps."""
        return duckdb.CoalesceOperator(x, sq.fn.const(0.0))


@pytest.fixture
def con():
    """Return a connection holding ``t(age) = 10, NULL, 30``."""
    c = duckdb.connect()
    c.sql("CREATE TABLE t AS SELECT * FROM (VALUES (10.0), (NULL), (30.0)) v(age)")
    return c


def impute_then_scale(schema):
    """Return the stages of fill-0 then MyScale, learning in one run."""
    first = step_stage(1, "impute", FillZero("age"), schema, SOURCE)
    second = step_stage(2, "scale", MyScale(), schema, first.name)
    return [first, second]


SCHEMA = [("age", DOUBLE)]


def produce(con, source, stages):
    """Execute a run that produces; return its values, data and statements."""
    values, rel, run = execute(con, source, stages, produce=True)
    assert rel is not None
    return values, rel, run


def test_impute_then_scale_learns_from_imputed_values(con):
    """Scale learns the mean of the imputed column, in one statement."""
    values, rel, run = execute(con, "t", impute_then_scale(SCHEMA), produce=False)
    assert values["s02_scale"]["mean"]["age"] == pytest.approx(40 / 3)
    assert rel is None
    assert len(run.statements) == 1
    assert run.statements[0].startswith("WITH")


def test_stage_names_follow_steps():
    """Each stage is named after its step and position."""
    assert stage_name(3, "scale") == "s03_scale"
    assert stage_name(3, "scale", learn=True) == "l03_scale"
    sql = build("t", impute_then_scale(SCHEMA))
    assert '"s01_impute"' in sql
    assert '"l02_scale"' in sql
    assert sql.endswith('SELECT * FROM "s02_scale"')


def test_a_learn_and_produce_run_is_two_statements(con):
    """Learn values in one statement, then return the data query, lazily."""
    values, rel, run = execute(con, "t", impute_then_scale(SCHEMA), produce=True)
    assert isinstance(run, Run)
    assert len(run.statements) == 2
    learn, data = run.statements
    assert '"l02_scale"' in learn
    assert '"l02_scale"' not in data
    assert "TEMP" not in learn + data
    assert isinstance(rel, duckdb.DuckDBPyRelation)
    # Lazy: a row added after `execute` is in the result.
    con.sql("INSERT INTO t VALUES (20.0)")
    assert len(rel.fetchall()) == 4
    mean = values["s02_scale"]["mean"]["age"]
    assert mean == pytest.approx(40 / 3)


def test_produce_matches_the_learned_values(con):
    """The data query applies the learned values as constants."""
    values, rel, _ = produce(con, "t", impute_then_scale(SCHEMA))
    mean, scale = (
        values["s02_scale"]["mean"]["age"],
        values["s02_scale"]["scale"]["age"],
    )
    assert isinstance(mean, float)
    assert isinstance(scale, float)
    got = [r[0] for r in rel.fetchall()]
    assert got == pytest.approx([(v - mean) / scale for v in (10.0, 0.0, 30.0)])


def test_a_run_that_only_applies_is_one_statement(con):
    """With every value known, the run is the data query alone."""
    known = {"mean": {"age": 10.0}, "scale": {"age": 2.0}}
    stage = step_stage(1, "scale", MyScale(), SCHEMA, SOURCE, values=known)
    values, rel, run = produce(con, "t", [stage])
    assert values == {}
    assert len(run.statements) == 1
    assert "10.0" in run.statements[0]
    assert rel.fetchall() == [(0.0,), (None,), (10.0,)]


def test_reserved_and_spaced_names_are_quoted(con):
    """Column names that are keywords or hold spaces or quotes are quoted."""
    con.sql('CREATE TABLE odd AS SELECT 1.0 AS "order", 3.0 AS "my col", 5.0 AS "a""b"')
    schema = describe(con, "odd", [])
    stages = [step_stage(1, "my scale", MyScale(), schema, SOURCE)]
    values, rel, _ = produce(con, "odd", stages)
    assert set(values["s01_my scale"]["mean"]) == {"order", "my col", 'a"b'}
    assert rel.columns == ["order", "my col", 'a"b']


def test_a_dynamic_step_learns_without_applying(con):
    """A dynamic step learning in this run passes its columns through."""
    con.sql(
        "CREATE TABLE c AS SELECT * FROM (VALUES ('b', 1.0), ('a', 2.0)) v(city, n)"
    )
    schema = [("city", VARCHAR), ("n", DOUBLE)]
    stage = step_stage(1, "onehot", MyEncoder(), schema, SOURCE, applies=False)
    values, _, _ = execute(con, "c", [stage], produce=False)
    assert values == {"s01_onehot": {"cities": {"city": ["a", "b"]}}}
    known = step_stage(
        1, "onehot", MyEncoder(), schema, SOURCE, values=values["s01_onehot"]
    )
    assert list(known.columns) == ["city_a", "city_b", "n"]
    assert describe(con, "c", [known])[0] == ("city_a", INTEGER)


def test_keep_puts_the_output_beside_the_input(con):
    """With keep, the input stays and the output follows it."""
    stage = step_stage(1, "impute", FillZero("age", keep=True), SCHEMA, SOURCE)
    assert list(stage.columns) == ["age", "age_impute"]


def test_duplicate_output_names_are_refused():
    """Two output columns of one stage may not share a name."""
    schema = [("age", DOUBLE), ("age_impute", DOUBLE)]
    with pytest.raises(sq.errors.SqlearnError, match="age_impute"):
        step_stage(1, "impute", FillZero("age", keep=True), schema, SOURCE)
    col = duckdb.ColumnExpression("a")
    with pytest.raises(sq.errors.SqlearnError, match="s01_x"):
        build("t", [Stage("s01_x", {"a": col, "A": col})])


def test_a_stage_with_no_columns_is_refused():
    """A data stage must produce at least one column."""
    with pytest.raises(sq.errors.SqlearnError, match="s01_x"):
        build("t", [Stage("s01_x", {})])


def test_nothing_to_learn_or_produce_runs_nothing(con):
    """A run with no learn stage and nothing to produce has no statement."""
    stage = step_stage(1, "impute", FillZero("age"), SCHEMA, SOURCE)
    assert execute(con, "t", [stage], produce=False) == ({}, None, Run([]))


def test_produce_needs_a_way_to_remake_a_learning_stage(con):
    """A learning stage built by hand cannot be applied with values."""
    agg = sq.agg.mean(duckdb.ColumnExpression("age"))
    stage = Stage("s01_x", {"age": duckdb.ColumnExpression("age")}, {"v0": agg})
    with pytest.raises(sq.errors.SqlearnError, match="s01_x"):
        execute(con, "t", [stage], produce=True)
    with pytest.raises(sq.errors.SqlearnError, match="not mapped"):
        execute(con, "t", [stage], produce=False)


def test_a_second_learning_step_learns_from_the_first_applied(con):
    """Step 2's learn stage reads step 1's output through placeholders."""
    first = step_stage(1, "scale", MyScale(), SCHEMA, SOURCE)
    second = step_stage(2, "again", MyScale(), SCHEMA, first.name)
    source = "SELECT * FROM t WHERE age IS NOT NULL"
    values, _, run = execute(con, source, [first, second], produce=False)
    assert len(run.statements) == 1
    assert '"l01_scale"."v0"' in run.statements[0]
    # Scaled values have mean 0 and population sd 1.
    assert values["s02_again"]["mean"]["age"] == pytest.approx(0.0)
    assert values["s02_again"]["scale"]["age"] == pytest.approx(1.0)


def test_one_statement_and_two_give_equal_rows(con):
    """`build` (one statement) and a learn-and-produce run agree."""
    stages = impute_then_scale(SCHEMA)
    _, rel, run = produce(con, "t", stages)
    assert len(run.statements) == 2
    one = [r[0] for r in con.sql(build("t", stages)).fetchall()]
    assert one == pytest.approx([r[0] for r in rel.fetchall()])


def test_remaking_without_a_learned_value_is_refused():
    """A learned value missing for a column names the stage and column."""
    known = {"mean": {"age": 10.0}, "scale": {}}
    with pytest.raises(sq.errors.SqlearnError, match=r"s01_scale.*'scale'.*'age'"):
        step_stage(1, "scale", MyScale(), SCHEMA, SOURCE, values=known)


def test_the_learn_statement_must_give_one_row():
    """A learn statement returning no row is sqlearn's bug, said so."""

    class NoRows:
        """A connection whose every query returns no row."""

        def sql(self, sql):
            """Return an empty relation."""
            return duckdb.sql("SELECT 1 WHERE false")

    stages = impute_then_scale(SCHEMA)
    with pytest.raises(sq.errors.InternalError, match="one row"):
        execute(NoRows(), "t", stages, produce=False)  # ty: ignore[invalid-argument-type]


def test_learning_from_no_rows_names_the_step(con):
    """A learn stage over no rows raises a StepError for its step."""
    stages = impute_then_scale(SCHEMA)
    with pytest.raises(sq.errors.StepError, match=r"scale \(step 2\).*no rows") as err:
        execute(con, "SELECT * FROM t WHERE false", stages, produce=False)
    assert (err.value.step, err.value.position) == ("scale", 2)


def test_given_columns_replace_the_selector():
    """Columns fixed at learn are used instead of resolving the selector."""
    schema = [("age", DOUBLE), ("extra", DOUBLE)]
    known = {"mean": {"age": 10.0}, "scale": {"age": 2.0}}
    stage = step_stage(1, "scale", MyScale(), schema, SOURCE, known, columns=["age"])
    assert str(stage.columns["extra"]) == '"source"."extra"'


def test_copy_writes_only_the_three_formats():
    """A file format other than parquet, csv or json is refused."""
    assert copy_sql("SELECT 1", "a.csv", "csv").endswith("(FORMAT csv)")
    with pytest.raises(sq.errors.SqlearnError, match="xlsx"):
        copy_sql("SELECT 1", "a.xlsx", "xlsx")


def test_number_rows_counts_from_one_in_read_order():
    """Rows are numbered from 1 as read, under a quoted name."""
    sql = number_rows("SELECT * FROM (VALUES ('c'), ('a'), ('b')) t(v)", 'my "row"')
    rel = connection().sql(sql)
    assert rel.columns == ["v", 'my "row"']
    assert rel.fetchall() == [("c", 1), ("a", 2), ("b", 3)]


class Middle(sq.Step):
    """Learn the median of each column; apply subtracts it."""

    def learn(self, x):
        """Learn the median."""
        return {"median": sq.agg.median(x)}

    def apply(self, x, learned):
        """Shift by the median, so a later step learns from the shifted values."""
        return x - learned.median


NAN = float("nan")


@pytest.mark.parametrize(
    ("values", "dtype"),
    [
        ([3.0, 1.0, 2.0], "DOUBLE"),  # odd count
        ([4.0, 1.0, 10.0, 2.0], "DOUBLE"),  # even: halfway between 2 and 4
        ([5.0, None, NAN, 1.0, None, 2.0, 8.0], "DOUBLE"),  # missing left out
        ([0.1, 0.7, 0.2, 0.3000000001, 1e300, -1e300], "DOUBLE"),
        ([7, 3, 9, 4], "INTEGER"),
        ([7, None, 3, 9], "BIGINT"),
        ([-2.5], "DOUBLE"),
    ],
)
def test_median_matches_duckdb_and_numpy(values, dtype):
    """The sorted median is DuckDB's median, and numpy's over present values."""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE m (a {dtype})")
    con.executemany("INSERT INTO m VALUES (?)", [[v] for v in values])
    stage = step_stage(1, "middle", Middle(), [("a", DOUBLE)], SOURCE)
    got = execute(con, "m", [stage], produce=False)[0]["s01_middle"]["median"]["a"]
    (want,) = con.sql(
        "SELECT median(a) FROM m WHERE a IS NOT NULL AND NOT isnan(a::DOUBLE)"
    ).fetchall()[0]
    present = [v for v in values if v is not None and v == v]
    assert got == want
    assert got == pytest.approx(float(np.median(np.array(present, dtype=float))))


def test_median_of_no_present_value_is_null():
    """Every value missing: the median is NULL (Impute then refuses it)."""
    con = duckdb.connect()
    source = "SELECT * FROM (VALUES (NULL::DOUBLE), ('NaN'::DOUBLE)) t(a)"
    stage = step_stage(1, "middle", Middle(), [("a", DOUBLE)], SOURCE)
    values, _, _ = execute(con, source, [stage], produce=False)
    assert values["s01_middle"]["median"]["a"] is None


def test_median_of_no_rows_is_null():
    """No rows at all: the learn statement's median is NULL beside a count of 0."""
    stage = step_stage(1, "middle", Middle(), [("a", DOUBLE)], SOURCE)
    sql = _learn_sql("SELECT 1.0::DOUBLE AS a WHERE false", [stage])
    assert duckdb.connect().sql(sql).fetchall() == [(0, None)]


def test_median_is_computed_by_sorting_with_odd_names_quoted():
    """The printed SQL sorts with a window and quotes every name it writes."""
    con = duckdb.connect()
    con.sql(
        'CREATE TABLE "o d""d" AS '
        'SELECT * FROM (VALUES (1.0, 5), (3.0, 7)) t("a b", "c""d")'
    )
    schema = [("a b", DOUBLE), ('c"d', INTEGER)]
    stage = step_stage(1, "mid dle", Middle(), schema, SOURCE)
    values, rel, run = produce(con, '"o d""d"', [stage])
    learn = run.statements[0]
    assert "row_number() OVER (ORDER BY" in learn
    assert "median(" not in learn
    assert learn.count("row_number()") == 1
    assert "__sqlearn_quantile" not in learn
    assert '"l01_mid dle_quantile_values"' in learn
    assert '"c""d"' in learn
    assert values["s01_mid dle"]["median"] == {"a b": 2.0, 'c"d': 6.0}
    assert rel.fetchall() == [(-1.0, -1.0), (1.0, 1.0)]


def test_a_later_step_learns_from_values_shifted_by_a_median(con):
    """One statement: MyScale learns from the data after the median's shift."""
    first = step_stage(1, "middle", Middle(), SCHEMA, SOURCE)
    second = step_stage(2, "scale", MyScale(), SCHEMA, first.name)
    values, _, run = execute(con, "t", [first, second], produce=False)
    assert len(run.statements) == 1
    assert values["s01_middle"]["median"]["age"] == 20.0
    assert values["s02_scale"]["mean"]["age"] == 0.0


def test_two_learn_stages_with_medians_in_one_statement(con):
    """Each learn stage sorts its own medians; both come back."""
    first = step_stage(1, "one", Middle(), SCHEMA, SOURCE)
    second = step_stage(2, "two", Middle(), SCHEMA, first.name)
    values, rel, _ = produce(con, "t", [first, second])
    assert values["s01_one"]["median"]["age"] == 20.0
    assert values["s02_two"]["median"]["age"] == 0.0
    assert rel.fetchall() == [(-10.0,), (None,), (10.0,)]


class Doubled(sq.Step):
    """Learn twice the median: a median inside a larger expression."""

    def learn(self, x):
        """Learn the median, doubled."""
        return {"twice": sq.agg.median(x) * sq.fn.const(2)}


def test_a_median_inside_an_expression_is_computed(con):
    """A median may sit inside a larger learned value (the core refused it)."""
    stage = step_stage(1, "double", Doubled(), SCHEMA, SOURCE)
    values, _, _ = execute(con, "t", [stage], produce=False)
    assert values["s01_double"]["twice"]["age"] == 40.0


class Nested(sq.Step):
    """Learn the median of a median: an aggregate of an aggregate."""

    def learn(self, x):
        """Learn the median of the median."""
        return {"m": sq.agg.median(sq.agg.median(x))}


def test_an_aggregate_of_an_aggregate_is_refused(con):
    """A quantile of a quantile is refused, naming the step."""
    stage = step_stage(1, "nest", Nested(), SCHEMA, SOURCE)
    with pytest.raises(
        sq.errors.StepError, match=r"nest \(step 1\).*aggregate of an aggregate"
    ):
        execute(con, "t", [stage], produce=False)


class HandMade(sq.Step):
    """Learn a quantile marker not built by sq.agg (no method)."""

    def learn(self, x):
        """Learn the bad marker."""
        return {"m": duckdb.FunctionExpression("__sqlearn_quantile", x)}


def test_a_marker_sq_agg_did_not_build_is_refused(con):
    """A marker with the wrong arguments is refused, naming sq.agg."""
    stage = step_stage(1, "hand", HandMade(), SCHEMA, SOURCE)
    with pytest.raises(sq.errors.StepError, match=r"hand \(step 1\).*sq\.agg"):
        execute(con, "t", [stage], produce=False)


def test_markers_are_found_outside_quotes_with_their_arguments():
    """Quotes, brackets and longer names do not confuse the marker search."""
    text = (
        "(__sqlearn_quantile(f(\"a\", [1, 2]), 0.5::DOUBLE, 'linear') - "
        "\"__sqlearn_mode(\" + my__sqlearn_mode(1) + __sqlearn_mode('x,)'))"
    )
    found = _markers(text)
    assert [(m.kind, m.args) for m in found] == [
        ("__sqlearn_quantile", ('f("a", [1, 2])', "0.5::DOUBLE", "'linear'")),
        ("__sqlearn_mode", ("'x,)'",)),
    ]
    assert text[found[0].start : found[0].end].startswith("__sqlearn_quantile(f(")
    assert _markers("__sqlearn_mode(1") == []


def test_a_median_of_text_holding_parentheses_and_quotes(con):
    """Parentheses and quotes inside the median's argument do not confuse it."""
    stage = step_stage(1, "middle", Middle(), SCHEMA, SOURCE)
    age = duckdb.ColumnExpression(SOURCE, "age")
    odd = duckdb.CaseExpression(
        age.cast("VARCHAR") == sq.fn.const(")'("), sq.fn.const(None)
    )
    stage.learn = {"v0": sq.agg.median(odd.otherwise(age))}
    values, _, _ = execute(con, "t", [stage], produce=False)
    assert values["s01_middle"]["median"]["age"] == 20.0
