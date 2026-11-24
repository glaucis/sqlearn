# cpptrace, the stack trace of a crash report (engine/src/crash/), from its
# submodule: in the wheel its library links into _duckdb, and in a preset's
# build into the crash group's test program.
#
# Its back-ends are chosen here, never left to its autoconfig, whose symbol
# back-end on macOS and Linux is libdwarf (LGPL-2.1, copyleft, so never in
# what ships, ADR 0066), fetched at configure time with zstd (never a
# download at configure time either). Instead:
#
# - symbols through libdl: dladdr, the system's, for the names a test and
#   the symbolising of a report outside the crash need. It compiles none of
#   libdwarf's or zstd's code, and fetches nothing.
# - unwinding on macOS through the system's libunwind (in libSystem), the
#   one back-end whose unwinding cpptrace makes signal-safe
#   (docs/signal-safe-tracing.md). Elsewhere its autoconfig picks libgcc's
#   unwinder, which is not signal-safe, so a report there says it has no
#   stack.
#
# Its install rules are skipped, so the wheel carries none of its headers
# or its archive: they are linked into _duckdb, nothing more.
function(sq_add_cpptrace)
  set(CPPTRACE_GET_SYMBOLS_WITH_LIBDL ON CACHE BOOL "" FORCE)
  set(CPPTRACE_GET_SYMBOLS_WITH_LIBDWARF OFF CACHE BOOL "" FORCE)
  set(CPPTRACE_GET_SYMBOLS_WITH_LIBBACKTRACE OFF CACHE BOOL "" FORCE)
  set(CPPTRACE_GET_SYMBOLS_WITH_ADDR2LINE OFF CACHE BOOL "" FORCE)
  if(APPLE)
    set(CPPTRACE_UNWIND_WITH_LIBUNWIND ON CACHE BOOL "" FORCE)
  endif()
  set(CPPTRACE_BUILD_SHARED OFF CACHE BOOL "" FORCE)
  set(CPPTRACE_BUILD_TESTING OFF CACHE BOOL "" FORCE)
  set(CPPTRACE_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
  set(CPPTRACE_DISABLE_CXX_20_MODULES ON CACHE BOOL "" FORCE)
  # Read by cpptrace's CMakeLists.txt in this function's scope only.
  set(CMAKE_SKIP_INSTALL_RULES ON)
  add_subdirectory("${SQ_ENGINE_DIR}/third_party/cpptrace" third_party/cpptrace EXCLUDE_FROM_ALL)
  if(TARGET libdwarf OR TARGET zstd OR TARGET libzstd_static)
    message(
      FATAL_ERROR
      "cpptrace configured libdwarf or zstd, which must never be compiled in "
      "(ADR 0066).\nFix: keep CPPTRACE_GET_SYMBOLS_WITH_LIBDL on in engine/cmake/cpptrace.cmake"
    )
  endif()
  # As system headers to ours, so our warnings cover our code only.
  set_property(TARGET cpptrace-lib PROPERTY SYSTEM TRUE)
endfunction()
