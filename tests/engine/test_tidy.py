"""clang-tidy refuses what ADR 0065 forbids outside the raw layer, the raw
layer relaxes only its pointer rules, and every header compiles alone."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from validation import _llvm

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"
LLVM = _llvm.bin_dir()
CASES = ENGINE / "tests" / "must_not_pass_tidy"

# A finding's check, as clang-tidy names it at the end of the line.
FINDING = re.compile(
    r"(?:warning|error): .* \[([a-z0-9.-]+)(?:,-warnings-as-errors)?\]$"
)


def _clang_tidy() -> Path:
    """Return Homebrew LLVM's clang-tidy, or skip when it is not installed."""
    tidy = LLVM / "clang-tidy"
    if not tidy.exists():
        pytest.skip("Homebrew LLVM's clang-tidy is needed: just doctor")
    return tidy


def _sdk() -> list[str]:
    """Return the -isysroot flags for macOS's SDK, or none elsewhere."""
    xcrun = shutil.which("xcrun")
    if xcrun is None:
        return []
    sdk = subprocess.run(
        [xcrun, "--show-sdk-path"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return ["-isysroot", sdk]


def _tidy(source: Path, *flags: str) -> tuple[int, set[str], str]:
    """Run clang-tidy on `source` with the engine's configuration.

    Returns its exit code, the checks it names and its output.
    """
    done = subprocess.run(
        [
            str(_clang_tidy()),
            *flags,
            str(source),
            "--",
            "-std=c++23",
            *_sdk(),
            f"-I{ENGINE / 'src'}",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    out = done.stdout + done.stderr
    checks = {
        str(m.group(1)) for line in out.splitlines() if (m := FINDING.search(line))
    }
    return done.returncode, checks, out


def test_a_raw_new_fails_tidy():
    """A raw new and delete outside engine/src/raw/ is a finding, and the only one."""
    code, checks, out = _tidy(CASES / "raw_new.cpp")
    assert code != 0, out
    assert checks == {"cppcoreguidelines-owning-memory"}, out


def test_pointer_arithmetic_outside_raw_fails_tidy():
    """Pointer arithmetic outside engine/src/raw/ is a finding, and the only one."""
    code, checks, out = _tidy(CASES / "pointer_arithmetic.cpp")
    assert code != 0, out
    assert checks == {"cppcoreguidelines-pro-bounds-pointer-arithmetic"}, out


def _enabled(source: Path) -> set[str]:
    """Return the checks clang-tidy runs on `source`, by the configuration it finds."""
    done = subprocess.run(
        [str(_clang_tidy()), "--list-checks", str(source), "--"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in done.stdout.splitlines()[1:] if line.strip()}


def test_the_raw_layer_relaxes_only_its_pointer_checks():
    """engine/src/raw/ runs every check the rest does but the pointer bounds
    and reinterpret_cast, and those run everywhere else."""
    relaxed = {
        "cppcoreguidelines-pro-type-reinterpret-cast",
        "cppcoreguidelines-pro-bounds-pointer-arithmetic",
    }
    elsewhere = _enabled(ENGINE / "src" / "core" / "error.cpp")
    raw = _enabled(ENGINE / "src" / "raw" / "buffer.cpp")
    off_in_raw = elsewhere - raw
    assert raw <= elsewhere
    assert relaxed <= off_in_raw
    assert all(
        c == "cppcoreguidelines-pro-type-reinterpret-cast"
        or c.startswith("cppcoreguidelines-pro-bounds-")
        for c in off_in_raw
    ), off_in_raw


def _headers() -> set[str]:
    """Return every header under engine/src, as git lists them, relative to it."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.hpp"],
        cwd=ENGINE / "src",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return set(out.split())


def test_every_header_compiles_alone(tmp_path):
    """The headers-alone target has one unit per header under engine/src,
    each including its header alone (twice, so a missing guard fails)."""
    script = tmp_path / "list.cmake"
    script.write_text(
        f'include("{ENGINE / "cmake" / "headers_alone.cmake"}")\n'
        f'sq_headers_alone_sources("{ENGINE / "src"}" "{tmp_path / "units"}" units)\n'
        'foreach(unit IN LISTS units)\n  message(STATUS "unit ${unit}")\nendforeach()\n'
    )
    if shutil.which("cmake") is None:
        pytest.skip("cmake is needed: just doctor")
    done = subprocess.run(
        ["cmake", "-P", str(script)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
    units = [
        Path(line.split("unit ", 1)[1])
        for line in (done.stdout + done.stderr).splitlines()
        if "-- unit " in line
    ]
    headers = _headers()
    assert headers, "no header found under engine/src"
    assert {
        u.relative_to(tmp_path / "units").with_suffix(".hpp").as_posix() for u in units
    } == headers
    for unit in units:
        header = unit.relative_to(tmp_path / "units").with_suffix(".hpp").as_posix()
        lines = [line for line in unit.read_text().splitlines() if line.startswith("#")]
        assert lines == [f'#include "{header}"'] * 2, unit
