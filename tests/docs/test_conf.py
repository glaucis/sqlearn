"""Tests of docs/conf.py, the Sphinx configuration."""

import re
import runpy
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def duckdb_floor_major():
    """Return the major version of the duckdb floor in pyproject.toml."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    for requirement in project["dependencies"]:
        found = re.fullmatch(r"duckdb\s*>=\s*(\d+)(\.\d+)*", requirement.strip())
        if found:
            return int(found.group(1))
    raise AssertionError("pyproject.toml has no `duckdb>=` floor")


def test_the_duckdb_intersphinx_url_names_the_floors_major_version():
    """DuckDB's docs path names a release, so it must move when the floor does."""
    conf = runpy.run_path(str(REPO / "docs" / "conf.py"))
    url = conf["intersphinx_mapping"]["duckdb"][0]
    found = re.match(r"https://duckdb\.org/docs/(\d+)\.\d+/", url)
    assert found, f"the duckdb intersphinx URL names no release: {url}"
    floor = duckdb_floor_major()
    assert int(found.group(1)) == floor, (
        f"docs/conf.py points intersphinx at {url}, but the duckdb floor in "
        f"pyproject.toml is major version {floor}: update the URL to "
        f"https://duckdb.org/docs/{floor}.<minor>/clients/python/reference/, "
        f"and the one in the justfile's fetch-inventories, then run "
        f"`just fetch-inventories`"
    )
