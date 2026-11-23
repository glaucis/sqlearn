"""sqlearn's engine: the C++ compiled into DuckDB's ``_duckdb`` binary.

The binary holds two modules, DuckDB's ``_duckdb`` and sqlearn's
``_native``. :func:`load` loads the second from the file of the first and
binds its functions here, so ``from sqlearn._native import count_rows``
works once ``sqlearn`` is imported. ``_native.pyi`` lists them.
"""

from importlib.machinery import ExtensionFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from types import ModuleType

_REFUSAL = (
    "sqlearn cannot start: its engine is not in the duckdb module.\n"
    "Why: the duckdb module is not sqlearn's build ({path})\n"
    "Fix: uv sync --reinstall-package sqlearn\n"
    "sqlearn ships its own DuckDB as the duckdb module; another package "
    "installed the official duckdb over it. A package that needs the official "
    "duckdb needs an environment of its own, apart from sqlearn's (ADR 0061)."
)


def load(path: str) -> ModuleType:
    """Load the engine from `path`, DuckDB's binary, and bind its functions here.

    Parameters
    ----------
    path : str
        The file of the ``_duckdb`` module, imported first.

    Returns
    -------
    ModuleType
        The engine module, ``sqlearn._native`` in the binary.

    Raises
    ------
    ImportError
        When the file holds no engine: the duckdb module is not sqlearn's
        build. The message has ``Why:`` and ``Fix:`` lines; the loader's own
        error is its cause.

    Examples
    --------
    >>> import _duckdb
    >>> from sqlearn import _native
    >>> _native.load(_duckdb.__file__).__name__
    'sqlearn._native'
    """
    name = __name__
    loader = ExtensionFileLoader(name, path)
    spec = spec_from_file_location(name, path, loader=loader)
    try:
        if spec is None:  # pragma: no cover - a path always gives a spec here
            msg = f"no module spec for {path}"
            raise ImportError(msg)
        module = module_from_spec(spec)
        loader.exec_module(module)
    except ImportError as exc:
        raise ImportError(_REFUSAL.format(path=path)) from exc
    globals().update(
        {key: value for key, value in vars(module).items() if not key.startswith("_")}
    )
    return module
