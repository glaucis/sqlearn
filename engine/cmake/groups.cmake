# The groups of sqlearn's C++: one directory of engine/src each (the
# inventory's groups, docs/architecture/engine-inventory.md), compiled as
# an object library with sqlearn's flags, and tested by one Catch2 program.

# Give `target`, one of ours, the C++ standard, hidden symbols (the module
# exports DuckDB's), engine/src as its include root, the warnings and the
# flavour. RAW marks the raw memory layer (warnings.cmake).
function(sq_target_options target)
  cmake_parse_arguments(PARSE_ARGV 1 arg "RAW" "" "")
  set_target_properties(
    ${target}
    PROPERTIES CXX_STANDARD ${SQ_CXX_STANDARD}
               CXX_STANDARD_REQUIRED ON
               CXX_EXTENSIONS OFF
               CXX_VISIBILITY_PRESET hidden
               VISIBILITY_INLINES_HIDDEN ON
               POSITION_INDEPENDENT_CODE ON)
  target_include_directories(${target} PRIVATE "${SQ_ENGINE_DIR}/src")
  if(arg_RAW)
    sq_target_warnings(${target} RAW)
  else()
    sq_target_warnings(${target})
  endif()
  sq_target_flavor(${target})
endfunction()

# sq_add_group(<name> SOURCES <file>... [TESTS <file>...])
#
# The object library sq_<name> from SOURCES (engine/src/<name>/), with
# sqlearn's options; in the wheel its objects join _duckdb. With TESTS, and
# when the tests are built (SQ_BUILD_TESTS), the Catch2 program
# test_<name>, registered with CTest as test_<name> under the label <name>.
# The group `raw` alone goes without -Wunsafe-buffer-usage.
function(sq_add_group name)
  cmake_parse_arguments(PARSE_ARGV 1 arg "" "" "SOURCES;TESTS")
  if(NOT arg_SOURCES)
    message(FATAL_ERROR "sq_add_group(${name}) has no SOURCES")
  endif()
  set(raw "")
  if(name STREQUAL "raw")
    set(raw RAW)
  endif()
  set(target sq_${name})
  add_library(${target} OBJECT ${arg_SOURCES})
  sq_target_options(${target} ${raw})
  if(COMMAND sq_add_to_module)
    sq_add_to_module(${target})
  endif()
  if(SQ_BUILD_TESTS AND arg_TESTS)
    set(program test_${name})
    add_executable(${program} ${arg_TESTS})
    sq_target_options(${program} ${raw})
    target_link_libraries(${program} PRIVATE ${target} Catch2::Catch2WithMain)
    add_test(NAME ${program} COMMAND ${program})
    set_tests_properties(${program} PROPERTIES LABELS ${name})
  endif()
endfunction()
