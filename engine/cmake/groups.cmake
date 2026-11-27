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

# Set `out` to the JSON array of the strings after it.
function(sq_json_list out)
  set(items "")
  foreach(item IN LISTS ARGN)
    list(APPEND items "\"${item}\"")
  endforeach()
  list(JOIN items ", " joined)
  set(${out} "[${joined}]" PARENT_SCOPE)
endfunction()

# Write <build>/sq_groups.json, the manifest of the groups sq_add_group saw,
# in definition order, with the directories that belong to no group.
function(sq_write_groups_manifest)
  get_property(groups GLOBAL PROPERTY SQ_GROUPS_JSON)
  list(JOIN groups ",\n    " joined)
  file(
    WRITE "${CMAKE_BINARY_DIR}/sq_groups.json"
    "{\n  \"groups\": [\n    ${joined}\n  ],\n"
    "  \"shared\": [\"engine/src/bindings\", \"engine/extension\"]\n}\n"
  )
endfunction()

# sq_add_group(<name> SOURCES <file>... [DEPENDS <group>...] [TESTS <file>...]
#              [DATA <file>...] [ARGS <argument>...] [PYTHON_TESTS <dir>...]
#              [VALIDATION <runner>...] [BENCH <name>...])
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
# -Wunsafe-buffer-usage. PYTHON_TESTS (directories, relative to the
# repository, which must exist), VALIDATION (runners) and BENCH (benchmarks)
# are what the group claims: they go into the manifest (sq_write_groups_manifest)
# that the checks read to rerun only what a change to the group affects.
function(sq_add_group name)
  cmake_parse_arguments(
    PARSE_ARGV 1
    arg
    ""
    ""
    "SOURCES;DEPENDS;TESTS;DATA;ARGS;PYTHON_TESTS;VALIDATION;BENCH"
  )
  if(NOT arg_SOURCES)
    message(FATAL_ERROR "sq_add_group(${name}) has no SOURCES")
  endif()
  foreach(dir IN LISTS arg_PYTHON_TESTS)
    if(NOT EXISTS "${SQ_ENGINE_DIR}/../${dir}")
      message(
        FATAL_ERROR
        "sq_add_group(${name}): PYTHON_TESTS ${dir} does not exist.\n"
        "Fix: name a directory of the repository, relative to its root, "
        "as sq_add_group(... PYTHON_TESTS tests/engine)"
      )
    endif()
  endforeach()
  sq_json_list(depends_json ${arg_DEPENDS})
  sq_json_list(tests_json ${arg_PYTHON_TESTS})
  sq_json_list(validation_json ${arg_VALIDATION})
  sq_json_list(bench_json ${arg_BENCH})
  set_property(
    GLOBAL
    APPEND
    PROPERTY
      SQ_GROUPS_JSON
        "{\"name\": \"${name}\", \"dir\": \"engine/src/${name}\", \"depends\": ${depends_json}, \"python_tests\": ${tests_json}, \"validation\": ${validation_json}, \"bench\": ${bench_json}}"
  )
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
