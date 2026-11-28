"""Check a release wheel (``just check-wheel <wheel>``).

A release has one wheel per platform of ADR 0062 that the workflow builds
(macOS 15 on arm64, manylinux_2_28 on x86_64 and aarch64), each CPython
3.12's stable ABI (``cp312-abi3``), serving every Python from 3.12. A sound
wheel holds ``sqlearn/``, ``duckdb/`` and one ``_duckdb`` module; abi3audit
finds no call outside the stable ABI in it; and installed in an environment
of its own it imports, answers ``sq.version()`` with its own version, and
has DuckDB's official extensions loaded without the network (ADR 0006,
0061).

``--installed`` checks a wheel already installed in this Python
(cibuildwheel's test step); without it the wheel is installed in an
environment of uv's, made for the check and thrown away.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

NAME = re.compile(
    r"^sqlearn-(?P<version>[^-]+)-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl$"
)
"""A wheel's file name: the distribution, version and its three tags."""

MANYLINUX = re.compile(r"^manylinux_2_(\d+)_(x86_64|aarch64)$")
"""One manylinux tag: its glibc minor version and its architecture."""

GLIBC_FLOOR = 28
"""manylinux_2_28: the oldest glibc the Linux wheels run on."""

FIX = (
    "Fix: build the wheel with just build-package (macOS) or the release "
    "workflow's cibuildwheel (Linux), from a clean checkout"
)

SMOKE = """
import sys
import duckdb
import sqlearn as sq

version = sys.argv[1]
said = sq.version()
if not said.startswith(f"sqlearn {version}"):
    sys.exit(f"sq.version() is {said!r}, not sqlearn {version}")
loaded = {
    row[0]
    for row in duckdb.connect().execute(
        "SELECT extension_name FROM duckdb_extensions() WHERE loaded"
    ).fetchall()
}
missing = {"core_functions", "json", "parquet", "icu"} - loaded
if missing:
    sys.exit(f"DuckDB's extensions {sorted(missing)} are not loaded")
"""
"""Run in the wheel's environment, with its version as the one argument."""


def _platform_ok(platform: str) -> bool:
    """Whether `platform` is one a release ships."""
    if platform == "macosx_15_0_arm64":
        return True
    found = [MANYLINUX.match(part) for part in platform.split(".")]
    if not all(found):
        return False
    return any(int(m.group(1)) == GLIBC_FLOOR for m in found if m) and all(
        int(m.group(1)) <= GLIBC_FLOOR for m in found if m
    )


def static_findings(name: str, members: tuple[str, ...]) -> list[str]:
    """What is wrong with the wheel named `name` holding `members`.

    Parameters
    ----------
    name : str
        The wheel's file name.
    members : tuple of str
        The paths in it.

    Returns
    -------
    list of str
        One line per finding; empty when its name and contents are sound.
    """
    findings = []
    tags = NAME.match(name)
    if tags is None:
        findings.append(f"{name} is not a sqlearn wheel's name")
    elif (tags["python"], tags["abi"]) != ("cp312", "abi3") or not _platform_ok(
        tags["platform"]
    ):
        findings.append(
            f"{name} is not tagged cp312-abi3 for macosx_15_0_arm64 or "
            f"manylinux_2_{GLIBC_FLOOR} (x86_64, aarch64)"
        )
    modules = [m for m in members if re.fullmatch(r"_duckdb\.[^/]*(so|pyd)", m)]
    if len(modules) != 1:
        findings.append(f"{name} holds {len(modules)} _duckdb modules, not one")
    for package in ("sqlearn/__init__.py", "duckdb/__init__.py"):
        if package not in members:
            findings.append(f"{name} has no {package}")
    return findings


def _abi3audit(wheel: Path) -> list[str]:
    """abi3audit's findings on `wheel`: calls outside the stable ABI."""
    done = subprocess.run(
        [sys.executable, "-m", "abi3audit", "--strict", str(wheel)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode == 0:
        return []
    return [f"abi3audit: {line}" for line in (done.stdout + done.stderr).splitlines()]


def _smoke(wheel: Path, version: str, *, installed: bool) -> list[str]:
    """Import the wheel's sqlearn in its own environment and run `SMOKE`."""
    if installed:
        command = [sys.executable, "-c", SMOKE, version]
    else:
        command = [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--with",
            str(wheel.resolve()),
            "python",
            "-c",
            SMOKE,
            version,
        ]
    # Outside the checkout, so nothing of it is imported instead of the wheel.
    with tempfile.TemporaryDirectory() as away:
        done = subprocess.run(
            command, cwd=away, capture_output=True, text=True, check=False
        )
    if done.returncode == 0:
        return []
    return [f"installed: {line}" for line in done.stderr.strip().splitlines()]


def asset_stem(name: str) -> str:
    """Return the release name of the map beside the wheel named `name`.

    Parameters
    ----------
    name : str
        The wheel's file name.

    Returns
    -------
    str
        ``sqlearn-<version>-<platform>``; of a manylinux wheel's compressed
        tags, the newest.
    """
    tags = NAME.match(name)
    if tags is None:
        raise ValueError(f"{name} is not a sqlearn wheel's name")
    platform = tags["platform"].split(".")[-1]
    return f"sqlearn-{tags['version']}-{platform}"


def _build_line(wheel: Path) -> str:
    """The build line of `wheel`'s sqlearn, installed in an environment of uv's."""
    with tempfile.TemporaryDirectory() as away:
        done = subprocess.run(
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--with",
                str(wheel.resolve()),
                "python",
                "-c",
                "from sqlearn import _native; print(_native.describe())",
            ],
            cwd=away,
            capture_output=True,
            text=True,
            check=True,
        )
    return done.stdout.strip()


def _assets(wheel: Path, linker_map: Path, out: Path) -> int:
    """Copy `linker_map` into `out` under its release name, its build line beside it."""
    stem = asset_stem(wheel.name)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(linker_map, out / f"{stem}.map")
    (out / f"{stem}.map.build").write_text(f"{_build_line(wheel)}\n", encoding="utf-8")
    print(f"{out / stem}.map and .map.build")  # noqa: T201
    return 0


def main(argv: list[str]) -> int:
    """Check the wheel `argv[-1]`; print each finding.

    Parameters
    ----------
    argv : list of str
        ``[wheel]``, or ``["--installed", wheel]`` for a wheel already
        installed in this Python; or ``["--assets", wheel, map, out]`` to
        write the release's map and build line (`asset_stem`) into ``out``.

    Returns
    -------
    int
        0 when the wheel is sound, 1 otherwise (with a ``Fix:`` line).
    """
    if argv[:1] == ["--assets"] and len(argv) == 4:
        return _assets(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    installed = argv[:1] == ["--installed"]
    if installed:
        argv = argv[1:]
    if len(argv) != 1:
        print("Fix: just check-wheel <the wheel's path>")  # noqa: T201
        return 1
    wheel = Path(argv[0])
    with zipfile.ZipFile(wheel) as archive:
        members = tuple(archive.namelist())
    findings = static_findings(wheel.name, members)
    if not findings:
        tags = NAME.match(wheel.name)
        version = tags["version"] if tags else ""
        findings = _abi3audit(wheel) + _smoke(wheel, version, installed=installed)
    for finding in findings:
        print(finding)  # noqa: T201
    if findings:
        print(FIX)  # noqa: T201
        return 1
    print(f"{wheel.name}: sound")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
