set shell := ["bash", "-euo", "pipefail", "-c"]

# The Python versions the package is tested on
matrix := "3.12 3.13 3.14"

# Homebrew LLVM's tools (clang-tidy, clang-format): the formula is keg-only, so they are off PATH
llvm := "/opt/homebrew/opt/llvm/bin"

# MathJax 4 and its font package (released together, one version), from the npm registry, with sha512 integrities
mathjax_version := "4.1.3"
mathjax_integrity := "sha512-BN/8Pkgn7G1pIDYJqd9md+JHsE/jydSYbyOZnSdSA0WziuVO8mRxdYiWFumkVVly/8U+hm9DpIIoWuvySverzw=="
font_integrity := "sha512-gzAB3dFHilHX1l5x2xUqRL+1jDQt3Fyza1DkEMVXWC4E8SvsGdlgEza47HYi2WhVcgfkvf4zgUGzuhbq3Pjlew=="

# Mull (mutation testing, development only), from its GitHub release for macOS arm64: the runner, and the frontend plugin for LLVM 23, with their sha256 digests
mull_version := "0.39.1"
mull_runner_sha256 := "2ffeb4d0d91199c4c7588b26f018e70a057b2fd784f01421bcbdea0592106e3b"
mull_plugin_sha256 := "73521db507f6483b01cb72a263f7c3079164b34c77a771fbc873d87df7ba04bd"

# List the recipes
default:
    @just --list

# Check the C++ toolchain: each tool, its version, and the brew line for a missing one
[group('setup')]
doctor:
    #!/usr/bin/env bash
    set -euo pipefail
    missing=0
    check() { # formula, command, version argument
        local found
        if [ "$1" = llvm ]; then
            found=/opt/homebrew/opt/llvm/bin/clang
            [ -x "$found" ] || found=
        else
            found=$(command -v "$2" 2>/dev/null || true)
        fi
        if [ -z "$found" ]; then
            echo "missing $1"
            echo "Fix: brew install $1"
            missing=1
        else
            echo "$1: $("$found" $3 2>&1 | head -n 1)"
        fi
    }
    check cmake cmake --version
    check ninja ninja --version
    check ccache ccache --version
    check llvm clang --version
    check include-what-you-use include-what-you-use --version
    check gitleaks gitleaks version
    exit "$missing"

# Write engine/.compiler-stamp, the C++ compiler's --version (CXX, else c++) and the SDK's, when it changed: one of uv's cache keys (pyproject.toml), so the next uv run rebuilds the module after a compiler update; rewritten only on a change, since uv keys a file on its modification time
[group('setup')]
compiler-stamp:
    #!/usr/bin/env bash
    set -euo pipefail
    stamp=engine/.compiler-stamp
    mkdir -p engine
    new=$(mktemp)
    trap 'rm -f "$new"' EXIT
    ${CXX:-c++} --version > "$new" 2>&1 || echo "no compiler: ${CXX:-c++}" > "$new"
    if command -v xcrun > /dev/null; then
        echo "sdk $(xcrun --show-sdk-version 2>/dev/null || echo none)" >> "$new"
    fi
    if ! cmp -s "$new" "$stamp"; then
        mv "$new" "$stamp"
    fi

# Point git at .githooks, check the toolchain (a missing tool is reported, and the rest still runs), fetch the submodules and build the locked environment; exits 1 when a tool is missing
[group('setup')]
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    "{{ just_executable() }}" --justfile "{{ justfile() }}" compiler-stamp
    git config core.hooksPath .githooks
    doctor=0
    "{{ just_executable() }}" --justfile "{{ justfile() }}" doctor || doctor=$?
    git submodule update --init --recursive
    uv sync --locked
    exit "$doctor"

# Apply ruff's safe fixes, then format the Python
[group('format')]
fmt-python:
    uv run --locked ruff check --fix-only
    uv run --locked ruff format

# Wrap the Markdown prose at 80 columns
[group('format')]
fmt-markdown:
    uv run --locked rumdl fmt .

