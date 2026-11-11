"""The trained model's own file: the formats `sq.save` can write it in.

A model's trained state belongs to its library and is not JSON, so it goes in
a file beside the pipeline's, by a format from `FORMATS`. Only ``"pickle"`` is
built; a later format (a library's own file, or one that loads without running
code) is one more entry, with no change to the JSON. See
``docs/specs/library-saving.md``, section 8.
"""

import pickle
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = ["FORMATS", "ModelFormat"]


@dataclass(frozen=True)
class ModelFormat:
    """One way to write a trained estimator to a file and read it back.

    Attributes
    ----------
    suffix : str
        The model file's suffix, in place of the JSON's
        (``churn.sqlearn.json`` gives ``churn.sqlearn.model.pickle``).
    save : callable
        ``save(estimator, path)`` writes the estimator to `path`.
    load : callable
        ``load(content)`` returns the estimator from the file's bytes. It is
        handed the bytes whose SHA-256 was checked, never a path, so the file
        cannot change between the check and the load.
    runs_code : bool
        Whether loading can run code the file's author chose; such a file is
        opened only with ``trust_model=True``.

    Examples
    --------
    >>> from sqlearn._saving.models import FORMATS
    >>> FORMATS["pickle"].suffix, FORMATS["pickle"].runs_code
    ('.model.pickle', True)
    """

    suffix: str
    save: Callable[[object, Path], None]
    load: Callable[[bytes], object]
    runs_code: bool


def _save_pickle(estimator: object, path: Path) -> None:
    with path.open("wb") as out:
        pickle.dump(estimator, out, protocol=5)


def _load_pickle(content: bytes) -> object:
    # Reached only with trust_model=True and the content's SHA-256 checked.
    return pickle.loads(content)


FORMATS: dict[str, ModelFormat] = {
    "pickle": ModelFormat(".model.pickle", _save_pickle, _load_pickle, runs_code=True),
}
