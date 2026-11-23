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

# The targets that build the units. The bindings' headers need DuckDB's,
# nanobind's and Python's headers, which only the wheel's build has
# (_duckdb_dependencies): there sq_headers_alone_bindings builds with the
# module. A preset's build (SQ_ENGINE_ONLY) has every other header in
# sq_headers_alone, built on demand: `just headers-alone`.
function(sq_add_headers_alone)
  sq_headers_alone_sources("${SQ_ENGINE_DIR}/src" "${CMAKE_BINARY_DIR}/headers_alone" units)
  set(bindings "${units}")
  list(FILTER bindings INCLUDE REGEX "/headers_alone/bindings/")
  list(FILTER units EXCLUDE REGEX "/headers_alone/bindings/")
  if(SQ_ENGINE_ONLY)
    add_library(sq_headers_alone OBJECT EXCLUDE_FROM_ALL ${units})
    sq_target_options(sq_headers_alone)
  elseif(bindings)
    add_library(sq_headers_alone_bindings OBJECT ${bindings})
    sq_target_options(sq_headers_alone_bindings)
    target_link_libraries(sq_headers_alone_bindings PRIVATE _duckdb_dependencies)
  endif()
endfunction()
