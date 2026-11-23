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

# Fail configure, naming the fix, when a submodule is missing or at a
# commit other than its pin.
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
  find_package(Git REQUIRED)
  foreach(check IN LISTS checks)
    string(REPLACE "|" ";" parts "${check}")
    list(GET parts 0 path)
    list(GET parts 1 pinned)
    set(dir "${engine}/${path}")
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
        "engine/${path} is not checked out.\n"
        "Fix: git submodule update --init --recursive"
      )
    elseif(NOT found STREQUAL pinned)
      message(
        FATAL_ERROR
        "engine/${path} is at ${found}, pinned to ${pinned}.\n"
        "Fix: git submodule update --init --recursive"
      )
    endif()
  endforeach()
endfunction()
