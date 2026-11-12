"""Tests of the category lookup the ordinal and target encoders take (#31)."""

import warnings

import duckdb
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

import sqlearn as sq
from sqlearn.errors import SqlearnError, SqlearnWarning, StepError
from sqlearn.preprocessing import _lookup

ENCODERS = {
    "ordinal": sq.encode.ordinal,
    "target": sq.encode.target,
}
"""The encoders that look a category up, by name."""


def many(k, rows_each=2):
    """Return `k` categories, every one in `rows_each` rows, a binary target."""
    values = [f"c{i:05d}" for i in range(k)] * rows_each
    return pd.DataFrame({"c": values, "y": [i % 2 for i in range(len(values))]})


@pytest.fixture
def threshold(monkeypatch):
    """Lower `WARN_ABOVE` to 40 categories, so a test learns few.

    The rule is tested, not the value: the value comes from the benchmark
    (20,000 categories, which would take minutes to learn here).
    """
    monkeypatch.setattr(_lookup, "WARN_ABOVE", 40)
    return 40


def lookup_warnings(run):
    """Return the lookup warnings `run` issues, every one recorded."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run()
    return [
        w
        for w in caught
        if issubclass(w.category, SqlearnWarning) and "lookup" in str(w.message)
    ]


def test_hash_and_list_give_the_same_positions():
    """1-based positions, NULL for a missing or absent value, from both forms."""
    categories = ["a", "it's", "", "ü", "c'est 'là'", *(f"k{i}" for i in range(300))]
    probes = [*categories, None, "absent", "A", "a "]
    rel = duckdb.sql("SELECT unnest($p) AS x", params={"p": probes})
    assert rel is not None
    x = duckdb.ColumnExpression("x")
    listed = rel.select(_lookup.position(x, categories, "list")).fetchall()
    hashed = rel.select(_lookup.position(x, categories, "hash")).fetchall()
    assert hashed == listed
    assert listed[: len(categories)] == [(i + 1,) for i in range(len(categories))]
    assert listed[len(categories) :] == [(None,)] * 4


def test_hash_finds_an_enum_value_as_its_text():
    """An ENUM column is hashed by its values' text, as listed."""
    rel = duckdb.sql(
        "SELECT x::ENUM('b', 'a', 'z') AS x FROM (VALUES ('a'), ('z'), (NULL)) t(x)"
    )
    assert rel is not None
    x = duckdb.ColumnExpression("x")
    hashed = rel.select(_lookup.position(x, ["a", "b"], "hash")).fetchall()
    assert hashed == rel.select(_lookup.position(x, ["a", "b"], "list")).fetchall()
    assert hashed == [(1,), (None,), (None,)]


@pytest.mark.parametrize("name", list(ENCODERS))
def test_hash_and_list_give_the_same_codes(name):
    """5,000 categories, quotes in some, NULL in the data, an unseen value."""
    make = ENCODERS[name]
    categories = [f"c{i:05d}" if i % 7 else f"it's {i}" for i in range(5_000)]
    train = pd.DataFrame(
        {
            "c": [*categories * 2, None, None],
            "y": [i % 3 == 0 for i in range(2 * len(categories) + 2)],
        }
    )
    test = pd.DataFrame(
        {"c": ["c00001", "it's 7", None, "unseen", "it''s 7", categories[-1]]}
    )
    out = {}
    for lookup in ("list", "hash"):
        pipe = sq.Pipeline([make("c", lookup=lookup)]).learn(train, target="y")
        out[lookup] = pipe.apply(test).fetchall()
    assert out["hash"] == out["list"]
    assert len({r[0] for r in out["list"]}) > 2


def test_hash_and_list_cross_fit_the_same_in_train():
    """train encodes each inner fold apart: both lookups give the same model."""
    rows = 600
    data = pd.DataFrame(
        {
            "c": [f"it's {i % 150}" if i % 11 else None for i in range(rows)],
            "y": [(i * 7) % 3 == 0 for i in range(rows)],
        }
    )
    predicted = {}
    for lookup in ("list", "hash"):
        model = sq.Pipeline(
            [sq.encode.target("c", lookup=lookup), ("model", LogisticRegression())]
        ).train(data, target="y")
        predicted[lookup] = model.predict(data, out="pandas")
    assert predicted["hash"].equals(predicted["list"])


@pytest.mark.parametrize("name", list(ENCODERS))
def test_many_categories_warn_when_lookup_is_left_out(name, threshold):
    """One SqlearnWarning naming the step, the count and lookup="hash"."""
    step = ENCODERS[name]("c")
    pipe = sq.Pipeline([step])
    caught = lookup_warnings(lambda: pipe.learn(many(threshold + 1), target="y"))
    assert len(caught) == 1
    text = str(caught[0].message)
    assert repr(step) in text
    assert f"{threshold + 1:,} categories" in text
    assert 'lookup="hash"' in text
    assert "Why:" in text
    assert "Fix:" in text
    assert caught[0].filename == __file__


