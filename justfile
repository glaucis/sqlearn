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

# Run the hook tests
[group('test')]
test-hooks:
    uv run --locked pytest tests/githooks -m ""

# Run every test with coverage, and write the slow tier's entries in tests.json
[group('test')]
test-all:
    uv run --locked pytest --cov -m "" -p validation._tests_report

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

# Compare each docstring under src/, or in the files named, with its signature (pydoclint); DOC111, types written in the docstring, is numpydoc's own style and is not a finding
[group('check')]
[positional-arguments]
check-docstring-args *files:
    #!/usr/bin/env bash
    set -uo pipefail
    [ $# -gt 0 ] || set -- src
    out=$(uv run --locked pydoclint "$@" 2>&1)
    rc=$?
    # 0 = clean, 1 = findings; anything else is pydoclint itself failing
    if [ $rc -gt 1 ]; then printf '%s\n' "$out"; exit $rc; fi
    # every line naming a DOC code other than DOC111 is a finding, printed under its file
    bad=$(printf '%s\n' "$out" | awk '/^src\// {f=$0} /DOC[0-9]+/ && !/DOC111/ {print f ": " $0}')
    if [ -n "$bad" ]; then printf '%s\n' "$bad"; exit 1; fi
    # a failure with no DOC line at all is an error, not a pass
    if [ $rc -eq 1 ] && ! grep -q 'DOC111' <<<"$out"; then printf '%s\n' "$out"; exit 1; fi

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

# Build the site, then run the doctests, warnings as errors; every page is read again (--fresh-env), since an incremental build repeats no warning of a page it did not reread
[group('docs')]
build-docs: fetch-mathjax
    uv run --locked sphinx-build -W --keep-going --fresh-env -b html docs docs/_build/html
    uv run --locked sphinx-build -W --keep-going --fresh-env -b doctest docs docs/_build/doctest

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

# Refuse "devdata" in any module of the package (ADR 0053), test_the_package_holds_no_datasets's rule on every commit
[group('check')]
check-no-devdata:
    #!/usr/bin/env bash
    set -euo pipefail
    rc=0
    found=$(grep -rn --include='*.py' devdata src/sqlearn) || rc=$?
    # 1 = no line found, the pass; 2 = grep itself failed, which is not a pass
    if [ $rc -gt 1 ]; then exit $rc; fi
    if [ $rc -eq 0 ]; then
        printf '%s\n' "$found"
        echo "src/ names devdata/, which never ships (ADR 0053): move what uses it out of src/."
        exit 1
    fi

# Run the checks that run on every commit
[group('check')]
check: lint-python check-types lint-markdown check-spelling check-mirror check-docstring-args check-no-devdata

# Run what the pre-commit hook runs
[group('check')]
pre-commit: check check-lockfile

# Rerun each validation runner whose imported files changed since a passed run
[group('test')]
validate:
    uv run --locked python -m validation

# Rerun every validation runner, recorded or not (at a release)
[group('test')]
validate-all:
    uv run --locked python -m validation --all

# How a task runs only when its inputs changed; SQLEARN_CHECKS replaces it, as the recipes' tests do in a scratch repository
checks := env("SQLEARN_CHECKS", "uv run --locked python -m validation._checks")

# Check the formatting of the Python and Markdown files changed since a passed run
[group('check')]
format:
    {{ checks }} format

# Lint the Python, the spelling and the Markdown of the files changed since a passed run
[group('check')]
lint:
    {{ checks }} lint

# Validate the docstrings of the files under src/ changed since a passed run (numpydoc, pydoclint)
[group('check')]
docstrings:
    {{ checks }} docstrings

# Type-check with ty, then mypy strict, when a Python file changed since a passed run
[group('check')]
types:
    {{ checks }} types

# Run the tests when what they read changed since a passed run: the fast ones in parallel, the serial ones, the slow tier, the hooks; tests.json is merged
[group('test')]
test:
    {{ checks }} test

# Build the site and run its doctests when docs/, src/ or examples/ changed since a passed run
[group('docs')]
docs:
    {{ checks }} docs

# Run one check all through, whatever its record says, and record its pass (validation/_checks.py); `validate` runs every runner (validate-all), its records being its own
[group('check')]
full task:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ task }}" = validate ]; then
        exec "{{ just_executable() }}" --justfile "{{ justfile() }}" validate-all
    fi
    {{ checks }} "{{ task }}" --all

# Print the tree of HEAD when only Markdown the tests do not read and the checks' outputs differ from it, and nothing otherwise
[group('check')]
checkable-tree:
    #!/usr/bin/env bash
    set -euo pipefail
    # the checks' own outputs are never inputs (OUTPUTS in validation/_checks.py), and Markdown is not one either: they may differ from HEAD
    outputs=(':(exclude,glob)validation/**/*.results.json' ':(exclude)validation/tests.json' ':(exclude)validation/environment.json')
    skip=(':(exclude)*.md' "${outputs[@]}")
    # what the test task reads is an input whatever its kind, a Markdown file a test reads included; the list is the task's own
    list=$({{ checks }} --declared)
    if [ -z "$list" ]; then echo "checkable-tree: no declared files listed" >&2; exit 1; fi
    declared=()
    while IFS= read -r spec; do declared+=("$spec"); done <<<"$list"
    declared+=("${outputs[@]}")
    if git diff --quiet HEAD -- . "${skip[@]}" &&
        git diff --quiet HEAD -- "${declared[@]}" &&
        [ -z "$(git ls-files --others --exclude-standard -- . "${skip[@]}")" ] &&
        [ -z "$(git ls-files --others --exclude-standard -- "${declared[@]}")" ]; then
        git rev-parse 'HEAD^{tree}'
    fi

# Remember a tree the checks passed on, when it is still the checkable tree
[group('check')]
remember-tree tree:
    #!/usr/bin/env bash
    set -euo pipefail
    before="{{ tree }}"
    file="$(git rev-parse --git-common-dir)/sqlearn-passed"
    if [ -z "$before" ] || [ "$before" != "$(just --justfile '{{ justfile() }}' checkable-tree)" ]; then
        printf '\nNot remembered: a file other than Markdown differed from the last commit, or the commit changed, while the checks ran. Commit, then run this again.\n'
        exit 0
    fi
    if ! grep -qx "$before" "$file" 2>/dev/null; then
        printf '%s\n' "$before" >> "$file"
        tail -n 50 "$file" > "$file.new" && mv "$file.new" "$file"
    fi
    printf '\nChecked tree %s: remembered.\n' "$before"

# Run the checks and what a change affects (fast, slow and hook tests, runners), unless this tree already passed, and remember the tree
[group('check')]
done:
    #!/usr/bin/env bash
    set -euo pipefail
    j=(just --justfile '{{ justfile() }}')
    tree="$("${j[@]}" checkable-tree)"
    if [ -n "$tree" ] && grep -qx "$tree" "$(git rev-parse --git-common-dir)/sqlearn-passed" 2>/dev/null; then
        echo "Tree $tree already passed: nothing to run."
        exit 0
    fi
    "${j[@]}" check
    "${j[@]}" test
    "${j[@]}" validate
    "${j[@]}" remember-tree "$tree"

# Run every check and every test: the release tier, by hand before 1.0.0
[group('check')]
verify:
    #!/usr/bin/env bash
    set -euo pipefail
    j=(just --justfile '{{ justfile() }}')
    tree="$("${j[@]}" checkable-tree)"
    "${j[@]}" check check-types-mypy test-all test-python-versions test-hooks check-docstrings validate-all build-docs
    "${j[@]}" remember-tree "$tree"
