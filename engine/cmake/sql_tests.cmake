# The files under the SQL tests' directory (engine/sqllogic/CMakeLists.txt):
# the ones DuckDB's sqllogictest runner takes (every .test, .test_slow and
# .test_coverage file at any depth, as its test_sqllogictest.cpp selects
# them), and every file there, which the checks hash.

# Set `out` to the files the runner would run under `dir`, sorted. In a
# configure, a file added or removed configures again (CONFIGURE_DEPENDS);
# in script mode (cmake -P, the tests) there is no configure to rerun.
function(sq_sql_test_files out dir)
  set(depends CONFIGURE_DEPENDS)
  if(CMAKE_SCRIPT_MODE_FILE)
    set(depends "")
  endif()
  file(GLOB_RECURSE files ${depends} "${dir}/*.test" "${dir}/*.test_slow" "${dir}/*.test_coverage")
  list(SORT files)
  set(${out} "${files}" PARENT_SCOPE)
endfunction()

# Set `out` to every file under `dir`, at any depth and hidden ones too,
# sorted: the runner's files and what they read at run time (a CSV, a
# script), so the checks hash them all. Reconfigured as sq_sql_test_files.
function(sq_sql_test_data out dir)
  set(depends CONFIGURE_DEPENDS)
  if(CMAKE_SCRIPT_MODE_FILE)
    set(depends "")
  endif()
  file(GLOB_RECURSE files LIST_DIRECTORIES false ${depends} "${dir}/*")
  list(SORT files)
  set(${out} "${files}" PARENT_SCOPE)
endfunction()
