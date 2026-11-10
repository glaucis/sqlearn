"""Tests of the compositor: step pieces become one chain of SQL stages."""

import statistics
import time

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
    _in_aggregates,
    _learn_sql,
    _markers,
    apply_sql,
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


def test_a_created_name_in_use_is_numbered():
    """A created name taken by an input column is numbered; the input stays."""
    schema = [("age", DOUBLE), ("age_impute", DOUBLE)]
    stage = step_stage(1, "impute", FillZero("age", keep=True), schema, SOURCE)
    assert list(stage.columns) == ["age", "age_impute_2", "age_impute"]


def test_labels_name_the_created_columns():
    """A mapping is keyed by labels; ``""`` is the input column itself."""

    class Split(sq.Step):
        def apply(self, x, learned):
            return {"": x, "low": x - 1, "high": x + 1}

    stage = step_stage(1, "split", Split("age"), SCHEMA, SOURCE)
    assert list(stage.columns)[:3] == ["age", "age_low", "age_high"]


def test_a_step_may_return_full_names():
    """With names_are_labels False, the mapping's keys are the names."""

    class Full(sq.Step):
        names_are_labels = False

        def apply(self, x, learned):
            return {"a^2": x * x, "A^2": x}

    stage = step_stage(1, "full", Full("age"), SCHEMA, SOURCE)
    assert list(stage.columns)[:2] == ["a^2", "A^2_2"]


def test_one_expression_is_named_as_a_label_even_with_full_names():
    """names_are_labels only concerns a mapping: one expression is the column."""

    class Full(sq.Step):
        names_are_labels = False

        def apply(self, x, learned):
            return x * 2

    stage = step_stage(1, "full", Full("age"), SCHEMA, SOURCE)
    assert list(stage.columns) == ["age"]
    stage = step_stage(1, "full", Full("age", keep=True), SCHEMA, SOURCE)
    assert list(stage.columns) == ["age", "age_full"]


def test_fixed_names_are_used_and_recorded():
    """Given the names fixed at learn, a stage uses them and records them."""
    schema = [("age", DOUBLE), ("age_impute", DOUBLE)]
    stage = step_stage(1, "impute", FillZero("age", keep=True), schema, SOURCE)
    assert stage.created == {"age": ["age_impute_2"]}
    again = step_stage(
        1, "impute", FillZero("age", keep=True), SCHEMA, SOURCE, names=stage.created
    )
    assert list(again.columns) == ["age", "age_impute_2"]


def test_fixed_names_must_match_the_outputs():
    """A step creating other columns than at learn is refused."""
    with pytest.raises(sq.errors.StepError, match=r"impute \(step 1\).*2 when"):
        step_stage(
            1, "impute", FillZero("age", keep=True), SCHEMA, SOURCE,
            names={"age": ["a", "b"]},
        )  # fmt: skip


def test_two_columns_of_one_stage_may_not_share_a_name():
    """A stage built by hand with two equal names is refused."""
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


def test_the_learn_scan_does_not_carry_a_whole_staged_value():
    """The target statistics are read once, not cross-joined into the scan (#41).

    The learned value ``stats`` is one whole staged marker: the learn stage
    reads it beside the scan's one row, so no source row carries the list.
    """
    schema = [("plan", VARCHAR), ("x", DOUBLE)]
    target = sq.encode.target("plan")
    stage = step_stage(1, "target", target, schema, SOURCE, applies=False)
    sql = _learn_sql("t", [stage])
    assert '"l01_target_stats" AS MATERIALIZED' in sql
    assert 'FROM "source" CROSS JOIN' not in sql
    assert '"l01_target" AS MATERIALIZED' in sql


class Spread(sq.Step):
    """Learn a median whole, inside an aggregate, and inside an expression."""

    def learn(self, x):
        """Learn the median three ways."""
        median = sq.agg.median(x)
        return {
            "m": median,
            "d": sq.agg.mean(sq.fn.abs(x - median)),
            "r": sq.agg.max(x) - median,
        }


def test_a_median_whole_nested_and_in_an_expression_in_one_step():
    """A whole median, read beside the scan, agrees with its other two uses."""
    con = duckdb.connect()
    source = "SELECT * FROM (VALUES (1.0), (2.0), (4.0), (10.0), (NULL)) t(a)"
    stage = step_stage(1, "spread", Spread(), [("a", DOUBLE)], SOURCE, applies=False)
    values, _, _ = execute(con, source, [stage], produce=False)
    got = values["s01_spread"]
    # median 3; mean(|1-3|, |2-3|, |4-3|, |10-3|) = 11 / 4; max - median = 7
    assert got["m"]["a"] == 3.0
    assert got["d"]["a"] == pytest.approx(2.75, rel=1e-15)
    assert got["r"]["a"] == 7.0