@pytest.mark.parametrize("name", list(ENCODERS))
def test_as_many_categories_as_the_threshold_do_not_warn(name, threshold):
    """The warning is for more than WARN_ABOVE categories."""
    pipe = sq.Pipeline([ENCODERS[name]("c")])
    assert lookup_warnings(lambda: pipe.learn(many(threshold), target="y")) == []


@pytest.mark.parametrize("name", list(ENCODERS))
@pytest.mark.parametrize("lookup", ["list", "hash"])
def test_an_explicit_lookup_never_warns(name, lookup, threshold):
    """Either value passed is a choice, and a choice is never warned about."""
    pipe = sq.Pipeline([ENCODERS[name]("c", lookup=lookup)])
    data = many(threshold + 1)
    assert lookup_warnings(lambda: pipe.learn(data, target="y")) == []


@pytest.mark.parametrize("name", list(ENCODERS))
def test_the_lookup_warning_shows_once_in_a_search(name, threshold):
    """A 5-fold search warns once; learning the same step again says nothing."""
    data = many(threshold + 1, rows_each=5)
    pipe = sq.Pipeline([("enc", ENCODERS[name]("c")), ("model", LogisticRegression())])
    search = sq.search(pipe, params={"model__C": [0.5, 1.0]}, folds=sq.folds.kfold(5))
    assert len(lookup_warnings(lambda: search.train(data, target="y"))) == 1
    again = sq.Pipeline([ENCODERS[name]("c")])
    assert lookup_warnings(lambda: again.learn(data, target="y")) == []


@pytest.mark.parametrize("name", list(ENCODERS))
def test_hash_is_refused_on_a_column_that_is_not_text(name):
    """The MD5 hash reads text: a number column is refused in the house form."""
    data = pd.DataFrame({"n": [1, 2, 3, 4], "y": [0, 1, 0, 1]})
    pipe = sq.Pipeline([ENCODERS[name]("n", lookup="hash")])
    with pytest.raises(StepError, match=r"'n'.*BIGINT.*Why:.*Fix:.*lookup=\"list\""):
        pipe.learn(data, target="y")


@pytest.mark.parametrize("name", list(ENCODERS))
def test_list_still_takes_a_column_that_is_not_text(name):
    """lookup="list" looks numbers up as before."""
    data = pd.DataFrame({"n": [1, 2, 3, 4], "y": [0, 1, 0, 1]})
    pipe = sq.Pipeline([ENCODERS[name]("n", lookup="list")]).learn(data, target="y")
    assert len(pipe.apply(data).fetchall()) == 4


@pytest.mark.parametrize("name", list(ENCODERS))
@pytest.mark.parametrize("lookup", ["md5", "", "LIST", True])
def test_an_unknown_lookup_is_refused(name, lookup):
    """Only "list" and "hash" are lookups."""
    with pytest.raises(SqlearnError, match=r"lookup=.*Why:.*Fix:"):
        ENCODERS[name]("c", lookup=lookup)


def test_onehot_takes_no_lookup():
    """The general form refuses lookup= with onehot, which looks nothing up."""
    with pytest.raises(SqlearnError, match=r"lookup.*Fix:"):
        sq.encode("c", method="onehot", lookup="hash")


@pytest.mark.parametrize("name", list(ENCODERS))
def test_a_left_out_lookup_does_not_print_and_a_chosen_one_does(name):
    """The repr shows lookup only when it was passed."""
    make = ENCODERS[name]
    assert "lookup" not in repr(make("c"))
    assert (
        repr(make("c", lookup="list")) == f"sq.encode.{name}(cols='c', lookup='list')"
    )
    assert f"method={name!r}" not in repr(sq.encode("c", method=name, lookup="hash"))
    assert repr(sq.encode("c", method=name, lookup="hash")) == repr(
        make("c", lookup="hash")
    )


def test_hash_compares_bytes_and_ignores_a_collation():
    """DuckDB does not report a collation, so the hash compares bytes exactly."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t(c VARCHAR COLLATE NOCASE)")
    con.execute("INSERT INTO t VALUES ('a'), ('b')")
    con.execute("CREATE TABLE u(c VARCHAR COLLATE NOCASE)")
    con.execute("INSERT INTO u VALUES ('A'), ('b')")
    sq.set_config(connection=con)
    codes = {}
    for lookup in ("list", "hash"):
        pipe = sq.Pipeline([sq.encode.ordinal("c", lookup=lookup)])
        codes[lookup] = pipe.learn(con.table("t")).apply(con.table("u")).fetchall()
    assert codes == {"list": [(0,), (1,)], "hash": [(-1,), (1,)]}
