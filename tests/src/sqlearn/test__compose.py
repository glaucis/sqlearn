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
