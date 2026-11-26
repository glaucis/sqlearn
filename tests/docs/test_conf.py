"""Tests of docs/conf.py, the Sphinx configuration."""

import re
import runpy
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def duckdb_floor_major():
    """Return the major version of the DuckDB sqlearn builds, from the pins.

    DuckDB is built into the wheel, not a dependency, so its version is
    `SQ_DUCKDB_TAG` in engine/cmake/pins.cmake (``v2.0.1`` gives 2).
    """
    pins = (REPO / "engine" / "cmake" / "pins.cmake").read_text()
    found = re.search(r'^set\(SQ_DUCKDB_TAG "v(\d+)\.\d+\.\d+"\)', pins, re.M)
    if found:
        return int(found.group(1))
    raise AssertionError("engine/cmake/pins.cmake sets no `SQ_DUCKDB_TAG`")


def test_the_duckdb_intersphinx_url_names_the_floors_major_version():
    """DuckDB's docs path names a release, so it moves with the pinned tag.

    The major version is read from `SQ_DUCKDB_TAG` in engine/cmake/pins.cmake.
    """
    conf = runpy.run_path(str(REPO / "docs" / "conf.py"))
    url = conf["intersphinx_mapping"]["duckdb"][0]
    found = re.match(r"https://duckdb\.org/docs/(\d+)\.\d+/", url)
    assert found, f"the duckdb intersphinx URL names no release: {url}"
    floor = duckdb_floor_major()
    assert int(found.group(1)) == floor, (
        f"docs/conf.py points intersphinx at {url}, but SQ_DUCKDB_TAG in "
        f"engine/cmake/pins.cmake is major version {floor}: update the URL to "
        f"https://duckdb.org/docs/{floor}.<minor>/clients/python/reference/, "
        f"and the one in the justfile's fetch-inventories, then run "
        f"`just fetch-inventories`"
    )


def test_the_justfile_fetches_the_same_duckdb_inventory():
    """`just fetch-inventories` must fetch from the URL conf.py links to."""
    conf = runpy.run_path(str(REPO / "docs" / "conf.py"))
    url = conf["intersphinx_mapping"]["duckdb"][0]
    justfile = (REPO / "justfile").read_text()
    fetched = re.findall(r"https://duckdb\.org/docs/\S+", justfile)
    assert fetched, "the justfile fetches no duckdb inventory"
    assert all(f == f"{url}objects.inv" for f in fetched), (
        f"the justfile fetches {fetched}, but docs/conf.py links to {url}: "
        f"make the justfile fetch {url}objects.inv"
    )
