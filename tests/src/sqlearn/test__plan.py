"""Tests of the run planner: which run each step learns in, and what it reads."""

import pytest
from duckdb.sqltypes import DOUBLE, INTEGER, VARCHAR
from steps_for_tests import MyEncoder, MyScale, Prefix, dynamic_step, static_step

import sqlearn as sq
from sqlearn._plan import plan

SCHEMA = [
    ("age", DOUBLE),
    ("a", DOUBLE),
    ("b", DOUBLE),
    ("x", VARCHAR),
    ("y", VARCHAR),
    ("city", VARCHAR),
    ("name", VARCHAR),
]


def runs(*steps):
    """Plan unnamed steps against SCHEMA."""
    return plan([(f"s{i}", s) for i, s in enumerate(steps)], SCHEMA)


def test_static_only_is_one_run():
    """A pipeline with no dynamic step learns and feeds in run 0."""
    p = runs(static_step("age"), static_step("age"))
    assert (p.learn_run, p.feed_run) == ([0, 0], 0)
    assert p.apply_run == [0, 0]


def test_independent_dynamic_steps_share_a_run():
    """Dynamic steps on different columns learn together."""
    p = runs(dynamic_step("x"), dynamic_step("y"), static_step("a"))
    assert (p.learn_run, p.feed_run) == ([0, 0, 0], 1)
    assert p.apply_run == [1, 1, 0]


def test_reading_new_columns_waits():
    """A selector that may match a dynamic step's new columns waits for it."""
    p = runs(dynamic_step("x"), static_step(sq.cols.numeric()))
    assert (p.learn_run, p.feed_run) == ([0, 1], 1)


def test_earliest_run_per_step():
    """Each step goes in the earliest run its own inputs allow (ADR 0018)."""
    p = runs(
        dynamic_step("x"),
        static_step(Prefix("x_")),
        dynamic_step("y"),
        static_step(Prefix("y_")),
    )
    assert (p.learn_run, p.feed_run) == ([0, 1, 0, 1], 1)


def test_a_chain_of_dynamic_steps_adds_runs():
    """A dynamic step reading another's new columns learns a run later."""
    p = runs(
        dynamic_step("x"),
        dynamic_step(sq.cols.numeric()),
        static_step(sq.cols.numeric()),
    )
    assert (p.learn_run, p.feed_run) == ([0, 1, 2], 2)
    assert p.apply_run == [1, 2, 2]


def test_string_selector_does_not_wait_for_onehot():
    """A selector that cannot match the declared new type does not wait."""
    p = runs(dynamic_step("city"), static_step(sq.cols.string()))
    assert (p.learn_run, p.feed_run) == ([0, 0], 1)


def test_unknown_inputs_depend_on_everything():
    """A step on every column depends on every step before it."""
    p = runs(static_step("age"), static_step(None), static_step("b"))
    assert (p.learn_run, p.feed_run) == ([0, 0, 0], 0)
    assert p.depends_on == [frozenset(), frozenset({0}), frozenset({0, 1})]


def test_depends_on_follows_columns():
    """A step depends only on the steps whose output it reads (ADR 0024)."""
    p = runs(static_step("age"), dynamic_step("city"), static_step("age"))
    assert p.depends_on == [frozenset(), frozenset(), frozenset({0})]


def test_depends_on_is_transitive():
    """Reading a step's output also depends on what that step read."""
    p = runs(static_step("age"), static_step(None), dynamic_step(sq.cols.numeric()))
    assert p.depends_on[2] == frozenset({0, 1})


def test_a_name_not_yet_known_waits():
    """A name that is not in the schema may be a new column, so it waits."""
    p = runs(dynamic_step("x"), static_step(["x_red"]))
    assert (p.learn_run, p.depends_on[1]) == ([0, 1], frozenset({0}))


def test_unknown_inputs_wait_for_new_columns():
    """A step on every column reads a dynamic step's new columns."""
    p = runs(dynamic_step("x"), static_step(None))
    assert (p.learn_run, p.feed_run) == ([0, 1], 1)


def test_undeclared_new_types_match_any_selector():
    """With no declared type, any selector may match the new columns."""
    p = runs(dynamic_step("x", creates=None), static_step(sq.cols.string()))
    assert p.learn_run == [0, 1]


def test_a_replaced_column_keeps_its_type():
    """A static step keeps its column's type, so a string selector finds it."""
    p = runs(static_step("x"), dynamic_step(sq.cols.string()))
    assert p.depends_on[1] == frozenset({0})


def test_a_kept_column_takes_its_input_type():
    """``keep=True`` adds ``<column>_<suffix>`` of the input's type."""
    p = runs(static_step("age", keep=True, suffix="z"), static_step(["age_z"]))
    assert (p.learn_run, p.depends_on[1]) == ([0, 0], frozenset({0}))
    p = runs(static_step("age", keep=True), static_step(["age_s0"]))
    assert p.depends_on[1] == frozenset({0})