# Format our C++ (clang-format, engine/.clang-format) and CMake files (gersemi, .gersemirc); the submodules are other repositories, so git lists none of their files
[group('format')]
fmt-engine:
    #!/usr/bin/env bash
    set -euo pipefail
    git ls-files -z --cached --others --exclude-standard -- '*.cpp' '*.hpp' | xargs -0 {{ llvm }}/clang-format -i
    git ls-files -z --cached --others --exclude-standard -- ':(glob)**/CMakeLists.txt' ':(glob)**/*.cmake' | xargs -0 uv run --locked gersemi -i

# Format the Python, the Markdown, then the C++ and CMake files
[group('format')]
fmt: fmt-python fmt-markdown fmt-engine

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

# Build the wheel, sqlearn with its DuckDB inside, into dist/, from the git checkout whose submodules sq_check_pins() reads; the sdist is left to step 3's release work
[group('build')]
build-package:
    uv build --wheel

# Configure and build sqlearn's C++ groups and their test programs with a preset (dev, debug, release, profile, llvm-dev) into engine/build/<preset>
[group('build')]
build-engine preset="dev":
    cd engine && cmake --preset {{ preset }}
    cd engine && cmake --build --preset {{ preset }} --parallel

# Build a preset's C++ groups, then run their tests and the must-not-compile tests with CTest
[group('test')]
test-engine preset="dev": (build-engine preset)
    cd engine && ctest --preset {{ preset }}

# Build a preset, then run each C++ group's tests whose program changed since they passed (validation/_ctest.py); --all runs every group; `just test` runs it on dev
[group('test')]
test-engine-changed preset="dev" *flags:
    uv run --locked python -m validation._ctest {{ preset }} {{ flags }}

# Build DuckDB's unittest with the sqlearn extension (the sqllogic preset, minutes the first time), then run engine/extension/test/sql/*.test when the program or a test file changed since they passed; --all runs them whatever the record; `just sql` runs this when its inputs changed
[group('test')]
test-sql *flags:
    uv run --locked python -m validation._ctest sqllogic {{ flags }}

# Fuzz each target for `seconds` (libFuzzer on the fuzzing preset, Homebrew LLVM) on a scratch copy of its corpus, then merge the new inputs into engine/fuzz/corpus/<target>/; a crash, leak, out-of-memory or timeout input is kept there, named, and fails
[group('test')]
fuzz seconds="60":
    #!/usr/bin/env bash
    set -euo pipefail
    cd engine
    cmake --preset fuzzing
    cmake --build --preset fuzzing
    scratch="$(mktemp -d)"
    trap 'rm -rf "$scratch"' EXIT
    kinds=(-name 'crash-*' -o -name 'leak-*' -o -name 'oom-*' -o -name 'timeout-*')
    for target in parse_version; do
        corpus="fuzz/corpus/$target"
        binary="build/fuzzing/fuzz/fuzz_$target"
        work="$scratch/$target/corpus"
        found="$scratch/$target/found"
        mkdir -p "$work" "$found"
        # the corpus's inputs, not the failures kept from an earlier run
        find "$corpus" -maxdepth 1 -type f ! \( "${kinds[@]}" \) -exec cp {} "$work"/ \;
        code=0
        "$binary" -max_total_time={{ seconds }} -timeout=10 -detect_leaks=0 \
            -artifact_prefix="$found/" "$work" || code=$?
        # libFuzzer writes each failing input under the prefix: this run's alone
        inputs="$(find "$found" -maxdepth 1 -type f \( "${kinds[@]}" \))"
        if [ "$code" -ne 0 ] && [ -z "$inputs" ]; then
            echo "fuzz_$target failed (exit $code) without writing an input: libFuzzer itself failed (its output is above)" >&2
            echo "Fix: run engine/$binary on engine/$corpus by hand to see why" >&2
            exit 1
        fi
        if [ -n "$inputs" ]; then
            echo "fuzz_$target failed (exit $code); its input is kept in engine/$corpus:" >&2
            while IFS= read -r input; do
                [ -n "$input" ] || continue
                cp "$input" "$corpus/"
                echo "  engine/$corpus/$(basename "$input")" >&2
            done <<<"$inputs"
            echo "Fix: the parser, then just test-engine dev runs it again" >&2
            exit 1
        fi
        "$binary" -merge=1 "$corpus" "$work"
    done

