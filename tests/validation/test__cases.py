"""The validation's shared pieces: error measures, judging, datasets, JSON."""

import math
from fractions import Fraction

import mpmath

from validation import _cases


def test_ulps_counts_one_step_to_the_next_double():
    """The next double after 1.0 is one ULP away, in either order."""
    after = math.nextafter(1.0, 2.0)
    assert _cases.ulps(1.0, after) == 1
    assert _cases.ulps(after, 1.0) == 1


def test_ulps_across_zero_and_equal_values():
    """-0.0 and 0.0 are one point; the smallest values either side are 2 apart."""
    tiny = math.nextafter(0.0, 1.0)
    assert _cases.ulps(-0.0, 0.0) == 0
    assert _cases.ulps(-tiny, tiny) == 2
    assert _cases.ulps(3.5, 3.5) == 0


def test_nearest_rounds_the_exact_value_to_a_double():
    """A third rounds to the double nearest it, from a Fraction or an mpf."""
    assert _cases.nearest(Fraction(1, 3)) == 1 / 3
    with mpmath.workdps(50):
        assert _cases.nearest(mpmath.mpf(1) / 3) == 1 / 3


def mean_of_one(reference, value, bound):
    """A case of the mean on the small set, whose exact answer is 1."""
    return _cases.case(
        step="scale",
        formula="mean",
        dataset="small",
        rows=4,
        type="DOUBLE",
        reference=reference,
        value=value,
        exact=Fraction(1),
        bound=bound,
    )


def test_a_sqlearn_case_outside_its_bound_fails():
    """sqlearn three ULPs from the canonical value, with a bound of 2, fails."""
    value = 1.0
    for _ in range(3):
        value = math.nextafter(value, 2.0)
    got = mean_of_one("sqlearn", value, 2)
    assert got["result"] == "fail"
    assert got["ulps"] == 3
    got = mean_of_one("sqlearn", value, 4)
    assert got["result"] == "pass"


def test_a_reference_far_off_is_an_anomaly_not_a_fail():
    """A library far outside the bound is an anomaly; only sqlearn can fail."""
    got = mean_of_one("numpy", 1.0 + 2**-40, 1)
    assert got["result"] == "anomaly"
    assert got["ulps"] == 2**12
    near = math.nextafter(1.0, 2.0)
    got = mean_of_one("numpy", near, 1)
    assert got["result"] == "pass"


def test_a_case_records_every_field():
    """A case carries what a page needs (ADR 0025), its errors measured."""
    got = mean_of_one("sqlearn", 1.0, 1)
    assert set(got) >= {
        "step",
        "formula",
        "dataset",
        "rows",
        "type",
        "reference",
        "abs_error",
        "rel_error",
        "ulps",
        "bound_ulps",
        "result",
        "note",
    }
    assert (got["abs_error"], got["rel_error"], got["ulps"]) == (0.0, 0.0, 0)


def test_a_skipped_reference_is_recorded_with_its_reason():
    """A reference that cannot run is kept as "skipped", never dropped."""
    got = _cases.skipped(
        step="scale",
        formula="mean",
        dataset="empty",
        rows=0,
        type="DOUBLE",
        reference="scikit-learn",
        note="no rows",
        bound=1,
    )
    assert got["result"] == "skipped"
    assert got["note"] == "no rows"
    assert got["ulps"] is None


def test_datasets_are_the_same_on_every_call():
    """The datasets come from seed 0: two calls give the same values."""
    first = _cases.numbers()
    second = _cases.numbers()
    assert [d.name for d in first] == [
        "small",
        "medium",
        "large",
        "null",
        "nan",
        "empty",
        "single",
        "reserved",
    ]
    assert [len(d.values) for d in first][:3] == [4, 1_000, 100_000]
    assert repr(first) == repr(second)


def test_json_is_byte_identical_across_runs(tmp_path):
    """The same results write the same bytes, sorted, with no bare NaN."""
    data = {"b": [1.5, math.nan, math.inf, -math.inf], "a": {"z": 1, "y": None}}
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    _cases.write_json(one, data)
    _cases.write_json(two, data)
    text = one.read_text()
    assert one.read_bytes() == two.read_bytes()
    assert text.endswith("}\n")
    assert '"NaN"' in text and '"Infinity"' in text and '"-Infinity"' in text
    assert text.index('"a"') < text.index('"b"')