class MedianAndStd(sq.Step):
    """Learn a median and a standard deviation, each a whole learned value."""

    def learn(self, x):
        """Learn both."""
        return {"m": sq.agg.median(x), "s": sq.agg.std(x)}


def test_whole_staged_values_join_no_stage_into_a_scan():
    """Neither the learn scan nor the std's passes cross-join an unread stage."""
    con = duckdb.connect()
    source = "SELECT * FROM (VALUES (1.0), (2.0), (4.0), (10.0), (NULL)) t(a)"
    stage = step_stage(1, "two", MedianAndStd(), [("a", DOUBLE)], SOURCE, applies=False)
    assert 'FROM "source" CROSS JOIN' not in _learn_sql(source, [stage])
    values, _, _ = execute(con, source, [stage], produce=False)
    assert values["s01_two"]["m"]["a"] == 3.0
    assert values["s01_two"]["s"]["a"] == pytest.approx(
        float(np.std([1.0, 2.0, 4.0, 10.0])), rel=1e-15
    )


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


class Share(sq.Step):
    """Divide each selected value by the row's total; also write the total."""

    rowwise = True
    static = True

    def apply_row(self, xs, learned, values):
        """Write each share, then the total."""
        total = sq.fn.const(0.0)
        for x in xs.values():
            total = total + x
        return {**{c: x / total for c, x in xs.items()}, "total": total}


ROW = [("a", DOUBLE), ("city", VARCHAR), ("b", DOUBLE)]


def test_a_rowwise_step_receives_every_selected_column():
    """A rowwise step's apply_row gets all its columns at once (§6.1)."""
    stage = step_stage(1, "share", Share(["a", "b"]), ROW, SOURCE)
    assert list(stage.columns) == ["a", "city", "b", "total"]
    assert '"source"."b"' in str(stage.columns["a"])
    assert stage.created == {"a": ["a"], "b": ["b", "total"]}


def test_a_rowwise_step_names_its_outputs_by_labels():
    """With keep, an output named after an input follows it, labelled."""
    stage = step_stage(1, "share", Share(["a", "b"], keep=True), ROW, SOURCE)
    assert list(stage.columns) == [
        "a", "a_share", "city", "b", "b_share", "total_share",
    ]  # fmt: skip
    taken = [("a", DOUBLE), ("total_share", DOUBLE), ("b", DOUBLE)]
    numbered = step_stage(1, "share", Share(["a", "b"], keep=True), taken, SOURCE)
    assert list(numbered.columns)[-1] == "total_share_2"
    again = step_stage(
        1, "share", Share(["a", "b"], keep=True), ROW, SOURCE, names=stage.created
    )
    assert list(again.columns) == list(stage.columns)


def test_a_rowwise_step_learns_per_column(con):
    """``learn`` stays per column; apply_row reads each column's values."""

    class Centred(sq.Step):
        rowwise = True
        static = True

        def learn(self, x):
            return {"mean": sq.agg.mean(x)}

        def apply_row(self, xs, learned, values):
            return {c: x - learned[c].mean for c, x in xs.items()}

    con.sql(
        "CREATE TABLE r AS SELECT * FROM "
        "(VALUES (1.0::DOUBLE, 10.0::DOUBLE), (3.0, 30.0)) v(a, b)"
    )
    stage = step_stage(1, "centred", Centred(), [("a", DOUBLE), ("b", DOUBLE)], SOURCE)
    assert stage.learned == {"v0": ("a", "mean"), "v1": ("b", "mean")}
    _, rel, _ = produce(con, "SELECT * FROM r", [stage])
    assert rel.fetchall() == [(-1.0, -10.0), (1.0, 10.0)]


class RowTotal(sq.Step):
    """Divide each value by the row's total, computed once as a row value."""

    rowwise = True
    static = True

    def learn(self, x):
        """Learn the mean."""
        return {"mean": sq.agg.mean(x)}

    def row_values(self, xs, learned):
        """The total of the centred values, once per row."""
        terms = [x - learned[c].mean for c, x in xs.items()]
        return {"total": sum(terms, sq.fn.const(0.0))}

    def apply_row(self, xs, learned, values):
        """Divide by the total."""
        return {c: x / values["total"] for c, x in xs.items()}


