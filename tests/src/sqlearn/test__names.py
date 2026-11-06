"""Tests of the one naming rule for created columns (ADR 0035)."""

from sqlearn._names import name_columns


def test_a_label_follows_its_column():
    """A label gives ``<column>_<label>``; the empty label is the column."""
    assert name_columns([("city", "Oslo"), ("age", "")], []) == ["city_Oslo", "age"]


def test_clashes_are_numbered_in_sorted_order():
    """Names equal without regard to case are numbered in label order."""
    assert name_columns([("city", "oslo"), ("city", "Oslo"), ("city", "NULL")], []) == [
        "city_oslo_2",
        "city_Oslo",
        "city_NULL",
    ]


def test_an_input_column_is_never_renamed():
    """A name passing through keeps it; the created one is numbered."""
    assert name_columns([("city", "Oslo")], ["city_oslo"]) == ["city_Oslo_2"]


def test_equal_labels_keep_their_order():
    """Two equal labels are numbered in the order they were planned."""
    assert name_columns([("c", "NULL"), ("c", "NULL")], []) == ["c_NULL", "c_NULL_2"]


def test_a_number_already_in_use_is_skipped():
    """Numbering moves past a name that is already taken."""
    assert name_columns([("a", "x"), ("a", "X")], ["a_x_2"]) == ["a_x_3", "a_X"]


def test_the_column_itself_keeps_its_name():
    """The empty label sorts first, so a replaced input column is not renamed."""
    assert name_columns([("a", "b"), ("a_b", "")], []) == ["a_b_2", "a_b"]
