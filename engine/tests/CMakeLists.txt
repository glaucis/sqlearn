# The C++ tests that are not a group's own program (those come from
# sq_add_group, engine/cmake/groups.cmake).

# Must-not-compile: each file breaks one rule of sqlearn's warnings and
# nothing else. Its target, built with a group's options (outside raw/),
# must fail; its control, the same file with only that warning turned off,
# must build, so the failure is the warning's and not the file's.
set(sq_must_not_compile
    "conversion|-Wno-conversion"
    "fallthrough|-Wno-implicit-fallthrough")
# -Wunsafe-buffer-usage is Clang's alone (warnings.cmake), so on another
# compiler buffer.cpp builds and its test would fail for the compiler, not
# the code.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  list(APPEND sq_must_not_compile "buffer|-Wno-unsafe-buffer-usage")
endif()

foreach(entry IN LISTS sq_must_not_compile)
  string(REPLACE "|" ";" parts "${entry}")
  list(GET parts 0 name)
  list(GET parts 1 off)
  set(source "${CMAKE_CURRENT_SOURCE_DIR}/must_not_compile/${name}.cpp")

  add_library(sq_must_not_compile_${name} OBJECT EXCLUDE_FROM_ALL "${source}")
  sq_target_options(sq_must_not_compile_${name})
  add_library(sq_must_not_compile_${name}_control OBJECT EXCLUDE_FROM_ALL "${source}")
  sq_target_options(sq_must_not_compile_${name}_control)
  target_compile_options(sq_must_not_compile_${name}_control PRIVATE ${off})

  add_test(NAME must_not_compile.${name}
           COMMAND "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}" --target
                   sq_must_not_compile_${name})
  add_test(NAME must_not_compile.${name}.control
           COMMAND "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}" --target
                   sq_must_not_compile_${name}_control)
  # One build at a time in the build directory: two ninjas there clash.
  set_tests_properties(must_not_compile.${name} PROPERTIES WILL_FAIL TRUE)
  set_tests_properties(must_not_compile.${name} must_not_compile.${name}.control
                       PROPERTIES LABELS must_not_compile RESOURCE_LOCK sq_build_directory)
endforeach()
