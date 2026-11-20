---
type: note
tags: [glossary, terminology, domain, sqlearn, pipelines]
summary: "Glossary defining sqlearn domain terms: recipe, learned part, stable key, and trained model for saved pipelines."
related: [docs/adr/0047-a-pipeline-saves-as-json.md, docs/adr/0048-the-user-saves-the-model-and-imports-its-packages.md]
mdindex: [type=edb465, tags=f09dae]
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
  stands for one block of row numbers. The generators in `devdata/` widen
  tickets into row numbers, so that DuckDB can share the work between threads.
  Ticket tables are never changed once made.
- **meta_sqlearn:** the in-memory database `devdata/` attaches beside the
  connection's own, to hold its ticket tables
  (`meta_sqlearn.main.tickets_<groups>`). Written only through a cursor, gone
  when the connection closes, and never trusted unless it holds only these
  tables. Not part of the sqlearn package.
