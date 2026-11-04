"""Tests of the compositor: step pieces become one chain of SQL stages."""

import duckdb
import pytest
from duckdb.sqltypes import DOUBLE, INTEGER, VARCHAR
from steps_for_tests import MyEncoder, MyScale

import sqlearn as sq
from sqlearn._compose import (
    SOURCE,
    Run,
    Stage,
    build,
    copy_sql,
    describe,
    execute,
    stage_name,
    step_stage,
)


class FillZero(sq.Step):
    """Replace missing values with 0 (learns nothing)."""

    def apply(self, x, learned):
        """Fill the gaps."""
        return duckdb.CoalesceOperator(x, sq.const(0.0))


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
    with pytest.raises(sq.SqlearnError, match="age_impute"):
        step_stage(1, "impute", FillZero("age", keep=True), schema, SOURCE)
    col = duckdb.ColumnExpression("a")
    with pytest.raises(sq.SqlearnError, match="s01_x"):
        build("t", [Stage("s01_x", {"a": col, "A": col})])


def test_a_stage_with_no_columns_is_refused():
    """A data stage must produce at least one column."""
    with pytest.raises(sq.SqlearnError, match="s01_x"):
        build("t", [Stage("s01_x", {})])


def test_nothing_to_learn_or_produce_runs_nothing(con):
    """A run with no learn stage and nothing to produce has no statement."""
    stage = step_stage(1, "impute", FillZero("age"), SCHEMA, SOURCE)
    assert execute(con, "t", [stage], produce=False) == ({}, None, Run([]))


def test_produce_needs_a_way_to_remake_a_learning_stage(con):
    """A learning stage built by hand cannot be applied with values."""
    agg = sq.avg(duckdb.ColumnExpression("age"))
    stage = Stage("s01_x", {"age": duckdb.ColumnExpression("age")}, {"v0": agg})
    with pytest.raises(sq.SqlearnError, match="s01_x"):
        execute(con, "t", [stage], produce=True)
    with pytest.raises(sq.SqlearnError, match="not mapped"):
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
    with pytest.raises(sq.SqlearnError, match=r"s01_scale.*'scale'.*'age'"):
        step_stage(1, "scale", MyScale(), SCHEMA, SOURCE, values=known)


def test_the_learn_statement_must_give_one_row():
    """A learn statement returning no row is sqlearn's bug, said so."""

    class NoRows:
        """A connection whose every query returns no row."""

        def sql(self, sql):
            """Return an empty relation."""
            return duckdb.sql("SELECT 1 WHERE false")

    stages = impute_then_scale(SCHEMA)
    with pytest.raises(sq.InternalError, match="one row"):
        execute(NoRows(), "t", stages, produce=False)  # ty: ignore[invalid-argument-type]


def test_learning_from_no_rows_names_the_step(con):
    """A learn stage over no rows raises a StepError for its step."""
    stages = impute_then_scale(SCHEMA)
    with pytest.raises(sq.StepError, match=r"scale \(step 2\).*no rows") as err:
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
    with pytest.raises(sq.SqlearnError, match="xlsx"):
        copy_sql("SELECT 1", "a.xlsx", "xlsx")