# Build each sanitizer preset and run every C++ group's tests and its canaries under it: dev (AddressSanitizer, UndefinedBehaviorSanitizer), tsan, lsan, tysan (validation/_ctest.py, --all); every preset runs, a failing one included, and the first failure's code is the exit
[group('test')]
sanitize:
    #!/usr/bin/env bash
    set -euo pipefail
    first=0
    for preset in dev tsan lsan tysan; do
        code=0
        uv run --locked python -m validation._ctest "$preset" --all || code=$?
        if [ "$first" -eq 0 ]; then first=$code; fi
    done
    exit "$first"

# Build the release preset (Apple clang) and run each group's test program, then again under macOS's leaks --atExit, which looks for memory no pointer reaches when the program ends; a failing program (its output shown), any leak, or no program found fails. test_crash is left out (below)
[group('test')]
leaks-engine: (build-engine "release")
    #!/usr/bin/env bash
    set -euo pipefail
    build=engine/build/release
    # test_crash forks a child for each case, and under leaks --atExit those
    # children hang until their alarm ends them, so its cases fail for the
    # tool's sake; its leaks are LeakSanitizer's (the lsan preset, just
    # sanitize). tests/engine/test_sanitizers.py pins that it alone is out.
    skip=(test_crash)
    programs=$(ctest --test-dir "$build" --show-only=json-v1 |
        uv run --locked python -c 'import json, sys; [print(t["command"][0]) for t in json.load(sys.stdin)["tests"] if t["name"].startswith("test_")]')
    if [ -z "$programs" ]; then
        echo "leaks-engine: no test_* program in $build: nothing was checked" >&2
        echo "Fix: configure $build with SQ_BUILD_TESTS on (cmake --preset release -DSQ_BUILD_TESTS=ON in engine/), then just leaks-engine" >&2
        exit 1
    fi
    out=$(mktemp)
    trap 'rm -f "$out"' EXIT
    first=0
    for program in $programs; do
        name=$(basename "$program")
        if printf '%s\n' "${skip[@]}" | grep -qx "$name"; then
            echo "leaks-engine: $name left out (its forked children hang under leaks)"
            continue
        fi
        code=0
        # leaks' exit says whether it found a leak, not whether the tests
        # passed: the program runs alone first.
        "$program" > "$out" 2>&1 || code=$?
        if [ "$code" -ne 0 ]; then
            cat "$out" >&2
        else
            /usr/bin/leaks --atExit -- "$program" || code=$?
        fi
        if [ "$code" -ne 0 ]; then
            echo "leaks-engine: $name failed or leaked (exit $code)" >&2
            if [ "$first" -eq 0 ]; then first=$code; fi
        fi
    done
    if [ "$first" -ne 0 ]; then
        echo "Fix: the failing tests, or free what the report names (RAII, ADR 0065), then just leaks-engine" >&2
    fi
    exit "$first"

# Build the coverage preset (Homebrew LLVM's source-based coverage), run every C++ test under it, print the line, region and branch coverage of engine/src outside bindings/, and fail below 95 % of lines (validation/_coverage.py)
[group('test')]
coverage-engine: (build-engine "coverage")
    uv run --locked python -m validation._coverage

# Audit the C++ groups' claims (validation/_audit.py): build the coverage wheel (sqlearn's C++ with source-based coverage, DuckDB not) into .venvs/coverage, measure a bare import, then each Python test set and validation runner a group claims, and fail when one ran a group outside its declared groups; a second DuckDB build, then up to an hour on every core
[group('test')]
audit-groups:
    #!/usr/bin/env bash
    set -euo pipefail
    export UV_PROJECT_ENVIRONMENT=.venvs/coverage SQLEARN_AUDIT_COVERAGE=1
    uv sync --locked --reinstall-package sqlearn
    # The audit's own process loads the module too: its profile goes apart,
    # never measured.
    rm -rf build/audit-self && mkdir -p build/audit-self
    LLVM_PROFILE_FILE="$PWD/build/audit-self/%p.profraw" uv run --locked python -m validation._audit

