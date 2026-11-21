---
type: adr
tags: [duckdb, packaging, dependencies, extensions, offline, architecture-decision]
summary: "Records that sqlearn ships its own DuckDB build, installed as the duckdb module in a second package pinned to one release, checked at start, with no extension downloaded by itself; amends ADRs 0005, 0006 and 0057."
related: [docs/adr/0005-runtime-dependencies.md, docs/adr/0006-local-and-offline.md, docs/adr/0057-numpy-is-a-runtime-dependency.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/specs/native-engine.md]
---
# 0061: sqlearn ships its own DuckDB build

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.2). Amends
[ADR 0005](0005-runtime-dependencies.md),
[ADR 0006](0006-local-and-offline.md) and
[ADR 0057](0057-numpy-is-a-runtime-dependency.md). Revised before merging
(2026-11-21), with the spec's revision: one DuckDB in the process, shared
with the C++ library.

## Context

The engine is C++ inside DuckDB (ADR 0060). It must reach the user's
DuckDB. Bundling sqlearn's own build avoids signing and version matching,
and gives full control over what is compiled in.

A drop-in keeps users' code and sqlearn's tests unchanged: they keep
`import duckdb`. Two packages, one for sqlearn and one for the build, are the
default: a change to sqlearn then ships without rebuilding DuckDB. The speed
is the same as in one package.

Three other ways were weighed:

- **The official DuckDB with the engine loaded into it.** That needs
  signing. `allow_unsigned_extensions` can only be set when a database
  opens. The community build needs a public repository and follows only
  DuckDB's latest release. It also needs a version match with whatever
  DuckDB the user has.
- **Our build under a private name inside sqlearn.** Two DuckDBs in one
  process, data that cannot cross between them, and 42 test files to
  change.
- **One package holding both.** Every Python fix ships DuckDB again, and the
  identical program is no faster.

## Decision

- **sqlearn bundles its own DuckDB,** built from the sources of DuckDB and
  of its Python package at a release tag: git submodules, never a fork, so
  an upgrade is a tag change. The engine and the extensions sqlearn needs
  are compiled in: today `core_functions`, `parquet`, `json` and `icu`, as
  in the official build (checked on 2.0.0), and later what sqlearn needs.
- **It installs as the `duckdb` module,** in place of the official package.
  Users' code, sqlearn's code and the tests keep `import duckdb` and get one
  DuckDB, shared. The official package cannot be installed beside it, since
  both are the `duckdb/` folder. In sqlearn's own environment nothing else
  needs it (checked with `uv tree --invert`).
- **It ships as a second package,** installed by the same `uv add sqlearn`.
  Its name is chosen in Phase 1; `sqlearn-duckdb` is a placeholder. sqlearn
  requires its exact version. A change to sqlearn then ships without
  rebuilding DuckDB. Two packages are the default, which Phase 1 may make
  one (the next bullet).
- **One DuckDB in the process.** The `duckdb` module and sqlearn's C++
  library must run in the same DuckDB, so that a user's connection
  (`sq.set_config(connection=con)`) and the data frames they hand in reach
  the C++ as they are, and the C++ is handed the C++ connection behind the
  Python one. Two copies of DuckDB linked into two binaries would be two
  databases that cannot see each other's data. Phase 1 decides how: both
  packages linking one shared DuckDB library, or the C++ library compiled
  into the DuckDB build's package. If the second, the two packages become
  one, and the reason above for two lapses.
- **At start, sqlearn checks that `duckdb` is its build** (the engine
  answers). If another package has replaced it with the official one,
  sqlearn refuses with its `Why:` and `Fix:` lines.
- **Accepted cost** (Tomas: "who needs 2 installs of duckdb?"): a package
  that needs the official `duckdb` (dbt-duckdb, Ibis, jupysql, sqlmesh, dlt
  and others) cannot share an environment with sqlearn. The installer puts
  both in without a conflict. They overwrite each other's files, and
  removing either breaks the other. The start-up check catches the case
  where the official one won. Its `Fix:` says to reinstall sqlearn's DuckDB,
  and that such a package needs an environment of its own for now.
- **Ways round, if users ask:** the same build also served under the name
  `duckdb` with a local version (`2.0.1+sqlearn.1`) from sqlearn's own
  package index, as PyTorch serves its CUDA builds (never on PyPI), or an
  override in the user's own uv project.
- **Pinned to one DuckDB release,** 2.0.1 first (a long-term-support line,
  to at least October 2027). Each new release gets an upgrade branch: read
  the release notes and the changes in what sqlearn uses (the C++ headers
  the engine includes, the Python API sqlearn calls), move the pin, rebuild,
  run `just verify` and the benchmarks before and after, and re-test each
  DuckDB workaround sqlearn carries. Each workaround gets a canary test that
  fails the day DuckDB fixes it and names the workaround to delete. A `just`
  recipe lists the DuckDB releases newer than the pin.
- **Nothing downloads by itself.** The official build installs and loads
  extensions from the network when a query needs one
  (`autoinstall_known_extensions` is on). sqlearn's build turns that off and
  compiles in what sqlearn needs (amends 0006's consequences).
- **A user may still install an extension by asking for it** (`INSTALL
  spatial`, or httpfs for `s3://` files, excel, iceberg; Tomas, 2026-11-21).
  They chose it, and nothing sqlearn does needs the network (ADR 0006).
  Phase 1 tests that DuckDB's official extensions load and work in
  sqlearn's build, which is compiled differently. One that fails is refused
  with a `Fix:` until it works.
- **A user's own DuckDB is not supported,** and is added only if users ask.
  Then the same engine is also built as a loadable extension for the
  official package, which needs an exact version match and signing (DuckDB
  2.0's repositories trusted with a publisher's own key, to be tested
  then).
- **Runtime dependencies** (amends 0005 and 0057): sqlearn's DuckDB build
  replaces `duckdb` from PyPI. numpy stays until the engine's linear algebra
  (Phase 3), when ADR 0057 is decided again.

## Consequences

- One DuckDB is shared by the user and sqlearn.
- No package that needs the official `duckdb` can share an environment with
  sqlearn.
- Each DuckDB release costs an upgrade branch.
- DuckDB's third-party code ships in sqlearn's builds, so its licences come
  with them (ADR 0066).
