# LLVM's clang (spec §3.8: the sanitizer, fuzzing and tooling builds), from
# the prefix SQ_LLVM_ROOT names: a cache variable, else the environment, else
# Homebrew's prefix for the host (keg-only, so off PATH). On macOS, Apple's
# SDK is the system root: without -isysroot its clang finds no system
# headers. The SDK path is xcrun's, asked once at configure. The workflows
# set SQ_LLVM_ROOT to apt.llvm.org's /usr/lib/llvm-<major> on Linux.
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
  set(sq_llvm_default "/opt/homebrew/opt/llvm")
else()
  set(sq_llvm_default "/home/linuxbrew/.linuxbrew/opt/llvm")
endif()
if(DEFINED ENV{SQ_LLVM_ROOT} AND NOT "$ENV{SQ_LLVM_ROOT}" STREQUAL "")
  set(sq_llvm_default "$ENV{SQ_LLVM_ROOT}")
endif()
set(SQ_LLVM_ROOT "${sq_llvm_default}" CACHE PATH "LLVM's prefix, the directory holding bin/clang++")

if(NOT EXISTS "${SQ_LLVM_ROOT}/bin/clang++")
  message(
    FATAL_ERROR
    "LLVM is not at ${SQ_LLVM_ROOT}.\n"
    "Fix: brew install llvm, or set SQ_LLVM_ROOT to LLVM's prefix"
  )
endif()

set(CMAKE_C_COMPILER "${SQ_LLVM_ROOT}/bin/clang")
set(CMAKE_CXX_COMPILER "${SQ_LLVM_ROOT}/bin/clang++")

# Link LLVM's own libc++, the library its headers are from, not the system's:
# a header newer than the library it links can call a function the library
# lacks, and libc++ is what the hardening modes are written for
# (hardening.cmake). Its libc++ finds its libc++abi and libunwind through its
# own rpaths.
if(APPLE)
  execute_process(
    COMMAND xcrun --show-sdk-path
    OUTPUT_VARIABLE SQ_SDK_PATH
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE sq_xcrun_result
  )
  if(NOT sq_xcrun_result EQUAL 0 OR SQ_SDK_PATH STREQUAL "")
    message(FATAL_ERROR "xcrun --show-sdk-path found no macOS SDK.\n" "Fix: xcode-select --install")
  endif()
  set(CMAKE_OSX_SYSROOT "${SQ_SDK_PATH}")
  set(SQ_LLVM_LIBCXX_DIR "${SQ_LLVM_ROOT}/lib/c++")
else()
  # On Linux clang takes libstdc++ unless told: libc++ is asked for here.
  set(CMAKE_CXX_FLAGS_INIT "-stdlib=libc++")
  set(SQ_LLVM_LIBCXX_DIR "${SQ_LLVM_ROOT}/lib")
endif()
set(SQ_LLVM_LIBCXX_FLAGS "-L${SQ_LLVM_LIBCXX_DIR} -Wl,-rpath,${SQ_LLVM_LIBCXX_DIR}")
set(CMAKE_EXE_LINKER_FLAGS_INIT "${SQ_LLVM_LIBCXX_FLAGS}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${SQ_LLVM_LIBCXX_FLAGS}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${SQ_LLVM_LIBCXX_FLAGS}")
