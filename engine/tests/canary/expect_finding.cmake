# A canary's check: cmake -DREPORT=<regex> -P expect_finding.cmake <program>
#
# Runs <program>, a canary with the one fault its sanitizer finds, and passes
# only when the program failed (a non-zero exit, or a signal) and its output
# holds the sanitizer's report, REPORT. Most sanitizers stop the program at
# the fault; LeakSanitizer looks at exit and fails it then. A bare non-zero
# exit would also pass a program that crashed for another reason, and the
# report alone a sanitizer that let the program succeed; so both are asked
# for.
math(EXPR last "${CMAKE_ARGC} - 1")
set(program "${CMAKE_ARGV${last}}")
if(NOT DEFINED REPORT OR NOT EXISTS "${program}")
  message(
    FATAL_ERROR
    "No canary to check.\n"
    "Fix: cmake -DREPORT=<the sanitizer's report> -P expect_finding.cmake <program>"
  )
endif()

execute_process(COMMAND "${program}" RESULT_VARIABLE code OUTPUT_VARIABLE out ERROR_VARIABLE err)
message("${out}${err}")
if("${code}" STREQUAL "0")
  message(
    FATAL_ERROR
    "${program} exited 0: its sanitizer did not fail it.\n"
    "Fix: build it with the sanitizer's preset (just sanitize), and keep "
    "-fno-sanitize-recover=all or the halt_on_error option (engine/cmake/hardening.cmake)"
  )
endif()
if(NOT "${out}${err}" MATCHES "${REPORT}")
  message(
    FATAL_ERROR
    "${program} failed (${code}) without the report \"${REPORT}\": something "
    "else failed it, not its sanitizer.\n"
    "Fix: read its output above; the canary must hold its one fault and no other"
  )
endif()
