"""Tests of ``sq.decompose``, its shortcut and its settings (spec §4, §4.1)."""

import pytest

import sqlearn as sq
from sqlearn._store import step_key
from sqlearn.decomposition import PCA
from sqlearn.errors import SqlearnError

DATA = ("table", "t", 1)


def key(name, step):
    """Return the store key of a one-step pipeline of `step`."""
    return step_key(DATA, None, [(name, step)], 0, frozenset())


@pytest.mark.parametrize(
    ("short", "general", "cls", "text"),
    [
        (
            sq.decompose.pca(n_components=3),
            sq.decompose(method="pca", n_components=3),
            PCA(n_components=3),
            "sq.decompose.pca(n_components=3)",
        ),
        (
            sq.decompose.pca(),
            sq.decompose(),
            PCA(),
            "sq.decompose.pca()",
        ),
        (
            sq.decompose.pca("a", "b", n_components=0.5, whiten=True),
            sq.decompose("a", "b", n_components=0.5, whiten=True),
            PCA(n_components=0.5, whiten=True, cols=["a", "b"]),
            "sq.decompose.pca(n_components=0.5, whiten=True, cols=['a', 'b'])",
        ),
    ],
)
def test_the_shortcut_is_the_general_form(short, general, cls, text):
    """The shortcut builds the step the class and the general form build."""
    assert type(short) is type(general) is type(cls) is PCA
    assert repr(short) == repr(general) == repr(cls) == text
    assert short.settings() == general.settings() == cls.settings()
    assert key("pca", short) == key("pca", general) == key("pca", cls)
    assert short.default_name() == "pca"


@pytest.mark.parametrize(
    "call",
    [
        lambda: sq.decompose.pca(n_components=-1),
        lambda: sq.decompose.pca(n_components=1.0),
        lambda: sq.decompose.pca(n_components="mle"),  # ty: ignore[invalid-argument-type]
        lambda: sq.decompose.pca(n_components=2.5),
        lambda: sq.decompose.pca(n_components=True),
        lambda: sq.decompose.pca(whiten="yes"),  # ty: ignore[invalid-argument-type]
        lambda: sq.decompose(method="svd"),
        lambda: sq.decompose.pca(3),
        lambda: sq.decompose("a", 0.5),
    ],
)
def test_the_group_refuses_bad_settings(call):
    """A setting out of range, an unknown method or a number positional is refused."""
    with pytest.raises(SqlearnError, match="Fix:"):
        call()


def test_a_number_positional_is_shown_as_its_setting():
    """A number given by position is refused, naming n_components."""
    with pytest.raises(SqlearnError, match=r"n_components=3"):
        sq.decompose.pca(3)
