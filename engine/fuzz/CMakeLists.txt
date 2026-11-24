# The version parser's fuzzing (spec §3.8): libFuzzer's target, built in the
# `fuzzing` preset alone (Homebrew LLVM; Apple's clang has no fuzzer
# runtime), and the replay of its kept corpus, built and run in every preset
# as CTest's replay_parse_version, under the label core: a change to the
# parser or a new corpus file reruns it (validation/_ctest.py).

# The target's source compiles in every preset, so clang-tidy sees it and it
# cannot rot; only the fuzzing preset links libFuzzer's main.
if(SQ_FLAVOR STREQUAL "fuzzing")
  add_executable(fuzz_parse_version fuzz_parse_version.cpp)
  target_link_libraries(fuzz_parse_version PRIVATE sq_core)
  target_link_options(fuzz_parse_version PRIVATE -fsanitize=fuzzer)
else()
  add_library(sq_fuzz_parse_version OBJECT fuzz_parse_version.cpp)
endif()
foreach(target fuzz_parse_version sq_fuzz_parse_version)
  if(TARGET ${target})
    sq_target_options(${target})
    target_include_directories(${target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
  endif()
endforeach()

add_executable(replay_parse_version replay_parse_version.cpp)
sq_stable_link(replay_parse_version)
sq_target_options(replay_parse_version)
target_include_directories(replay_parse_version PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(replay_parse_version PRIVATE sq_core)

# Each corpus file is an argument and a required file, so the checks hash its
# bytes into the group's identity, and a file added or edited reruns the
# test; the glob is redone at each build (CONFIGURE_DEPENDS).
file(GLOB corpus CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/corpus/parse_version/*")
add_test(NAME replay_parse_version COMMAND replay_parse_version ${corpus})
set_tests_properties(replay_parse_version PROPERTIES LABELS core)
sq_test_environment(replay_parse_version)
sq_test_data(replay_parse_version ${corpus})