# Fetch Mull's runner and its LLVM 23 plugin into engine/build/mull/<version>/, checking their digests; skipped when they are there
[group('setup')]
fetch-mull:
    #!/usr/bin/env bash
    set -euo pipefail
    dest="engine/build/mull/{{ mull_version }}"
    if [ -x "$dest/bin/mull-runner" ] && [ -f "$dest/lib/mull-ir-frontend-23" ]; then
        exit 0
    fi
    if [ "$(uname -s)-$(uname -m)" != Darwin-arm64 ]; then
        echo "fetch-mull fetches Mull's macOS arm64 release; this is $(uname -s) $(uname -m)." >&2
        echo "Fix: install Mull {{ mull_version }} for LLVM 23 from https://github.com/mull-project/mull/releases into engine/build/mull/{{ mull_version }}/" >&2
        exit 1
    fi
    mkdir -p engine/build/mull
    tmp=$(mktemp -d engine/build/mull/.fetch.XXXXXX)
    trap 'rm -rf "$tmp"' EXIT
    release="https://github.com/mull-project/mull/releases/download/{{ mull_version }}"
    fetch() { # name, sha256
        curl --fail --location --silent --show-error --output "$tmp/$1" "$release/$1"
        actual=$(shasum -a 256 "$tmp/$1" | cut -d ' ' -f 1)
        if [ "$actual" != "$2" ]; then
            echo "$1: sha256 $actual does not match $2" >&2
            exit 1
        fi
        unzip -q -o "$tmp/$1" -d "$tmp/out"
    }
    fetch "Mull-{{ mull_version }}-macOS-aarch64-26.7.2.zip" "{{ mull_runner_sha256 }}"
    fetch "Mull-23-{{ mull_version }}-LLVM-23.1.4-macOS-aarch64-26.7.2.zip" "{{ mull_plugin_sha256 }}"
    rm -rf "$dest" && mv "$tmp/out" "$dest"

# Build the mutate preset (Mull's mutants compiled into our groups), run Mull on test_core and test_raw, and fail on a surviving mutant engine/mull.yml gives no reason for (validation/_mutate.py)
[group('test')]
mutate-engine: fetch-mull (build-engine "mutate")
    uv run --locked python -m validation._mutate "engine/build/mull/{{ mull_version }}/bin"

# Run clang-tidy, with the Clang static analyser, over our C++ (engine/.clang-tidy, every finding an error), from one compile database of the llvm-dev, release and wheel builds (validation/_tidy.py)
[group('check')]
tidy-engine:
    uv run --locked python -m validation._tidy tidy

# Run include-what-you-use over our C++ and headers, from the same compile database as tidy-engine, with engine/iwyu.imp's mappings
[group('check')]
iwyu-engine:
    uv run --locked python -m validation._tidy iwyu

# Build every header under engine/src alone (engine/cmake/headers_alone.cmake) on the llvm-dev preset; the bindings' headers build alone in the wheel's build
[group('check')]
headers-alone:
    cd engine && cmake --preset llvm-dev
    cd engine && cmake --build --preset llvm-dev --target sq_headers_alone

# Build the release preset and run the C++ benchmarks (nanobench), each printing its table
[group('test')]
bench-engine: (build-engine "release")
    engine/build/release/bench/bench_buffer

# List the benchmarks out of date (script or measured C++ groups changed since the last run) with their last time, cores and memory; runs none (ADR 0072)
[group('test')]
benchmarks-due:
    uv run --locked python -m validation._bench due

# Run one benchmark and record its time, cores, memory and load: only after Tomas's go-ahead, which names it, its time and its weight (ADR 0072)
[group('test')]
bench name:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{name}}" in bench_*) just build-engine release ;; esac
    uv run --locked python -m validation._bench run {{name}}

