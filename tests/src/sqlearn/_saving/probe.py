"""Objects whose attribute access records itself, so a test can see code run.

A saved file may name any path into an imported module: looking a class up
must not touch ``__class__``, a metaclass ``__getattr__`` or a
``__getattribute__`` of what the path reaches.
"""

calls: list[str] = []


class _Proxy:
    """A lazy proxy: reading ``__class__`` resolves it, as wrapt's does."""

    @property  # type: ignore[misc]
    def __class__(self) -> type:
        calls.append("__class__")
        return type(self)


proxy = _Proxy()


class _Meta(type):
    def __getattr__(cls, name: str) -> object:
        calls.append(f"getattr {name}")
        raise AttributeError(name)

    def __getattribute__(cls, name: str) -> object:
        calls.append(f"getattribute {name}")
        return super().__getattribute__(name)


class Thing(metaclass=_Meta):
    """A class that is no step, model or estimator, with a recording metaclass."""