def test_row_values_are_computed_once_in_a_projection_of_their_own(con):
    """A row value is one column of the row projection, read by every output."""
    schema = [("a", DOUBLE), ("__row_0", DOUBLE)]
    stage = step_stage(1, "total", RowTotal(["a", "__row_0"]), schema, SOURCE)
    assert list(stage.row) == ["___row_0"]
    assert list(stage.columns) == ["a", "__row_0"]
    assert str(stage.columns["a"]).count("___row_0") == 1
    sql = build("SELECT * FROM r", [stage])
    assert '"r01_total" AS "source"' in sql
    assert "___row_0" in apply_sql(stage)
    con.sql(
        "CREATE TABLE r AS SELECT * FROM "
        "(VALUES (1.0::DOUBLE, 2.0::DOUBLE), (3.0, 6.0)) v(a, __row_0)"
    )
    _, rel, _ = produce(con, "SELECT * FROM r", [stage])
    # Means 2 and 4: the totals are -3 and 3.
    assert rel.fetchall() == [(-1 / 3, -2 / 3), (1.0, 2.0)]


def wide(columns: int, rows: int = 200, name: str | None = None):
    """Return a new table of `columns` numbers and `rows` rows.

    It is named `name`, by default ``wide<columns>``; a name of its own gives
    a table never learned from, which the learning store cannot answer.
    """
    con = connection()
    name = name or f"wide{columns}"
    picks = ", ".join(
        f"(hash(i, {c}) % 1000)::DOUBLE / 7 AS c{c}" for c in range(columns)
    )
    con.execute(
        f"CREATE OR REPLACE TABLE {name} AS SELECT {picks} FROM range({rows}) r(i)"
    )
    return con.table(name)


@pytest.mark.parametrize(
    "step",
    [sq.scale.robust, sq.bin.quantile, sq.impute.mode],
    ids=["scale.robust", "bin.quantile", "impute.mode"],
)
def test_a_cold_learn_of_many_staged_aggregates_is_fast(step):
    """A cold learn of 50 columns costs at most 20 times one of 10 columns.

    Each column brings quantiles (or a mode) computed in stages of their own;
    the learn statement grows linearly with them, and DuckDB plans it fast.
    When each quantile had its own column, filters and scalar subquery
    (before c7bca0b), five times the columns cost 59 (robust) and 70
    (bin.quantile) times as much; now 3 to 8, idle or under load.

    A ratio, not a time: a busy machine slows both learns alike (8 times,
    under 32 busy processes on 8 cores), which failed an absolute limit. The
    learns alternate, and the median of three of each is compared: the
    fastest favoured the short learn, which fits in a quiet moment more often.
    """
    sq.Pipeline([step()]).learn(wide(1))  # warm up: imports, caches
    times: dict[int, list[float]] = {10: [], 50: []}
    for run in range(3):
        for columns, taken in times.items():
            data = wide(columns, name=f"cold{columns}_{run}")  # never learned
            pipe = sq.Pipeline([step()])
            start = time.perf_counter()
            pipe.learn(data)
            taken.append(time.perf_counter() - start)
    assert statistics.median(times[50]) / statistics.median(times[10]) < 20


def test_two_hundred_columns_of_quantiles_learn():
    """200 columns' quantiles stay within DuckDB's expression depth."""
    pipe = sq.Pipeline([sq.scale.robust()]).learn(wide(200, rows=20))
    assert len(pipe[0].center_) == 200


class Learns(sq.Step):
    """Learn the values `make` builds from the column; apply leaves it."""

    def __init__(self, make, cols=None, keep=False):
        """Set the settings."""
        super().__init__(cols=cols, keep=keep)
        self.make = make

    def learn(self, x):
        """Learn what `make` builds."""
        return self.make(x)

    def apply(self, x, learned):
        """Leave the column."""
        return x


VALUES = [1.0, 2.0, 3.0, 9.0, None, 4.0]


def learned(make, values=VALUES, kind="DOUBLE"):
    """Return what a `Learns` step learns from column ``a`` holding `values`."""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t (a {kind})")
    con.executemany("INSERT INTO t VALUES (?)", [[v] for v in values])
    schema = [("a", duckdb.sqltype(kind))]
    stage = step_stage(1, "learns", Learns(make), schema, SOURCE)
    got = execute(con, "t", [stage], produce=False)[0]["s01_learns"]
    return {k: v["a"] for k, v in got.items()}


def test_a_quantile_inside_another_aggregate_is_computed():
    """Mean absolute deviation about the median, and a sum about it, as numpy."""
    present = np.array([v for v in VALUES if v is not None])
    middle = np.median(present)

    def make(x):
        centred = x - sq.agg.median(x)
        return {
            "mad": sq.agg.mean(duckdb.FunctionExpression("abs", centred)),
            "sum": duckdb.FunctionExpression("sum", centred),
            "iqr": sq.agg.iqr(x),
            "plus": sq.agg.median(x) + duckdb.FunctionExpression("sum", centred),
        }

    got = learned(make)
    assert got["mad"] == pytest.approx(np.mean(np.abs(present - middle)))
    assert got["sum"] == pytest.approx(np.sum(present - middle))
    assert got["iqr"] == pytest.approx(
        np.quantile(present, 0.75) - np.quantile(present, 0.25)
    )
    assert got["plus"] == pytest.approx(middle + np.sum(present - middle))