# Print which C++26 features each compiler on this machine has, by its __cpp_* macros (spec §3.8's table); rerun after each Xcode or compiler update
[group('maintain')]
probe-cxx26:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    cat > "$tmp/probe.cpp" <<'CPP'
    #include <cstdio>
    #include <version>
    #define SQ_STR2(x) #x
    #define SQ_STR(x) SQ_STR2(x)
    int main() {
        std::printf("%ld\n", static_cast<long>(__cplusplus));
    #if defined(__cpp_reflection)
        std::puts("__cpp_reflection " SQ_STR(__cpp_reflection));
    #elif defined(__cpp_impl_reflection)
        std::puts("__cpp_impl_reflection " SQ_STR(__cpp_impl_reflection));
    #else
        std::puts("no");
    #endif
    #if defined(__cpp_contracts)
        std::puts(SQ_STR(__cpp_contracts));
    #else
        std::puts("no");
    #endif
    #if defined(__cpp_lib_linalg)
        std::puts(SQ_STR(__cpp_lib_linalg));
    #else
        std::puts("no");
    #endif
    }
    CPP
    sdk=$(xcrun --show-sdk-path)
    names=() ; columns=()
    probe() { # name, compiler, flags...
        local name=$1 cxx=$2
        shift 2
        if ! command -v "$cxx" > /dev/null 2>&1; then return; fi
        local version
        version=$("$cxx" --version | head -n 1)
        if "$cxx" -std=c++26 "$@" "$tmp/probe.cpp" -o "$tmp/probe" 2> "$tmp/err"; then
            names+=("$name ($version)")
            columns+=("$("$tmp/probe" | paste -sd '|' -)")
        else
            names+=("$name ($version)")
            columns+=("compile failed: $(head -n 1 "$tmp/err")|||")
        fi
    }
    probe "Apple clang" clang++
    probe "Homebrew LLVM" /opt/homebrew/opt/llvm/bin/clang++ -isysroot "$sdk"
    for gcc in g++-16 gcc-16; do
        if command -v "$gcc" > /dev/null 2>&1; then
            [ "$gcc" = gcc-16 ] && set -- -lstdc++ || set --
            probe "GCC" "$gcc" "$@"
            probe "GCC, -freflection -fcontracts" "$gcc" -freflection -fcontracts "$@"
            break
        fi
    done
    row() { # label, field
        printf '| %s |' "$1"
        for c in "${columns[@]}"; do printf ' %s |' "$(cut -d '|' -f "$2" <<<"$c")"; done
        printf '\n'
    }
    printf '| |'; for n in "${names[@]}"; do printf ' %s |' "$n"; done; printf '\n'
    printf '|---|'; for n in "${names[@]}"; do printf -- '---|'; done; printf '\n'
    row "__cplusplus (-std=c++26)" 1
    row "Reflection" 2
    row "Contracts" 3
    row "std::linalg" 4

# Write src/sqlearn/_native.pyi from the built engine, with nanobind's stubgen (signatures only: a docstring stays on its function), formatted as ruff formats the package
[group('build')]
stubs:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    uv run --locked python -m nanobind.stubgen -q -D -m sqlearn._native -o "$tmp/raw.pyi"
    uv run --locked ruff format --stdin-filename src/sqlearn/_native.pyi < "$tmp/raw.pyi" > "$tmp/_native.pyi"
    mv "$tmp/_native.pyi" src/sqlearn/_native.pyi

# Check that src/sqlearn/_native.pyi is what `just stubs` writes from the built engine
[group('check')]
check-stubs:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    uv run --locked python -m nanobind.stubgen -q -D -m sqlearn._native -o "$tmp/raw.pyi"
    uv run --locked ruff format --stdin-filename src/sqlearn/_native.pyi < "$tmp/raw.pyi" > "$tmp/_native.pyi"
    if ! diff -u src/sqlearn/_native.pyi "$tmp/_native.pyi"; then
        echo "src/sqlearn/_native.pyi differs from the engine's stubs."
        echo "Fix: just stubs"
        exit 1
    fi

# Write tests/public_api.txt, the public API one name a line; commit it with the reason the API changed (ADR 0003, 0067)
[group('build')]
api-snapshot:
    uv run --locked python tests/public_api.py

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
    rm -rf dist docs/_build docs/_static/mathjax
    rm -rf .venvs .ruff_cache .mypy_cache .rumdl_cache .coverage .coverage.* htmlcov

# Refuse "devdata" in any module of the package (ADR 0053), on every commit
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
check: lint-python check-types lint-markdown check-spelling check-docstring-args check-no-devdata

# Refuse a secret (a key, a token, a password) in the files a commit holds: gitleaks over the directory when it has no .git (the hook's export of the index), else over an export of this checkout's index
[group('check')]
check-secrets:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -e .git ]; then
        gitleaks dir . --no-banner --no-color --redact --verbose --log-level warn
        exit
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    git checkout-index -a --prefix="$tmp/tree/"
    gitleaks dir "$tmp/tree" --no-banner --no-color --redact --verbose --log-level warn

