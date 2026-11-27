"""A module with a lazy ``__getattr__`` that records each call, as PEP 562 allows."""

calls: list[str] = []


def __getattr__(name: str) -> object:
    calls.append(name)
    raise AttributeError(name)
