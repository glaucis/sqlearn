"""The public API, one name per line, as ``tests/public_api.txt`` records it.

Every name in ``sq.__all__`` and in the ``__all__`` of each submodule it
lists, with its ``inspect.signature`` (spec §3.9). ``just api-snapshot``
writes the file; ``test_the_public_api_is_the_recorded_one`` compares. A
change to the public API changes the file, and its commit says why (ADR
0003, 0067).
"""

import inspect
import re
import sys
from pathlib import Path
from types import ModuleType

RECORD = Path(__file__).with_name("public_api.txt")
# What differs between runs or Python versions, and its one spelling here: a
# default's address (``<object object at 0x...>``), pathlib's module
# (``pathlib._local`` from 3.13), and ``typing.`` before a name (3.14 drops it).
_SAME = (
    (re.compile(r"\b0x[0-9a-f]+\b"), "0x..."),
    (re.compile(r"\bpathlib\._local\."), "pathlib."),
    (re.compile(r"\btyping\."), ""),
)


def _line(qualified: str, value: object) -> str:
    """Return `qualified` with its signature, or its type when it has none."""
    if callable(value):
        try:
            return f"{qualified}{inspect.signature(value)}"
        except (TypeError, ValueError):
            pass
    return f"{qualified}: {type(value).__name__}"


def render() -> str:
    """Return the public API of the imported ``sqlearn``, one line a name."""
    import sqlearn

    lines = []
    for name in sorted(sqlearn.__all__):
        value = getattr(sqlearn, name)
        if isinstance(value, ModuleType):
            lines.append(f"sqlearn.{name}: module")
            for inner in sorted(getattr(value, "__all__", ())):
                lines.append(_line(f"sqlearn.{name}.{inner}", getattr(value, inner)))
        else:
            lines.append(_line(f"sqlearn.{name}", value))
    text = "\n".join(lines) + "\n"
    for pattern, spelling in _SAME:
        text = pattern.sub(spelling, text)
    return text


if __name__ == "__main__":
    RECORD.write_text(render(), encoding="utf-8")
    sys.stdout.write(f"wrote {RECORD}\n")