# Check THIRD_PARTY.md and NOTICE against the wheel's last build: every library compiled in listed, every licence one ADR 0066 allows, numpy's too (validation/_licences.py); `just test` runs it as a test, since the hook's export has no build
[group('check')]
check-licences:
    uv run --locked python -m validation._licences

# Run what the pre-commit hook runs
[group('check')]
pre-commit: check check-lockfile check-secrets

# Rerun each validation runner whose imported files changed since a passed run
[group('test')]
validate:
    uv run --locked python -m validation

# Rerun every validation runner, recorded or not (at a release)
[group('test')]
validate-all:
    uv run --locked python -m validation --all

# How a task runs only when its inputs changed (the tasks' tests set it on a scratch repository)
checks := "uv run --locked python -m validation._checks"

# Check the formatting of the Python, Markdown, C++ and CMake files changed since a passed run
[group('check')]
format:
    {{ checks }} format

# Lint the Python, the spelling and the Markdown of the files changed since a passed run
[group('check')]
lint:
    {{ checks }} lint

# Check that every relative link and related: path in the tracked Markdown names a file (tests/docs/test_links.py), when a Markdown file changed since a passed run
[group('check')]
links:
    {{ checks }} links

# Validate the docstrings of the files under src/ changed since a passed run (numpydoc, pydoclint)
[group('check')]
docstrings:
    {{ checks }} docstrings

# Type-check with ty, then mypy strict, when a Python file changed since a passed run
[group('check')]
types:
    {{ checks }} types

# Run the tests that changed since a passed run: the C++ groups whose program changed (dev), then each Python test set whose identity changed (validation/_pytest_sets.py: the tooling tests, each group's, the unclaimed ones), its fast tests in parallel, the serial ones, the slow tier; tests.json is merged. Like done, it writes the compiler stamp first, so a compiler update rebuilds the module before anything is checked
[group('test')]
test: compiler-stamp
    {{ checks }} test

# Run the sqlearn extension's SQL tests (just test-sql) when the extension, our C++, the runner's build, DuckDB's pin or the compiler changed since a passed run
[group('test')]
sql:
    {{ checks }} sql

# Run clang-tidy, include-what-you-use and the headers-alone build when our C++, its settings or the submodules changed since a passed run, or one of the tools was upgraded
[group('check')]
tidy:
    {{ checks }} tidy

# Build the site and run its doctests when docs/, src/ or examples/ changed since a passed run
[group('docs')]
docs:
    {{ checks }} docs

# Run one check all through, whatever its record says, and record its pass (validation/_checks.py); `validate` runs every runner (validate-all), its records being its own. Like done, it writes the compiler stamp first, so a compiler update rebuilds the module before anything is checked
[group('check')]
full task: compiler-stamp
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{ task }}" = validate ]; then
        exec "{{ just_executable() }}" --justfile "{{ justfile() }}" validate-all
    fi
    {{ checks }} "{{ task }}" --all

# Print, for each check, whether `just done` would run it and why; runs no check. Like done, it writes the compiler stamp first, so a compiler update rebuilds the module before anything is read
[group('check')]
affected: compiler-stamp
    uv run --locked python -m validation._affected

# Run every check of just done in full and compare with what the selection chose; minutes to an hour, no benchmark. A check the selection called unchanged that fails is a missed rerun (exit 1); a pass is remembered with its date (validation/_sweep.py). Like done, it writes the compiler stamp first, so a compiler update rebuilds the module before anything is checked
[group('check')]
sweep: compiler-stamp
    uv run --locked python -m validation._sweep

# Print a warning when the last passed sweep is older than its cadence (CADENCE_DAYS in validation/_sweep.py) or missing; runs nothing
[group('check')]
sweep-stale:
    @uv run --locked python -m validation._sweep --stale

# Print the tree of HEAD when only the checks' own outputs differ from it, and nothing otherwise
[group('check')]
checkable-tree:
    #!/usr/bin/env bash
    set -euo pipefail
    # the checks' own outputs are never inputs (OUTPUTS in validation/_checks.py); any other change, Markdown included, is one
    skip=(':(exclude,glob)validation/**/*.results.json' ':(exclude)validation/tests.json' ':(exclude)validation/environment.json')
    if git diff --quiet HEAD -- . "${skip[@]}" &&
        [ -z "$(git ls-files --others --exclude-standard -- . "${skip[@]}")" ]; then
        git rev-parse 'HEAD^{tree}'
    fi

