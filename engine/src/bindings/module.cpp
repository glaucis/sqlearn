/// @file
/// sqlearn._native: the second nanobind module in DuckDB's _duckdb binary,
/// in its nanobind domain (NB_DOMAIN=duckdb, from _duckdb_dependencies), so
/// DuckDB's connection type and exception translators serve it too.
#include "bindings/guard.hpp"
#include "core/version.hpp"
#include "crash/handler.hpp"

#include <Python.h>
#include <nanobind/nanobind.h>
// nanobind's caster for std::string, which describe's binding uses through
// templates, so no symbol of it is named here.
#include <nanobind/stl/string.h> // IWYU pragma: keep

#include <string>

namespace nb = nanobind;

namespace sq::bindings {

void raise_internal(const std::string &message) {
    const nb::object cls = nb::module_::import_("sqlearn.errors").attr("InternalError");
    const nb::str text(message.c_str(), message.size());
    PyErr_SetObject(cls.ptr(), text.ptr());
    throw nb::python_error();
}

} // namespace sq::bindings

namespace {

/// Return the build identity as a dictionary of its five fields.
/// @return sqlearn_version, duckdb_version, duckdb_commit, compiler and
///         build_type, each a string.
nb::dict build_identity() {
    return sq::bindings::guarded([] {
        const auto identity = sq::core::build_identity();
        nb::dict out;
        out["sqlearn_version"] = identity.sqlearn_version;
        out["duckdb_version"] = identity.duckdb_version;
        out["duckdb_commit"] = identity.duckdb_commit;
        out["compiler"] = identity.compiler;
        out["build_type"] = identity.build_type;
        return out;
    });
}

/// Return core::describe's one line for this build.
/// @return The line sq.version() and SELECT sqlearn_version() give.
std::string describe() {
    return sq::bindings::guarded([] { return sq::core::describe(sq::core::build_identity()); });
}

} // namespace

/// The module sqlearn._native: PyInit__native, beside PyInit__duckdb.
NB_MODULE(_native, m) {
    m.doc() = "sqlearn's engine, compiled into DuckDB's _duckdb binary.";
    // The crash report, written on this machine only (ADR 0006). When its
    // directory cannot be made the handler is not installed, and the
    // import goes on.
    (void)sq::crash::install_default();
    m.def("build_identity", &build_identity, nb::sig("def build_identity() -> dict[str, str]"),
          "Return what this engine was built as: sqlearn's and DuckDB's versions,\n"
          "DuckDB's commit, the compiler and the build type.");
    m.def("describe", &describe,
          "Return the build in one line, as sq.version() and SELECT sqlearn_version()\n"
          "give it.");
    sq::bindings::add_connection(m);
}
