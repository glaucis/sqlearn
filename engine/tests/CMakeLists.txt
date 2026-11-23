# The C++ tests that are not a group's own program (those come from
# sq_add_group, engine/cmake/groups.cmake).

# Must-not-compile: each file breaks one rule of sqlearn's warnings and
# nothing else. Its target, built with a group's options (outside raw/),
# must fail; its control, the same file with only that warning turned off,
# must build, so the failure is the warning's and not the file's. An entry
# is the case's name, then each flag its control adds.
set(sq_must_not_compile "conversion|-Wno-conversion" "fallthrough|-Wno-implicit-fallthrough")
# -Wunsafe-buffer-usage is Clang's alone (warnings.cmake), so on another
# compiler buffer.cpp builds and its test would fail for the compiler, not
# the code.
# [[clang::lifetimebound]] on Buffer::span() (raw/buffer.hpp) is Clang's alone
# too, so is the -Wdangling it gives. LLVM 23's -Wlifetime-safety refuses the
# same dangling span (Apple clang 21 accepts the flag and finds nothing), so
# the control turns off both.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  list(
    APPEND sq_must_not_compile
    "buffer|-Wno-unsafe-buffer-usage"
    "dangling|-Wno-dangling|-Wno-lifetime-safety"
  )
endif()

foreach(entry IN LISTS sq_must_not_compile)
  string(REPLACE "|" ";" parts "${entry}")
  list(GET parts 0 name)
  list(SUBLIST parts 1 -1 off)
  set(source "${CMAKE_CURRENT_SOURCE_DIR}/must_not_compile/${name}.cpp")

  add_library(sq_must_not_compile_${name} OBJECT EXCLUDE_FROM_ALL "${source}")
  sq_target_options(sq_must_not_compile_${name})
  add_library(sq_must_not_compile_${name}_control OBJECT EXCLUDE_FROM_ALL "${source}")
  sq_target_options(sq_must_not_compile_${name}_control)
  target_compile_options(sq_must_not_compile_${name}_control PRIVATE ${off})

  add_test(
    NAME must_not_compile.${name}
    COMMAND "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}" --target sq_must_not_compile_${name}
  )
  add_test(
    NAME must_not_compile.${name}.control
    COMMAND
      "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}" --target sq_must_not_compile_${name}_control
  )
  # One build at a time in the build directory: two ninjas there clash.
  set_tests_properties(must_not_compile.${name} PROPERTIES WILL_FAIL TRUE)
  set_tests_properties(
    must_not_compile.${name}
    must_not_compile.${name}.control
    PROPERTIES LABELS must_not_compile RESOURCE_LOCK sq_build_directory
  )
endforeach()

# The canaries: one program per sanitizer, holding the one fault it finds,
# built in that sanitizer's flavour. Its test passes only when the sanitizer
# stopped it with its report (canary/expect_finding.cmake), so a preset whose
# sanitizer is off, or lets a finding pass, fails. They break sqlearn's
# rules on purpose, as the must-not-compile cases do: they get the flavour
# (its sanitizers, hardening, optimisation), not the warnings, and clang-tidy
# leaves them out (validation/_tidy.py).
function(sq_add_canary name report)
  set(program canary_${name})
  add_executable(${program} canary/${name}.cpp)
  set_target_properties(
    ${program}
    PROPERTIES CXX_STANDARD ${SQ_CXX_STANDARD} CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF
  )
  sq_target_flavor(${program})
  sq_stable_link(${program})
  # The program is the command's last argument, so the checks hash its
  # bytes and libraries into the label's identity (validation/_ctest.py).
  add_test(
    NAME canary.${name}
    COMMAND
      "${CMAKE_COMMAND}" "-DREPORT=${report}" -P
      "${CMAKE_CURRENT_SOURCE_DIR}/canary/expect_finding.cmake" $<TARGET_FILE:${program}>
  )
  set_tests_properties(canary.${name} PROPERTIES LABELS canary)
  if(SQ_TEST_ENVIRONMENT)
    set_tests_properties(canary.${name} PROPERTIES ENVIRONMENT "${SQ_TEST_ENVIRONMENT}")
  endif()
endfunction()

if(SQ_FLAVOR STREQUAL "dev")
  sq_add_canary(asan "ERROR: AddressSanitizer: heap-buffer-overflow")
  sq_add_canary(ubsan "runtime error: signed integer overflow")
  # AddressSanitizer's leak check, on with Homebrew LLVM (llvm-dev) alone.
  if(SQ_TEST_ENVIRONMENT MATCHES "detect_leaks=1")
    sq_add_canary(lsan "ERROR: LeakSanitizer: detected memory leaks")
  endif()
elseif(SQ_FLAVOR STREQUAL "tsan")
  sq_add_canary(tsan "WARNING: ThreadSanitizer: data race")
elseif(SQ_FLAVOR STREQUAL "lsan")
  sq_add_canary(lsan "ERROR: LeakSanitizer: detected memory leaks")
elseif(SQ_FLAVOR STREQUAL "tysan")
  sq_add_canary(tysan "ERROR: TypeSanitizer: type-aliasing-violation")
endif()
