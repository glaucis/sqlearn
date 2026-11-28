# The commits the build is made from. Each is a git submodule's pinned
# commit: bump the submodule and its line here together (tests/engine/
# test_pins.py compares them). Nothing is fetched at configure time.

set(SQ_DUCKDB_TAG "v2.0.1")
set(SQ_DUCKDB_COMMIT "8d78114e90a53823803660bf821f6073ac87da8c")
set(SQ_DUCKDB_PYTHON_COMMIT "de8eed775826e6c515af3656a6a88e00559a903b")
set(SQ_CATCH2_COMMIT "08092139210881f01a34e60c5f2fd6afa0ea4024")
set(SQ_RAPIDCHECK_COMMIT "2c3c4365aca21ef4e612768fdc95b1ce8b39a651")
set(SQ_NANOBENCH_COMMIT "b709728dba4df0356d467abfb0ba20781a8031c0")
set(SQ_CPPTRACE_COMMIT "3db8da80111171c219ab5839905771386bee06b3")

# Fail configure, naming the fix, when the submodule checked out at `dir`
# (shown as `name`) is missing, at a commit other than `pinned`, or has
# local edits: submodules are never edited, and the commit alone does not
# show an edited or added file. A build writes nothing inside them. It also
# runs in script mode (cmake -P), where the tests call it.
function(sq_check_submodule dir name pinned)
  find_package(Git REQUIRED)
  set(found "")
  if(EXISTS "${dir}/.git")
    execute_process(
      COMMAND "${GIT_EXECUTABLE}" -C "${dir}" rev-parse HEAD
      OUTPUT_VARIABLE found
      OUTPUT_STRIP_TRAILING_WHITESPACE
      ERROR_QUIET
    )
  endif()
  if(found STREQUAL "")
    message(
      FATAL_ERROR
      "${name} is not checked out.\n"
      "Fix: run these two commands\n"
      "  git submodule update --init\n"
      "  git -C engine/duckdb-python submodule update --init external/duckdb"
    )
  elseif(NOT found STREQUAL pinned)
    message(
      FATAL_ERROR
      "${name} is at ${found}, pinned to ${pinned}.\n"
      "Fix: run these two commands\n"
      "  git submodule update --init\n"
      "  git -C engine/duckdb-python submodule update --init external/duckdb"
    )
  endif()
  # A nested submodule (duckdb-python's DuckDB) is checked on its own, so
  # its edits are named there, with the fix for its own directory.
  execute_process(
    COMMAND "${GIT_EXECUTABLE}" -C "${dir}" status --porcelain --ignore-submodules=all
    OUTPUT_VARIABLE edits
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(NOT edits STREQUAL "")
    string(REPLACE "\n" ";" lines "${edits}")
    list(LENGTH lines count)
    list(SUBLIST lines 0 10 shown)
    list(JOIN shown "\n  " shown)
    message(
      FATAL_ERROR
      "${name} has local edits (${count} files), at its pinned commit:\n"
      "  ${shown}\n"
      "Submodules are never edited: the build would carry the edits unseen.\n"
      "Fix: keep any edit you need elsewhere, then discard them with\n"
      "  git -C ${name} checkout -- .\n"
      "  git -C ${name} clean -fd"
    )
  endif()
endfunction()

# Check every submodule the build uses (sq_check_submodule).
function(sq_check_pins)
  get_filename_component(engine "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/.." ABSOLUTE)
  set(
    checks
    "duckdb-python|${SQ_DUCKDB_PYTHON_COMMIT}"
    "duckdb-python/external/duckdb|${SQ_DUCKDB_COMMIT}"
    "third_party/catch2|${SQ_CATCH2_COMMIT}"
    "third_party/rapidcheck|${SQ_RAPIDCHECK_COMMIT}"
    "third_party/nanobench|${SQ_NANOBENCH_COMMIT}"
    "third_party/cpptrace|${SQ_CPPTRACE_COMMIT}"
  )
  foreach(check IN LISTS checks)
    string(REPLACE "|" ";" parts "${check}")
    list(GET parts 0 path)
    list(GET parts 1 pinned)
    sq_check_submodule("${engine}/${path}" "engine/${path}" "${pinned}")
  endforeach()
endfunction()
