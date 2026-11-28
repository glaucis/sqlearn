"""The fuzz corpus's cap (``just fuzz``).

Each ``just fuzz`` merges the inputs it found into the committed corpus,
``engine/fuzz/corpus/<target>/``, which every build replays. A corpus may
hold at most :data:`MAX_FILES` files and :data:`MAX_BYTES` bytes, so it
cannot grow without anyone seeing: the repository keeps every file in its
history, each test run replays all of them, and the replay program takes
each file on its command line. The recipe passes :data:`MAX_LEN` to
libFuzzer as ``-max_len``, so no input it writes is longer.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_FILES = 500
"""The most files one target's corpus holds."""

MAX_BYTES = 1_048_576
"""The most bytes one target's corpus holds, its files together."""

MAX_LEN = 4096
"""The longest input libFuzzer makes (``-max_len``): the corpus's largest
file when the cap was set."""


def problems(corpus: Path) -> list[str]:
    """Return what makes `corpus`, one target's directory, break the cap.

    Each problem names the target, what it holds against the cap, and the
    fix.
    """
    files = sorted(p for p in corpus.iterdir() if p.is_file())
    size = sum(p.stat().st_size for p in files)
    target = corpus.name
    fix = (
        f"Fix: keep only the inputs that add coverage: run "
        f"engine/build/fuzzing/fuzz/fuzz_{target} -merge=1 <an empty directory> "
        f"engine/fuzz/corpus/{target}, then replace engine/fuzz/corpus/{target}'s "
        "files with that directory's and commit them"
    )
    found = []
    if len(files) > MAX_FILES:
        found.append(
            f"fuzz corpus {target} holds {len(files)} files, at most {MAX_FILES}. {fix}"
        )
    if size > MAX_BYTES:
        found.append(
            f"fuzz corpus {target} holds {size} bytes, at most {MAX_BYTES}. {fix}"
        )
    return found


def main(argv: list[str]) -> int:
    """Check each corpus directory in `argv`; print its problems.

    Returns:
        0 when every corpus keeps the cap, 1 otherwise.
    """
    found = [p for corpus in argv for p in problems(Path(corpus))]
    for problem in found:
        print(problem)  # noqa: T201
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
