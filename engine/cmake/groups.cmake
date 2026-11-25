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
    PROPERTIES
      CXX_STANDARD ${SQ_CXX_STANDARD}
      CXX_STANDARD_REQUIRED ON
      CXX_EXTENSIONS OFF
      CXX_VISIBILITY_PRESET hidden
      VISIBILITY_INLINES_HIDDEN ON
      POSITION_INDEPENDENT_CODE ON
  )
  target_include_directories(${target} PRIVATE "${SQ_ENGINE_DIR}/src")
  if(arg_RAW)
    sq_target_warnings(${target} RAW)
  else()
    sq_target_warnings(${target})
  endif()
  sq_target_flavor(${target})
endfunction()

# Link `target`, a program, so that relinking the same objects gives the
# same bytes. Apple's linker writes each object's modification time into a
# program's debug map unless ZERO_AR_DATE is set, so a rebuilt object with
# unchanged bytes (a touched header, a ccache hit) would change the program;
# the checks know a test program by the hash of its bytes
# (validation/_ctest.py). Its UUID is derived from the content, so it stays.
function(sq_stable_link target)
  if(APPLE)
    set_property(
      TARGET ${target}
      PROPERTY CXX_LINKER_LAUNCHER "${CMAKE_COMMAND}" -E env ZERO_AR_DATE=1
    )
  endif()
endfunction()

# Give the test `test` the files it reads at run time, relative to the
# current source directory or absolute, as CTest's REQUIRED_FILES: CTest
# refuses to run it without them, and the checks hash them into its group's
# identity (validation/_ctest.py), so an edited file reruns it. A directory
# is refused: the checks hash a file's bytes, and a directory's would be
# none of its files'.
function(sq_test_data test)
  set(files "")
  foreach(file IN LISTS ARGN)
    get_filename_component(path "${file}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    if(IS_DIRECTORY "${path}")
      message(
        FATAL_ERROR
        "sq_test_data(${test}): ${path} is a directory, whose files the checks "
        "would not hash, so an edited one would not rerun ${test}.\n"
        "Fix: name each file it reads, as sq_add_group(... DATA <dir>/a.csv <dir>/b.csv)"
      )
    endif()
    list(APPEND files "${path}")
  endforeach()
  if(files)
    set_property(TEST ${test} APPEND PROPERTY REQUIRED_FILES ${files})
  endif()
endfunction()

# How long a CTest test may run before CTest ends it as failed: a hang
# fails in minutes, never stalls a run. validation/_ctest.py refuses a test
# without one.
set(SQ_TEST_TIMEOUT 300)

# Give each of the tests named a TIMEOUT of SQ_TEST_TIMEOUT seconds.
function(sq_test_timeout)
  set_tests_properties(${ARGN} PROPERTIES TIMEOUT ${SQ_TEST_TIMEOUT})
endfunction()

# sq_add_group(<name> SOURCES <file>... [DEPENDS <group>...] [TESTS <file>...]
#              [DATA <file>...] [ARGS <argument>...])
#
# The object library sq_<name> from SOURCES (engine/src/<name>/), with
# sqlearn's options; in the wheel its objects join _duckdb. DEPENDS names
# the groups whose objects it calls, which its test program links too (an
# object library's objects reach only the targets that name it). DEPENDS is
# not transitive: a group whose dependency has a dependency of its own names
# both. With TESTS,
# and when the tests are built (SQ_BUILD_TESTS), the Catch2 program
# test_<name>, with RapidCheck for its properties, registered with CTest as
# test_<name> under the label <name>, with SQ_TEST_TIMEOUT; DATA names the
# files it reads at run time (sq_test_data), and ARGS what CTest passes the
# program (a Catch2 test filter). The group `raw` alone goes without
# -Wunsafe-buffer-usage.
function(sq_add_group name)
  cmake_parse_arguments(PARSE_ARGV 1 arg "" "" "SOURCES;DEPENDS;TESTS;DATA;ARGS")
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
    sq_stable_link(${program})
    sq_target_options(${program} ${raw})
    list(TRANSFORM arg_DEPENDS PREPEND sq_ OUTPUT_VARIABLE depends)
    target_link_libraries(
      ${program}
      PRIVATE ${target} ${depends} Catch2::Catch2WithMain sq_rapidcheck_catch
    )
    add_test(NAME ${program} COMMAND ${program} ${arg_ARGS})
    set_tests_properties(${program} PROPERTIES LABELS ${name})
    sq_test_timeout(${program})
    sq_test_environment(${program})
    sq_test_data(${program} ${arg_DATA})
  endif()
endfunction()
