# ccache for every build: the presets' and the wheel's (duckdb-python would
# otherwise pick a bare ccache for its own and DuckDB's sources).
#
# ccache knows a compiler by its file's size and modification time by
# default. On macOS the compiler CMake finds is /usr/bin/c++, xcrun's shim,
# which an Xcode or Command Line Tools update leaves as it was, so objects of
# the old compiler would serve the new one; and `content` would hash the
# shim alone. The compiler's --version, run through the shim, names the real
# compiler's build, so ccache is launched with CCACHE_COMPILERCHECK set to it.

# Set the C and C++ launchers to ccache with the compiler check, found on
# PATH or in the directories `ARGN` names first. A launcher already set to
# something other than ccache (distcc, sccache) is left as it is, and so is
# a build without ccache.
function(sq_ccache)
  find_program(SQ_CCACHE NAMES ccache HINTS ${ARGN})
  if(NOT SQ_CCACHE)
    return()
  endif()
  set(
    launcher
    "${CMAKE_COMMAND}"
    -E
    env
    "CCACHE_COMPILERCHECK=%compiler% --version"
    "${SQ_CCACHE}"
  )
  foreach(language IN ITEMS C CXX)
    set(before "${CMAKE_${language}_COMPILER_LAUNCHER}")
    if(before STREQUAL "" OR before MATCHES "(^|/)ccache$")
      set(
        CMAKE_${language}_COMPILER_LAUNCHER
        "${launcher}"
        CACHE STRING
        "ccache, checking the compiler by its --version (engine/cmake/ccache.cmake)"
        FORCE
      )
      # In this scope too, should a normal variable of the old value hide
      # the cache's.
      set(CMAKE_${language}_COMPILER_LAUNCHER "${launcher}" PARENT_SCOPE)
    endif()
  endforeach()
endfunction()
