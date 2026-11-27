---
type: note
tags: [glossary, domain-terms, sqlearn, pipelines, terminology]
summary: "Glossary defining sqlearn domain terms: recipe, learned part, stable key, and trained model for saved pipelines."
related: [docs/adr/archived/0047-a-pipeline-saves-as-json.md, docs/adr/archived/0048-the-user-saves-the-model-and-imports-its-packages.md]
mdindex: [type=edb465, tags=7200c2]
---
# Glossary

Terms of sqlearn's domain, in the sense the code and the docs use them.

- **Feature selector:** a step of `sq.select` (`variance`, `best`,
  `percentile`): it learns a score per column and keeps some columns, passing
  them through unchanged. `best` and `percentile` learn from the target but do
  not cross-fit.
  _Avoid_: selector (that means a column selector, `sq.cols`).
- **Recipe:** the part of a saved pipeline that says what to build: each
  step's class and settings, in order, and the model by its class and
  parameters. It holds no data and no learned value, and can be shared
  (`sq.save(pipe, path, learned=False)`).
- **Learned part:** the part of a saved pipeline that holds what its steps
  learned (each step's learned values, the columns and types `apply` needs)
  and the fingerprint of the data they came from. Absent from a recipe.
- **Stable key:** the second key under which the learning store files a
  step's learned values, made of facts that mean the same in every process
  (a file's real path, size and modification time), as opposed to the live
  key, which holds a connection token that only one process knows. Loading a
  saved pipeline fills the store by it.
- **Trained model:** the model library's own object after `train`
  (`pipe.model_`). The user saves and opens it, in any format; a saved
  pipeline never holds it, and `use_model` puts it back.
  _Avoid_: model file.
- **Work ticket:** one row of a ticket table in `meta_sqlearn`: a number that
  stands for one block of row numbers. The generators in `old_python/devdata/`
  widen tickets into row numbers, so that DuckDB can share the work between
  threads. Ticket tables are never changed once made.
- **meta_sqlearn:** the in-memory database `old_python/devdata/` attaches beside
  the connection's own, to hold its ticket tables
  (`meta_sqlearn.main.tickets_<groups>`). Written only through a cursor, gone
  when the connection closes, and never trusted unless it holds only these
  tables. Not part of the sqlearn package.
- **Gram step:** a step that learns from the matrix XᵀX of its centred input
  columns, which the core builds in numpy from batches DuckDB streams (ADR
  0058). `sq.decompose.pca` is one. Internal for now; it learns in a run of
  its own, and applying it is SQL as for any step.
- **Profile:** the answer of `sq.explore.profile`: a relation with one row per
  column holding its type, counts, statistics and notes, computed now inside
  DuckDB. Not a step: nothing is learned for later.
  _Avoid_: summary, describe.
- **Note:** a flag in a profile's `notes` list, one of `all-missing`,
  `constant`, `id-like` and `high-cardinality`, each with a rule that can be
  checked and a step that answers it.
  _Avoid_: warning (a warning is sqlearn's, with a `Fix:`).
- **Missing pattern:** the set of chosen columns that are missing together in
  a row (NULL, and NaN in a float column); `sq.explore.missing` lists the
  commonest, the empty set (nothing missing) among them.
- **Native engine:** sqlearn's C++ library with its kernels, registered in
  sqlearn's DuckDB build; its SQL functions start with `sqlearn_` (ADR 0060).
- **sqlearn's C++ library:** all of sqlearn in C++, embedding DuckDB and
  written against its internal C++ API: the pipeline, the steps, the SQL it
  builds, the store, search, saving, exploration, metrics and later the models.
  Its C++ API is internal; only `sq.` is public (ADR 0060).
- **The bindings:** sqlearn's Python layer, written with nanobind: it converts
  arguments, hands Python objects to the C++ and keeps `sq.`'s names,
  docstrings and errors, and holds no logic of its own (ADR 0060).
- **sqlearn's DuckDB build:** the `duckdb` module sqlearn installs, by default
  as a second package (Phase 1 may make it one; ADR 0061): DuckDB from its
  official source at a pinned release, with the engine and the extensions
  sqlearn needs compiled in (ADR 0061). _Avoid_: fork.
- **Kernel:** one of the engine's computations over DuckDB's columns, with a
  CPU version everywhere and, on Apple silicon, perhaps a Metal version that
  gives the same answer (ADR 0063, 0064); Phase 6 also tries Mojo, which
  becomes the kernels' language if it matches Metal (ADR 0063).
- **Plain-SQL twin:** the DuckDB SQL that computes what an engine function in
  apply computes, kept so the SQL runs in any DuckDB (ADR 0060).
