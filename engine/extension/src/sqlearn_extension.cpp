/// @file
/// The sqlearn extension's entry: DuckDB calls it for every database it
/// opens, since the extension is statically linked into _duckdb.
#include "core/version.hpp"

#include "duckdb.hpp"
#include "duckdb/function/scalar_function.hpp"
#include "duckdb/main/config.hpp"
#include "duckdb/main/extension/extension_loader.hpp"
#include "duckdb/main/settings.hpp"

namespace {

/// sqlearn_version(): the build in one line, core::describe's.
/// @param args The (empty) arguments; only their row count is read.
/// @param state Unused.
/// @param result A constant vector of the line.
void sqlearn_version(duckdb::DataChunk &args, duckdb::ExpressionState &state,
                     duckdb::Vector &result) {
    (void)state;
    result.Reference(duckdb::Value(sq::core::describe(sq::core::build_identity())),
                     duckdb::count_t(args.size()));
}

/// Turn automatic installs of known extensions off for `db`, unless the user
/// set autoinstall_known_extensions when opening it (ADR 0006, 0061): DuckDB
/// 2.0 has no build switch for the default. A user's value is in the
/// database's user settings, set before extensions load; a default is not.
/// @param db The database being opened.
void no_downloads_by_default(duckdb::DatabaseInstance &db) {
    auto &config = duckdb::DBConfig::GetConfig(db);
    using Setting = duckdb::AutoinstallKnownExtensionsSetting;
    if (!config.user_settings.IsSet(Setting::SettingIndex)) {
        config.SetOptionByName(Setting::Name, duckdb::Value::BOOLEAN(false));
    }
}

} // namespace

extern "C" {

/// The entry DuckDB's static loader calls for each new database.
DUCKDB_CPP_EXTENSION_ENTRY(sqlearn, loader) {
    no_downloads_by_default(loader.GetDatabaseInstance());
    loader.RegisterFunction(duckdb::ScalarFunction("sqlearn_version", duckdb::vector<duckdb::LogicalType>{},
                                                   duckdb::LogicalType::VARCHAR, sqlearn_version));
}
}
