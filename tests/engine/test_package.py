"""The sqlearn package: the bindings alone, until the C++ brings the rest."""

import sqlearn as sq


def test_the_package_gives_only_the_bindings_names():
    """sqlearn gives its version, its errors and version(), nothing else."""
    assert sq.__all__ == ["__version__", "errors", "version"]


def test_an_internal_error_is_a_sqlearn_error():
    """The class the bindings raise for a broken precondition."""
    assert issubclass(sq.errors.InternalError, sq.errors.SqlearnError)


def test_the_public_api_is_the_recorded_one():
    """Every public name and signature is tests/public_api.txt.

    A change to the API rewrites it with `just api-snapshot`, committed
    with the change.
    """
    from tests import public_api

    assert public_api.render() == public_api.RECORD.read_text(encoding="utf-8")
