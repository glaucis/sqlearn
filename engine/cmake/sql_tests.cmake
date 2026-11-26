# The files DuckDB's sqllogictest runner takes under a directory, so the
# checks hash exactly what it runs (engine/sqllogic/CMakeLists.txt): every
# .test, .test_slow and .test_coverage file at any depth, as its
# test_sqllogictest.cpp selects them.

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
