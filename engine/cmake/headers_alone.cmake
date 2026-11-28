# Every header under engine/src compiles alone: one generated unit per
# header includes it, twice, and nothing else, so a header that leans on an
# include it does not make, or has no include guard, fails to build. The
# units take the strict flags of a group outside the raw layer.

# Write one unit per header under `src_dir` into `out_dir`, mirroring the
# tree (core/error.hpp gives <out_dir>/core/error.cpp), and set `out_var` to
# their paths, sorted. A unit is written only when its text changes, so a
# configure does not rebuild them. It also runs in script mode (cmake -P),
# where the tests call it.
function(sq_headers_alone_sources src_dir out_dir out_var)
  if(CMAKE_SCRIPT_MODE_FILE)
    file(GLOB_RECURSE headers RELATIVE "${src_dir}" "${src_dir}/*.hpp")
  else()
    file(GLOB_RECURSE headers CONFIGURE_DEPENDS RELATIVE "${src_dir}" "${src_dir}/*.hpp")
  endif()
  list(SORT headers)
  set(units "")
  foreach(header IN LISTS headers)
    string(REGEX REPLACE "\\.hpp$" ".cpp" unit "${out_dir}/${header}")
    set(
      text
      "// ${header} alone, twice (engine/cmake/headers_alone.cmake).\n#include \"${header}\"\n#include \"${header}\"\n"
    )
    set(old "")
    if(EXISTS "${unit}")
      file(READ "${unit}" old)
    endif()
    if(NOT old STREQUAL text)
      file(WRITE "${unit}" "${text}")
    endif()
    list(APPEND units "${unit}")
  endforeach()
  set(${out_var} "${units}" PARENT_SCOPE)
endfunction()

option(
  SQ_HEADERS_ALONE_BINDINGS
  "In a preset's build, build the bindings' headers alone too (the llvm-dev preset)"
  OFF
)
set(
  SQ_PYTHON
  "${CMAKE_CURRENT_LIST_DIR}/../../.venv/bin/python"
  CACHE FILEPATH
  "The project environment's Python, whose headers and nanobind's the bindings' headers read"
)

# Give `target`, the bindings' headers-alone units in a preset's build, what
# the wheel's build gives them through duckdb-python's _duckdb_dependencies:
# DuckDB's and duckdb-python's headers, Python's and nanobind's (from the
# project environment, where nanobind sits at a fixed path), as system
# headers, and the same definitions. tests/engine/test_presets.py compares
# the two builds' units, so a change to the wheel's shows here.
function(sq_headers_alone_bindings_paths target)
  if(NOT EXISTS "${SQ_PYTHON}")
    message(
      FATAL_ERROR
      "The bindings' headers build alone against the project environment's "
      "Python, which is not at ${SQ_PYTHON}.\n"
      "Fix: just setup (it syncs the environment), or set SQ_PYTHON"
    )
  endif()
  execute_process(
    COMMAND
      "${SQ_PYTHON}" -I -c
      "import sysconfig, nanobind; print(sysconfig.get_path('include')); print(nanobind.include_dir())"
    OUTPUT_VARIABLE paths
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE failed
  )
  if(failed)
    message(
      FATAL_ERROR
      "${SQ_PYTHON} could not name Python's and nanobind's headers.\n"
      "Fix: just setup (it installs the build group, nanobind with it)"
    )
  endif()
  string(REPLACE "\n" ";" paths "${paths}")
  set(duckdb "${SQ_ENGINE_DIR}/duckdb-python/external/duckdb")
  target_include_directories(
    ${target}
    SYSTEM
    PRIVATE
      "${SQ_ENGINE_DIR}/duckdb-python/src/include"
      ${paths}
      "${duckdb}/src/include"
      "${duckdb}/third_party"
      "${duckdb}/third_party/re2"
      "${duckdb}/third_party/fast_float"
      "${duckdb}/third_party/utf8proc/include"
      "${duckdb}/third_party/libpg_query/include"
      "${duckdb}/third_party/fmt/include"
  )
  # The module's stable ABI is CPython 3.12's (pyproject.toml's
  # wheel.py-api = "cp312").
  target_compile_definitions(
    ${target}
    PRIVATE DUCKDB_STATIC_BUILD NB_DOMAIN=duckdb Py_LIMITED_API=0x030C0000
  )
endfunction()

# The targets that build the units. The bindings' headers need DuckDB's,
# nanobind's and Python's headers: the wheel's build has them
# (_duckdb_dependencies), where sq_headers_alone_bindings builds with the
# module. A preset's build (SQ_ENGINE_ONLY) has every other header in
# sq_headers_alone, built on demand: `just headers-alone`; with
# SQ_HEADERS_ALONE_BINDINGS (llvm-dev) the bindings' headers too, in their
# own target.
function(sq_add_headers_alone)
  sq_headers_alone_sources("${SQ_ENGINE_DIR}/src" "${CMAKE_BINARY_DIR}/headers_alone" units)
  set(bindings "${units}")
  list(FILTER bindings INCLUDE REGEX "/headers_alone/bindings/")
  list(FILTER units EXCLUDE REGEX "/headers_alone/bindings/")
  if(SQ_ENGINE_ONLY)
    add_library(sq_headers_alone OBJECT EXCLUDE_FROM_ALL ${units})
    sq_target_options(sq_headers_alone)
    if(SQ_HEADERS_ALONE_BINDINGS AND bindings)
      add_library(sq_headers_alone_bindings OBJECT EXCLUDE_FROM_ALL ${bindings})
      sq_target_options(sq_headers_alone_bindings)
      sq_headers_alone_bindings_paths(sq_headers_alone_bindings)
    endif()
  elseif(bindings)
    add_library(sq_headers_alone_bindings OBJECT ${bindings})
    sq_target_options(sq_headers_alone_bindings)
    target_link_libraries(sq_headers_alone_bindings PRIVATE _duckdb_dependencies)
  endif()
endfunction()