# Print the place the checks run in (Python, platform, machine), hashed: a tree passed in one place is checked again in another
[group('check')]
place:
    @{{ checks }} --place

# Remember a tree the checks passed on in a place, when both are still the checkable tree and today's place
[group('check')]
remember-tree tree place:
    #!/usr/bin/env bash
    set -euo pipefail
    j=(just --justfile '{{ justfile() }}')
    before="{{ tree }}"
    where="{{ place }}"
    file="$(git rev-parse --git-common-dir)/sqlearn-passed"
    if [ -z "$before" ] || [ "$before" != "$("${j[@]}" checkable-tree)" ]; then
        printf '\nNot remembered: a file other than an output of the checks differed from the last commit, or the commit changed, while the checks ran. Commit, then run this again.\n'
        exit 0
    fi
    if [ -z "$where" ] || [ "$where" != "$("${j[@]}" place)" ]; then
        printf '\nNot remembered: the place the checks run in (Python, platform, machine) changed while they ran. Run them again.\n'
        exit 0
    fi
    if ! grep -qx "$before $where" "$file" 2>/dev/null; then
        printf '%s %s\n' "$before" "$where" >> "$file"
        tail -n 50 "$file" > "$file.new" && mv "$file.new" "$file"
    fi
    printf '\nChecked tree %s: remembered.\n' "$before"

# Run every check on what changed since it passed (the instant ones, then each task), unless this tree already passed in this place; every one runs, a failing one included, and the first failure's code is the exit; then remember the tree and the place
[group('check')]
done:
    #!/usr/bin/env bash
    set -euo pipefail
    j=(just --justfile '{{ justfile() }}')
    # A compiler update rebuilds the module at the first uv run (its stamp is a cache key).
    "${j[@]}" compiler-stamp
    # Before anything uv runs: a stale lock would fail there with uv's error, not this check's.
    code=0
    "${j[@]}" check-lockfile || code=$?
    if [ "$code" -ne 0 ]; then exit "$code"; fi
    # The sweep's cadence: a warning only, which changes neither what runs nor the exit.
    "${j[@]}" sweep-stale || true
    tree="$("${j[@]}" checkable-tree)"
    place="$("${j[@]}" place)"
    if [ -n "$tree" ] && grep -qx "$tree $place" "$(git rev-parse --git-common-dir)/sqlearn-passed" 2>/dev/null; then
        echo "Tree $tree already passed: nothing to run."
        exit 0
    fi
    # every check runs whatever the others' exit, as each task's steps do, so one failure hides no other's findings
    first=0
    for check in check-no-devdata format lint links docstrings types tidy test sql validate docs; do
        code=0
        "${j[@]}" "$check" || code=$?
        if [ "$first" -eq 0 ]; then first=$code; fi
    done
    if [ "$first" -ne 0 ]; then exit "$first"; fi
    "${j[@]}" remember-tree "$tree" "$place"

# Run every check all through, whatever the records say (the steady-memory test in full test's slow tier), then the audit of the groups' claims, the sanitizers, the leak check of the release build, a minute of fuzzing, the C++ coverage gate, mutation testing, the licence check, and the tests with coverage and on every Python: the release tier, by hand before 1.0.0
[group('check')]
verify:
    #!/usr/bin/env bash
    set -euo pipefail
    j=(just --justfile '{{ justfile() }}')
    # A compiler update rebuilds the module at the first uv run (its stamp is a cache key).
    "${j[@]}" compiler-stamp
    # Before anything uv runs: a stale lock would fail there with uv's error, not this check's.
    "${j[@]}" check-lockfile
    tree="$("${j[@]}" checkable-tree)"
    place="$("${j[@]}" place)"
    "${j[@]}" check-no-devdata
    for task in format lint links docstrings types tidy test sql validate docs; do
        "${j[@]}" full "$task"
    done
    # After validate-all (full validate): the groups' claims, by coverage.
    "${j[@]}" audit-groups
    "${j[@]}" sanitize leaks-engine
    "${j[@]}" fuzz 60
    "${j[@]}" coverage-engine mutate-engine check-licences
    "${j[@]}" test-all test-python-versions
    "${j[@]}" remember-tree "$tree" "$place"