def test_a_mode_inside_another_aggregate_is_computed():
    """How many values equal the mode, at the top level beside it."""

    def make(x):
        hits = duckdb.CaseExpression(x == sq.agg.mode(x), sq.fn.const(1))
        return {
            "mode": sq.agg.mode(x),
            "hits": duckdb.FunctionExpression("sum", hits.otherwise(sq.fn.const(0))),
        }

    got = learned(make, ["b", "a", "b", None, "c"], "VARCHAR")
    assert got == {"mode": "b", "hits": 2}


def test_a_nested_quantile_over_no_rows_gives_one_row():
    """No rows: the learn statement still gives one row, the values NULL."""
    centred = lambda x: x - sq.agg.median(x)  # noqa: E731
    stage = step_stage(
        1,
        "learns",
        Learns(lambda x: {"sum": duckdb.FunctionExpression("sum", centred(x))}),
        [("a", DOUBLE)],
        SOURCE,
    )
    sql = _learn_sql("SELECT 1.0::DOUBLE AS a WHERE false", [stage])
    assert duckdb.connect().sql(sql).fetchall() == [(0, None)]


def test_spans_inside_aggregates_are_found_once():
    """Only the outermost aggregate's brackets count; quotes and FILTER are read."""
    text = "sum(abs(\"x\" - m)) + f('sum(') + count(*) FILTER (WHERE y > m) + g(1)) "
    spans = [text[a:b] for a, b in _in_aggregates(text)]
    assert spans == ['abs("x" - m)', "*", "WHERE y > m"]


CHAINED = """
    SELECT
        CASE WHEN i % 11 = 0 THEN NULL
             ELSE 20 + (hash(i, 1) % 600) / 10 END::DOUBLE AS age,
        CASE WHEN i % 13 = 0 THEN NULL
             ELSE 1000 + hash(i, 2) % 100000 END::DOUBLE AS income,
        (hash(i, 5) % 100 < 30)::INTEGER AS churned
    FROM range(10000000) t(i)
"""


@pytest.mark.slow
def test_two_chained_quantile_stages_spill(tmp_path):
    """The median, then the robust scaler, learn 10 million rows within 64 MB.

    Two learn stages, each sorting three columns, in one statement: the
    second sorts the first's output. With a join of the ranks to the sorted
    rows, it ran out of memory here; the core's plan, and this one, spill.
    At 20 million rows it does not fit 64 MB, as it did not for the core.
    """
    path = tmp_path / "chained.parquet"
    duckdb.execute(f"COPY ({CHAINED}) TO '{path}' (FORMAT parquet)")
    con = duckdb.connect()
    con.execute("set memory_limit = '64MB'")
    con.execute("set threads = 1")
    con.execute(f"set temp_directory = '{tmp_path / 'spill'}'")
    sq.set_config(connection=con)
    pipe = sq.Pipeline([sq.impute.median(), sq.scale.robust()]).learn(str(path))
    data = f"read_parquet('{path}')"
    (medians,) = (
        duckdb.connect()
        .sql(f"SELECT [median(age), median(income), median(churned)] FROM {data}")
        .fetchall()[0]
    )
    assert pipe[0].value_ == pytest.approx(
        dict(zip(["age", "income", "churned"], medians, strict=True))
    )
    assert pipe[1].center_ == pytest.approx(pipe[0].value_)


class _NamesOne(sq.Step):
    """From ``b`` a column named in full ``a``; from ``a`` one expression."""

    static = True
    names_are_labels = False

    def apply(self, x, learned):
        """Write ``a`` from ``b``; replace any other column."""
        if x.get_name() == "b":
            return {"a": x * 10}
        return x + 1


def test_a_replaced_column_keeps_its_name_beside_a_created_one():
    """One expression replacing ``a`` keeps the name ``a`` (ADR 0035).

    A column another input creates under that name is numbered instead, as
    the planner plans it, so a later step naming ``a`` reads the replaced one.
    """
    rel = connection().sql("SELECT 1.0::DOUBLE AS b, 2.0::DOUBLE AS a")
    later = sq.Step(apply=lambda x: x * 100, cols=["a"])
    pipe = sq.Pipeline([("names", _NamesOne()), ("later", later)]).learn(rel)
    assert pipe.columns_out_ == ["a_2", "a"]
    assert pipe.apply(rel).fetchall() == [(10.0, 300.0)]
