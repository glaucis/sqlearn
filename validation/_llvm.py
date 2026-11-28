"""Where LLVM's tools are: one prefix for every check that runs them.

The prefix is ``SQ_LLVM_ROOT`` when it is set, else Homebrew's for the host
(the formula is keg-only, so its tools are off ``PATH``), as
``engine/cmake/toolchain-llvm.cmake`` and the justfile's ``llvm`` find it.
"""

import os
import sys
from pathlib import Path

HOMEBREW = {
    "darwin": Path("/opt/homebrew/opt/llvm"),
    "linux": Path("/home/linuxbrew/.linuxbrew/opt/llvm"),
}
"""Homebrew's LLVM prefix on each host."""


def root() -> Path:
    """Return LLVM's prefix, the directory holding ``bin/clang++``."""
    if named := os.environ.get("SQ_LLVM_ROOT"):
        return Path(named)
    return HOMEBREW.get(sys.platform, HOMEBREW["linux"])


def bin_dir() -> Path:
    """Return the directory of LLVM's programs."""
    return root() / "bin"