def test_a_kept_name_in_use_is_numbered_as_the_compositor_does():
    """``age_z`` taken by an input: the kept column is ``age_z_2``."""
    schema = [("age", DOUBLE), ("age_z", DOUBLE)]
    steps = [static_step("age", keep=True, suffix="z"), static_step(["age_z_2"])]
    p = plan([(f"s{i}", s) for i, s in enumerate(steps)], schema)
    assert p.depends_on[1] == frozenset({0})
    steps = [static_step("age", keep=True, suffix="z"), static_step(["age_z"])]
    p = plan([(f"s{i}", s) for i, s in enumerate(steps)], schema)
    assert p.depends_on[1] == frozenset()


def test_a_kept_unknown_column_stays_unknown():
    """A static step keeping a new column adds another unknown column."""
    p = runs(
        dynamic_step("x"),
        static_step(Prefix("x_"), keep=True),
        static_step(sq.cols.numeric() - sq.cols("age", "a", "b")),
    )
    assert (p.learn_run, p.feed_run) == ([0, 1, 1], 1)
    assert p.depends_on[2] == frozenset({0, 1})


def test_a_dynamic_step_removes_its_input():
    """A dynamic step that does not keep its input takes it out of the schema."""
    p = runs(dynamic_step("city"), static_step(["city"]))
    assert p.depends_on[1] == frozenset({0})
    assert p.learn_run == [0, 1]


def test_a_dynamic_step_leaves_new_columns_it_may_not_read():
    """A dynamic step reading part of an unknown group leaves the rest."""
    p = runs(
        dynamic_step("x"),
        dynamic_step(Prefix("x_a"), creates=VARCHAR),
        static_step(sq.cols.numeric()),
    )
    assert (p.learn_run, p.depends_on[2]) == ([0, 1, 1], frozenset({0}))


def test_a_dynamic_step_leaves_new_columns_of_any_type():
    """New columns of undeclared type may not all be read by a type selector."""
    p = runs(
        dynamic_step("x", creates=None),
        dynamic_step(sq.cols.numeric(), creates=INTEGER),
        static_step(sq.cols.string()),
    )
    assert (p.learn_run, p.depends_on[2]) == ([0, 1, 1], frozenset({0}))


def test_a_dynamic_step_consumes_new_columns_it_must_read():
    """A selector that must match the new type consumes the whole group.

    Nothing is left for the last step to wait for; it still depends on the
    steps that took the numbers away, as they decide what it matches.
    """
    p = runs(
        dynamic_step("x"),
        dynamic_step(sq.cols.numeric(), creates=VARCHAR),
        static_step(sq.cols.numeric()),
    )
    assert (p.learn_run, p.depends_on[2]) == ([0, 1, 0], frozenset({0, 1}))


def test_a_dynamic_step_by_name_leaves_new_columns():
    """Naming one new column does not consume the others."""
    p = runs(dynamic_step("x"), dynamic_step(["x_red"]), static_step(["x_blue"]))
    assert p.depends_on[2] == frozenset({0, 1})


def test_a_dynamic_step_may_keep_its_input():
    """With ``keep=True`` the input stays, as it was."""
    p = runs(dynamic_step("city", keep=True), static_step(["city"]))
    assert (p.learn_run, p.depends_on[1]) == ([0, 0], frozenset())


def test_a_step_that_changes_rows_is_read_by_every_later_step():
    """Every step after a row-changing step depends on it and waits for it."""
    p = runs(
        dynamic_step("x"),
        static_step(sq.cols.numeric(), changes_rows=True),
        static_step("city"),
    )
    assert p.depends_on[2] == frozenset({0, 1})
    assert p.learn_run == [0, 1, 1]


def test_undeclared_steps_are_classified():
    """Steps without a declaration are classified before planning."""
    p = plan([("onehot", MyEncoder()), ("scale", MyScale())], SCHEMA)
    assert (p.learn_run, p.feed_run) == ([0, 1], 1)


def test_an_empty_pipeline_feeds_from_run_0():
    """No steps: the data is fed as it is, in run 0."""
    p = plan([], [("a", INTEGER)])
    assert (p.learn_run, p.feed_run, p.depends_on) == ([], 0, [])


def test_a_declared_dynamic_step_is_planned_as_dynamic():
    """A step declaring ``dynamic = True`` makes the steps after it wait."""
    kind = type("Declared", (sq.Step,), {"dynamic": True, "creates": INTEGER})
    p = plan([("d", kind(cols="city")), ("s", MyScale(cols="age"))], SCHEMA)
    assert (p.learn_run[0], p.apply_run[0]) == (0, 1)


