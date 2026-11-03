set shell := ["bash", "-euo", "pipefail", "-c"]

# The Python versions the package is tested on
matrix := "3.12 3.13 3.14"

# List the recipes
default:
    @just --list

# Point git at .githooks and install the locked environment
[group('setup')]
setup:
    git config core.hooksPath .githooks
    uv sync --locked

# Apply ruff's safe fixes, then format the Python
[group('format')]
fmt-python:
    uv run --locked ruff check --fix-only
    uv run --locked ruff format

# Wrap the Markdown prose at 80 columns
[group('format')]
fmt-markdown:
    uv run --locked rumdl fmt .

# Format the Python, then the Markdown
[group('format')]
fmt: fmt-python fmt-markdown

# Lint and check the formatting of the Python
[group('check')]
lint-python:
    uv run --locked ruff check
    uv run --locked ruff format --check

# Type-check with ty
[group('check')]
check-types:
    uv run --locked ty check

# Type-check src/ with mypy, strict
[group('check')]
check-types-mypy:
    uv run --locked mypy

# Lint the Markdown
[group('check')]
lint-markdown:
    uv run --locked rumdl check .

# Check the spelling
[group('check')]
check-spelling:
    uv run --locked typos

# Check that uv.lock matches pyproject.toml
[group('check')]
check-lockfile:
    uv lock --check

# Run the fast tests with coverage
[group('test')]
test:
    uv run --locked pytest --cov --ignore=tests/githooks

# Run the hook tests
[group('test')]
test-hooks:
    uv run --locked pytest tests/githooks -m ""

# Run every test with coverage
[group('test')]
test-all:
    uv run --locked pytest --cov -m ""

# Run the package's tests on every Python in the matrix
[group('test')]
test-python-versions:
    #!/usr/bin/env bash
    set -euo pipefail
    for v in {{ matrix }}; do
        UV_PROJECT_ENVIRONMENT=.venvs/py$v uv run --locked --python $v pytest -m "" --ignore=tests/githooks
    done

# Validate the docstrings under src/ with numpydoc
[group('check')]
check-docstrings:
    uv run --locked numpydoc lint $(git ls-files 'src/*.py')

# Build the sdist and the wheel into dist/
[group('build')]
build-package:
    uv build

# Upgrade the locked dependencies, then verify
[group('maintain')]
upgrade-dependencies:
    uv lock --upgrade
    just fetch-inventories
    just verify

# Download Python's and DuckDB's intersphinx inventories into docs/_inventories
[group('docs')]
fetch-inventories:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p docs/_inventories
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    fetch() {
        curl --fail --location --silent --show-error --output "$tmp/$1.inv" "$2"
        uv run --locked python -m sphinx.ext.intersphinx "$tmp/$1.inv" >/dev/null
        mv "$tmp/$1.inv" "docs/_inventories/$1.inv"
    }
    fetch python https://docs.python.org/3/objects.inv
    fetch duckdb https://duckdb.org/docs/2.0/clients/python/reference/objects.inv

# Build the site, then run the doctests, warnings as errors
[group('docs')]
build-docs:
    uv run --locked sphinx-build -W --keep-going -b html docs docs/_build/html
    uv run --locked sphinx-build -W --keep-going -b doctest docs docs/_build/doctest

# Remove build output, the matrix environments and tool caches
[group('maintain')]
clean:
    rm -rf dist docs/_build docs/examples docs/reference/generated docs/_static/mathjax
    rm -rf .venvs .ruff_cache .mypy_cache .rumdl_cache .coverage .coverage.* htmlcov

# Run the checks that run on every commit
[group('check')]
check: lint-python check-types lint-markdown check-spelling

# Run what the pre-commit hook runs
[group('check')]
pre-commit: check check-lockfile

# Run every check, for review, merge and release
[group('check')]
verify: check check-types-mypy test-python-versions test-hooks check-docstrings build-docs
