set shell := ["bash", "-euo", "pipefail", "-c"]

# The Python versions the package is tested on
matrix := "3.12 3.13 3.14"

# MathJax 4 and its font package (released together, one version), from the npm registry, with sha512 integrities
mathjax_version := "4.1.3"
mathjax_integrity := "sha512-BN/8Pkgn7G1pIDYJqd9md+JHsE/jydSYbyOZnSdSA0WziuVO8mRxdYiWFumkVVly/8U+hm9DpIIoWuvySverzw=="
font_integrity := "sha512-gzAB3dFHilHX1l5x2xUqRL+1jDQt3Fyza1DkEMVXWC4E8SvsGdlgEza47HYi2WhVcgfkvf4zgUGzuhbq3Pjlew=="

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

# The flags that select the tests a change affects, and run them in parallel
affected := "--testmon --testmon-forceselect -n auto"

# Print 16 hex digits: the SHA-256 of the files a test run depends on besides code
[group('test')]
test-env root=".":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{ root }}"
    {
        printf '%s\n' uv.lock .python-version pyproject.toml justfile
        find . -mindepth 1 \( -name '.*' -o -name node_modules \) -prune -o -name conftest.py -print | sed 's|^\./||'
        find devdata/data -type f 2>/dev/null || true
    } | LC_ALL=C sort -u | while IFS= read -r f; do
        printf '%s\0' "$f"
        if [ -f "$f" ]; then cat "$f"; fi
        printf '\0'
    done | shasum -a 256 | cut -c1-16

# Run the fast tests a change affects, in parallel, without coverage
[group('test')]
test:
    #!/usr/bin/env bash
    set -euo pipefail
    rc=0
    uv run --locked pytest {{ affected }} --testmon-env="'$(just test-env)'" --ignore=tests/githooks || rc=$?
    # 5 means the change affected no test: nothing to run is success
    [ "$rc" -eq 5 ] && exit 0
    exit "$rc"

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

# Copy MathJax's CHTML output and its fonts into docs/_static/mathjax
[group('docs')]
fetch-mathjax:
    #!/usr/bin/env bash
    set -euo pipefail
    dest=docs/_static/mathjax
    stamp=$(printf '%s\n' "{{ mathjax_version }}" "{{ mathjax_integrity }}" "{{ font_integrity }}")
    if [ -f "$dest/.pinned" ] && [ "$(cat "$dest/.pinned")" = "$stamp" ]; then
        echo "MathJax {{ mathjax_version }} is already in $dest, skipped"
        exit 0
    fi
    # Inside docs/_static, so the final move stays on one filesystem.
    tmp=$(mktemp -d docs/_static/.mathjax.XXXXXX)
    trap 'rm -rf "$tmp"' EXIT
    fetch() {
        curl --fail --location --silent --show-error --output "$tmp/$1.tgz" \
            "https://registry.npmjs.org/$2/-/$3-{{ mathjax_version }}.tgz"
        actual=sha512-$(openssl dgst -sha512 -binary "$tmp/$1.tgz" | base64 | tr -d '\n')
        if [ "$actual" != "$4" ]; then
            echo "$2: integrity $actual does not match $4" >&2
            exit 1
        fi
        mkdir "$tmp/$1"
        tar -xzf "$tmp/$1.tgz" -C "$tmp/$1" --strip-components=1
    }
    fetch mathjax mathjax mathjax "{{ mathjax_integrity }}"
    fetch font @mathjax/mathjax-newcm-font mathjax-newcm-font "{{ font_integrity }}"
    test -f "$tmp/mathjax/tex-chtml.js"
    test -d "$tmp/font/chtml/woff2"
    out="$tmp/out"
    mkdir -p "$out/fonts/mathjax-newcm-font"
    cp "$tmp/mathjax/tex-chtml.js" "$tmp/mathjax/LICENSE" "$out/"
    cp -R "$tmp/mathjax/input" "$tmp/mathjax/ui" "$tmp/mathjax/a11y" "$out/"
    cp -R "$tmp/font/chtml" "$out/fonts/mathjax-newcm-font/"
    printf '%s\n' "$stamp" > "$out/.pinned"
    rm -rf "$dest" && mv "$out" "$dest"

# Build the site, then run the doctests, warnings as errors
[group('docs')]
build-docs: fetch-mathjax
    uv run --locked sphinx-build -W --keep-going -b html docs docs/_build/html
    uv run --locked sphinx-build -W --keep-going -b doctest docs docs/_build/doctest

# Remove build output, the matrix environments and tool caches
[group('maintain')]
clean:
    rm -rf dist docs/_build docs/examples docs/reference/generated docs/_static/mathjax
    rm -rf .venvs .ruff_cache .mypy_cache .rumdl_cache .coverage .coverage.* htmlcov

# Check that every module has its test, and every step and metric its validation
[group('check')]
check-mirror:
    #!/usr/bin/env bash
    set -euo pipefail
    missing=0
    while IFS= read -r f; do
        rel=${f#src/sqlearn/}
        dir=$(dirname "$rel")
        name=$(basename "$rel" .py)
        [ "$name" = "__init__" ] && continue
        [ "$dir" = "." ] && sub="" || sub="$dir/"
        test="tests/src/sqlearn/${sub}test_${name}.py"
        if [ ! -f "$test" ]; then
            echo "missing: $test (for $f)"
            missing=1
        fi
        case "$dir" in
            agg|agg/*|preprocessing|preprocessing/*|metrics|metrics/*|decomposition|decomposition/*)
                case "$name" in _*) continue ;; esac
                val="validation/sqlearn/${sub}validate_${name}.py"
                if [ ! -f "$val" ]; then
                    echo "missing: $val (for $f)"
                    missing=1
                fi
                ;;
            feature_selection|feature_selection/*)
                # One runner validates every selector of sq.select.
                case "$name" in _*) continue ;; esac
                val="validation/sqlearn/feature_selection/validate_select.py"
                if [ ! -f "$val" ]; then
                    echo "missing: $val (for $f)"
                    missing=1
                fi
                ;;
        esac
    done < <(find src/sqlearn -name '*.py' | sort)
    exit $missing

# Run the checks that run on every commit
[group('check')]
check: lint-python check-types lint-markdown check-spelling check-mirror

# Run what the pre-commit hook runs
[group('check')]
pre-commit: check check-lockfile

# Run every test and every validation runner, writing their results as JSON under validation/
[group('test')]
validate:
    uv run --locked pytest -m "" -q -p validation._tests_report --ignore=tests/githooks
    uv run --locked python -m validation

# Run every check, for review, merge and release
[group('check')]
verify: check check-types-mypy test-python-versions test-hooks check-docstrings validate build-docs
