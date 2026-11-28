"""The release wheel: one abi3 wheel per platform, built in isolation, holding
sqlearn, its DuckDB and the one module."""

import tomllib
import zipfile
from pathlib import Path

import pytest

from validation import _wheel

REPO = Path(__file__).resolve().parents[2]

GOOD = (
    "sqlearn/__init__.py",
    "sqlearn/_native.pyi",
    "duckdb/__init__.py",
    "_duckdb.abi3.so",
    "sqlearn-0.1.dev9.dist-info/METADATA",
)


def _wheel_file(tmp_path: Path, name: str, members: tuple[str, ...]) -> Path:
    """A zip named `name` holding `members`, each empty."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, "")
    return path


def test_cibuildwheel_builds_one_abi3_wheel_in_isolation():
    """Linux's wheels: CPython 3.12's abi3 wheel alone, manylinux_2_28, no musl,
    built by pypa/build (isolated: it reads no [tool.uv]), and each one checked
    by check-wheel in the environment cibuildwheel installed it into."""
    table = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["cibuildwheel"]
    assert table["build"] == "cp312-*"
    assert table["skip"] == "*-musllinux_*"
    assert table["build-frontend"] == "build"
    assert table["manylinux-x86_64-image"] == "manylinux_2_28"
    assert table["manylinux-aarch64-image"] == "manylinux_2_28"
    assert table["test-command"] == "python -m validation._wheel --installed {wheel}"
    assert "validation" in table["test-sources"]
    assert "abi3audit" in " ".join(table["test-requires"])


def test_check_wheel_refuses_a_wheel_without_the_module(tmp_path, capsys):
    """No _duckdb binary: no sqlearn to run."""
    wheel = _wheel_file(
        tmp_path,
        "sqlearn-0.1.dev9-cp312-abi3-macosx_15_0_arm64.whl",
        tuple(m for m in GOOD if not m.startswith("_duckdb")),
    )
    assert _wheel.main([str(wheel)]) == 1
    out = capsys.readouterr().out
    assert "_duckdb" in out
    assert "Fix:" in out


def test_check_wheel_refuses_two_modules(tmp_path, capsys):
    """Two _duckdb binaries: which one loads depends on the platform."""
    wheel = _wheel_file(
        tmp_path,
        "sqlearn-0.1.dev9-cp312-abi3-macosx_15_0_arm64.whl",
        (*GOOD, "_duckdb.cpython-312-darwin.so"),
    )
    assert _wheel.main([str(wheel)]) == 1
    assert "Fix:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "name",
    [
        "sqlearn-0.1.dev9-cp313-cp313-macosx_15_0_arm64.whl",
        "sqlearn-0.1.dev9-cp312-abi3-macosx_14_0_arm64.whl",
        "sqlearn-0.1.dev9-cp312-abi3-macosx_15_0_x86_64.whl",
        "sqlearn-0.1.dev9-cp312-abi3-linux_x86_64.whl",
    ],
)
def test_check_wheel_refuses_a_wheel_not_tagged_for_release(tmp_path, capsys, name):
    """Not cp312-abi3 on macOS 15 arm64 or manylinux: refused, naming the tag."""
    wheel = _wheel_file(tmp_path, name, GOOD)
    assert _wheel.main([str(wheel)]) == 1
    out = capsys.readouterr().out
    assert name in out
    assert "Fix:" in out


@pytest.mark.parametrize(
    "name",
    [
        "sqlearn-0.1.dev9-cp312-abi3-macosx_15_0_arm64.whl",
        "sqlearn-0.1.dev9-cp312-abi3-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "sqlearn-0.1.dev9-cp312-abi3-manylinux_2_28_aarch64.whl",
    ],
)
def test_a_release_tag_passes_the_static_checks(name):
    """The three platforms' tags, the module and the packages there: no finding."""
    assert _wheel.static_findings(name, GOOD) == []


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        (
            "sqlearn-1.0.0-cp312-abi3-macosx_15_0_arm64.whl",
            "sqlearn-1.0.0-macosx_15_0_arm64",
        ),
        (
            "sqlearn-1.0.0-cp312-abi3-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
            "sqlearn-1.0.0-manylinux_2_28_x86_64",
        ),
    ],
)
def test_a_release_map_is_named_after_its_wheel(name, stem):
    """The map a release attaches says the version and the platform it is
    of, the newest manylinux tag for Linux's."""
    assert _wheel.asset_stem(name) == stem


def test_release_assets_copy_the_map_and_write_its_build_line(tmp_path, monkeypatch):
    """The map is copied under its release name, and its build line, the
    wheel's sq.version() installed, is written beside it."""
    wheel = _wheel_file(
        tmp_path, "sqlearn-1.0.0-cp312-abi3-macosx_15_0_arm64.whl", GOOD
    )
    linker_map = tmp_path / "_duckdb.map"
    linker_map.write_text("# Path: _duckdb.abi3.so\n")
    out = tmp_path / "out"
    monkeypatch.setattr(
        _wheel, "_build_line", lambda path: "sqlearn 1.0.0, DuckDB 2.0.1"
    )
    assert _wheel.main(["--assets", str(wheel), str(linker_map), str(out)]) == 0
    stem = "sqlearn-1.0.0-macosx_15_0_arm64"
    assert (out / f"{stem}.map").read_text() == "# Path: _duckdb.abi3.so\n"
    assert (out / f"{stem}.map.build").read_text() == "sqlearn 1.0.0, DuckDB 2.0.1\n"
