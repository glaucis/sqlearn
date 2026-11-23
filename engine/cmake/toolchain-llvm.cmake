# Homebrew LLVM on macOS (spec §3.8: the sanitizer, fuzzing and tooling
# builds), with Apple's SDK as the system root: without -isysroot its clang
# finds no system headers. The SDK path is xcrun's, asked once at configure.
set(SQ_LLVM_ROOT "/opt/homebrew/opt/llvm" CACHE PATH "Homebrew LLVM's prefix")

if(NOT EXISTS "${SQ_LLVM_ROOT}/bin/clang++")
  message(FATAL_ERROR "Homebrew LLVM is not at ${SQ_LLVM_ROOT}.\n" "Fix: brew install llvm")
endif()

execute_process(
  COMMAND xcrun --show-sdk-path
  OUTPUT_VARIABLE SQ_SDK_PATH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE sq_xcrun_result
)
if(NOT sq_xcrun_result EQUAL 0 OR SQ_SDK_PATH STREQUAL "")
  message(FATAL_ERROR "xcrun --show-sdk-path found no macOS SDK.\n" "Fix: xcode-select --install")
endif()

set(CMAKE_C_COMPILER "${SQ_LLVM_ROOT}/bin/clang")
set(CMAKE_CXX_COMPILER "${SQ_LLVM_ROOT}/bin/clang++")
set(CMAKE_OSX_SYSROOT "${SQ_SDK_PATH}")

# Link Homebrew LLVM's own libc++, the library its headers are from, not the
# SDK's older one: a header newer than the library it links can call a
# function the library lacks. Its libc++ finds its libc++abi and libunwind
# through its own rpaths.
set(SQ_LLVM_LIBCXX_FLAGS "-L${SQ_LLVM_ROOT}/lib/c++ -Wl,-rpath,${SQ_LLVM_ROOT}/lib/c++")
set(CMAKE_EXE_LINKER_FLAGS_INIT "${SQ_LLVM_LIBCXX_FLAGS}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${SQ_LLVM_LIBCXX_FLAGS}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${SQ_LLVM_LIBCXX_FLAGS}")
