/// @file
/// How sqlearn's C++ errors cross into Python: every binding body runs
/// inside guarded().
#pragma once

#include "core/error.hpp"

#include "duckdb/common/exception.hpp"

#include <nanobind/nanobind.h>

#include <exception>
#include <new>
#include <string>
#include <typeinfo>
#include <utility>

namespace sq::bindings {

/// Raise sqlearn.errors.InternalError with `message` as the pending Python
/// error, and throw so nanobind returns to Python. The GIL must be held.
/// @param message The full message, its Why: and Fix: lines included.
[[noreturn]] void raise_internal(const std::string &message);

/// Run `body`, letting what Python and DuckDB raise pass as they are, and
/// turning sqlearn's own errors and any other C++ exception into
/// sqlearn.errors.InternalError, so nothing crashes the interpreter.
/// @param body The binding's work; it may release the GIL inside.
/// @return What `body` returns.
template <typename Body> decltype(auto) guarded(Body &&body) {
    try {
        return std::forward<Body>(body)();
    } catch (const nanobind::python_error &) {
        throw;
    } catch (const nanobind::builtin_exception &) {
        throw;
    } catch (const duckdb::Exception &) {
        throw; // DuckDB's translators, which the shared domain gives us
    } catch (const std::bad_alloc &) {
        throw; // nanobind's MemoryError
    } catch (const core::Error &e) {
        raise_internal(std::string(e.what()) + "\nWhy: " + e.why() + "\nFix: " + e.fix());
    } catch (const std::exception &e) {
        raise_internal("sqlearn's engine failed with a C++ exception it did not expect (" +
                       std::string(typeid(e).name()) + "): " + e.what() +
                       "\nWhy: sqlearn's C++ let an exception through that it should have "
                       "handled, which is a bug in sqlearn, not a mistake in your code"
                       "\nFix: please report it at https://github.com/glaucis/sqlearn/issues "
                       "with this message");
    }
}

/// Add count_rows and roundtrip, the functions that take a user's
/// connection, to the module.
/// @param m The _native module.
void add_connection(nanobind::module_ &m);

} // namespace sq::bindings
