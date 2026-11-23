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
# A default's repr may hold its address (``<object object at 0x...>``),
# which changes from run to run.
_ADDRESS = re.compile(r"\b0x[0-9a-f]+\b")


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
    return _ADDRESS.sub("0x...", "\n".join(lines) + "\n")


if __name__ == "__main__":
    RECORD.write_text(render(), encoding="utf-8")
    sys.stdout.write(f"wrote {RECORD}\n")
