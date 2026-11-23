# sqlearn's C++ benchmarks, with nanobench (header-only, test-only: it never
# ships). They are built only in the optimised flavours, release and
# profile: a timing of the sanitized or -O0 build measures the build, not
# the code. `just bench-engine` builds release and runs them.

if(NOT SQ_FLAVOR MATCHES "^(release|profile)$")
  return()
endif()

add_library(sq_nanobench INTERFACE)
target_include_directories(sq_nanobench SYSTEM
                           INTERFACE "${SQ_ENGINE_DIR}/third_party/nanobench/src/include")

add_executable(bench_buffer bench_buffer.cpp)
sq_target_options(bench_buffer)
target_link_libraries(bench_buffer PRIVATE sq_raw sq_core sq_nanobench)
