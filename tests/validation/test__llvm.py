"""One LLVM prefix for the checks: SQ_LLVM_ROOT, else Homebrew's."""

import re
import sys
from pathlib import Path

import pytest

from validation import _llvm

REPO = Path(__file__).resolve().parents[2]


def test_the_llvm_prefix_is_taken_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQ_LLVM_ROOT, when set, is the prefix and its bin/ the tools."""
    monkeypatch.setenv("SQ_LLVM_ROOT", "/usr/lib/llvm-23")
    assert _llvm.root() == Path("/usr/lib/llvm-23")
    assert _llvm.bin_dir() == Path("/usr/lib/llvm-23/bin")


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", "/opt/homebrew/opt/llvm"),
        ("linux", "/home/linuxbrew/.linuxbrew/opt/llvm"),
    ],
)
def test_without_the_variable_the_prefix_is_homebrews_for_the_host(
    monkeypatch: pytest.MonkeyPatch, platform: str, expected: str
) -> None:
    """Unset or empty, the prefix is Homebrew's on that host."""
    monkeypatch.setenv("SQ_LLVM_ROOT", "")
    monkeypatch.setattr(sys, "platform", platform)
    assert _llvm.root() == Path(expected)


def test_no_check_names_homebrews_llvm_but_this_module() -> None:
    """Every other module asks _llvm, so one variable moves them all."""
    literal = re.compile(r"/opt/homebrew/opt/llvm")
    named = sorted(
        path.name
        for path in (REPO / "validation").glob("*.py")
        if path.name != "_llvm.py" and literal.search(path.read_text())
    )
    assert named == []