def test_declaring_static_and_dynamic_is_refused():
    """The two declarations contradict each other, so the step is named."""
    kind = type("Both", (sq.Step,), {"static": True, "dynamic": True})
    with pytest.raises(sq.errors.StepError) as err:
        plan([("one", sq.Step()), ("both", kind(cols="age"))], SCHEMA)
    assert (err.value.step, err.value.position) == ("both", 2)
    assert str(err.value) == (
        "both (step 2) declares both static=True and dynamic=True, which "
        "contradict each other. Fix: declare one, or neither (sqlearn will "
        "then detect it)."
    )


def test_a_step_that_could_read_a_removed_column_depends_on_its_remover():
    """A column taken away decides what a later step reads (ADR 0024)."""
    p = runs(dynamic_step("city"), static_step(sq.cols.string()))
    assert (p.learn_run, p.depends_on[1]) == ([0, 0], frozenset({0}))
    by_name = runs(dynamic_step("city"), static_step(["x", "city"]))
    assert 0 in by_name.depends_on[1]
    every = runs(dynamic_step("city"), static_step(None))
    assert 0 in every.depends_on[1]


def test_a_step_that_cannot_read_a_removed_column_does_not_depend_on_it():
    """A removed column of another type or name leaves a step independent."""
    p = runs(
        dynamic_step("city", creates=VARCHAR),
        static_step(sq.cols.numeric()),
        static_step(["x"]),
    )
    assert p.depends_on[1:] == [frozenset(), frozenset()]


def test_a_removed_column_carries_its_removers_dependencies():
    """The remover's own dependencies come along with it."""
    p = runs(
        static_step(["city"], changes_rows=True),
        dynamic_step("x"),
        static_step(["y"]),
    )
    assert p.depends_on[2] == frozenset({0})
    q = runs(static_step(["city"]), dynamic_step("city"), static_step(sq.cols.string()))
    assert q.depends_on[2] == frozenset({0, 1})


class Total(sq.Step):
    """A whole-row step writing its inputs' shares and their total."""

    rowwise = True
    static = True
    creates = DOUBLE

    def apply_row(self, xs, learned, values):
        """Write each share, then the total."""
        total = sum(xs.values(), sq.fn.const(0.0))
        return {**{c: x / total for c, x in xs.items()}, "total": total}


def test_a_rowwise_step_reads_every_input():
    """Each output of a whole-row step reads every selected input (§6.1)."""
    # A dynamic step creates x_* columns; normalize reads one of them, so it
    # waits for that step, and so does a later step reading only ``a``.
    p = runs(
        dynamic_step("city", creates=DOUBLE),
        sq.scale.normalize(["a", "x_1"]),
        static_step("a"),
    )
    assert p.learn_run == [0, 1, 1]
    assert p.depends_on[2] == frozenset({0, 1})
    q = runs(static_step("b"), sq.scale.normalize(["a", "b"]), static_step("a"))
    assert q.depends_on[2] == frozenset({0, 1})


def test_a_rowwise_step_names_its_new_outputs():
    """A new output of a whole-row step is known by name to later steps."""
    p = runs(static_step("b"), Total(["a", "b"]), static_step("total"))
    assert p.depends_on[2] == frozenset({0, 1})
    kept = runs(static_step("b"), Total(["a", "b"], keep=True), static_step("a"))
    assert kept.depends_on[2] == frozenset()
    assert runs(Total(["a", "b"], keep=True), static_step("a_s0")).depends_on[1] == (
        frozenset({0})
    )


def test_a_rowwise_step_reading_unknown_columns_writes_unknown_ones():
    """Outputs of a whole-row step over unknown columns are themselves unknown."""
    p = runs(dynamic_step("city", creates=DOUBLE), Total(["x_1"]), static_step("total"))
    assert (p.learn_run, p.depends_on[2]) == ([0, 1, 1], frozenset({0, 1}))


def test_a_target_step_ends_its_run():
    """A step learning from the target ends its run; its outputs are DOUBLE."""
    p = runs(sq.encode.target("city"), sq.scale.standard())
    assert (p.learn_run, p.apply_run, p.feed_run) == ([0, 1], [1, 1], 1)
    q = runs(sq.encode.target("city"), sq.encode.onehot())
    # The encoded city is a number now, so onehot does not read it: it learns
    # beside the target step, but after it in the pipeline.
    assert q.learn_run == [0, 0]


def test_a_target_step_without_folds_is_refused():
    """A step learning from the target needs whole-number cv and seed."""

    class NoFolds(sq.Step):
        uses_target = True
        static = True

    with pytest.raises(sq.errors.StepError, match=r"s0 \(step 1\).*cv"):
        runs(NoFolds("city"))
